#!/usr/bin/env python3
"""Riset: kalau kita copy trade wallet top kolscan, untung atau tidak?

  python3 riset/copytrade.py fetch   --out riset/data   # di GitHub Actions (butuh internet ke RPC + kolscan)
  python3 riset/copytrade.py analyze --out riset/data   # olah data yang sudah diambil, tanpa internet

Cara kerja fetch:
  1. Ambil daftar wallet dari leaderboard kolscan (urutan = ranking).
  2. Ambil histori transaksi tiap wallet lewat RPC publik Solana. Trade dibaca dari perubahan saldo
     token + SOL wallet itu (berlaku untuk semua venue: kurva pump.fun, PumpSwap, router).
  3. Untuk tiap beli pembuka posisi dan tiap jual di kurva pump.fun, ambil harga kurva beberapa slot
     sesudahnya (1, 3, 8, 13 slot = 0.4, 1.2, 3.2, 5.2 detik) dari TradeEvent transaksi lain di koin itu.
Analyze mensimulasikan copy dengan ukuran tetap, fee 1.25%, slippage 2%, priority fee 0.0005 SOL,
dan dampak harga kurva. Tidak ada kode live / kunci privat di sini.
"""
import argparse, base64, gzip, json, math, os, re, sys, time, urllib.request, urllib.error

RPC = os.environ.get("RPC_HTTP", "https://api.mainnet-beta.solana.com")
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
WSOL = "So11111111111111111111111111111111111111112"
DISC_TRADE = bytes([189, 219, 127, 211, 78, 230, 97, 238])
SLOTS = [1, 3, 8, 13]                      # jeda copy dalam slot (~0.4 dtk per slot)
FEE, SLIP, PRIO = 0.0125, 0.02, 0.0005
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def b58(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def trade_events(logs):
    """TradeEvent pump.fun dari log: mint, sol, tok, buy, user, v_sol, v_tok (sesudah trade)."""
    out = []
    for line in logs or []:
        if not line.startswith("Program data: "):
            continue
        try:
            raw = base64.b64decode(line[14:])
        except ValueError:
            continue
        if raw[:8] != DISC_TRADE or len(raw) < 8 + 32 + 8 + 8 + 1 + 32 + 8 + 16:
            continue
        i = 8
        mint = b58(raw[i:i + 32]); i += 32
        sol = int.from_bytes(raw[i:i + 8], "little") / 1e9; i += 8
        tok = int.from_bytes(raw[i:i + 8], "little") / 1e6; i += 8
        buy = raw[i] != 0; i += 1
        user = b58(raw[i:i + 32]); i += 32
        i += 8                                         # timestamp
        v_sol = int.from_bytes(raw[i:i + 8], "little") / 1e9; i += 8
        v_tok = int.from_bytes(raw[i:i + 8], "little") / 1e6
        out.append({"mint": mint, "sol": sol, "tok": tok, "buy": buy, "user": user, "v_sol": v_sol, "v_tok": v_tok})
    return out


# ---------------------------------------------------------------- RPC

class Rpc:
    def __init__(self, rate=8.0):
        self.gap, self.last, self.n, self.err = 1.0 / rate, 0.0, 0, 0

    def call(self, method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        for attempt in range(8):
            wait = self.last + self.gap - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.n += 1
            try:
                req = urllib.request.Request(RPC, body, {"content-type": "application/json", "user-agent": UA})
                with urllib.request.urlopen(req, timeout=40) as r:
                    d = json.load(r)
                if "error" in d:
                    msg = str(d["error"])
                    if "429" in msg or "rate" in msg.lower() or "-32005" in msg:
                        raise urllib.error.HTTPError(RPC, 429, msg, None, None)
                    self.err += 1
                    return None
                return d.get("result")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                code = getattr(e, "code", 0)
                time.sleep(min(60, 2 ** attempt * (3 if code == 429 else 1)))
        self.err += 1
        return None

    def sigs(self, addr, limit=1000, before=None, until=None):
        o = {"limit": limit, "commitment": "confirmed"}
        if before:
            o["before"] = before
        if until:
            o["until"] = until
        return self.call("getSignaturesForAddress", [addr, o]) or []

    def tx(self, sig):
        return self.call("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                                  "commitment": "confirmed"}])


# ---------------------------------------------------------------- fetch

def kolscan_wallets(n):
    req = urllib.request.Request("https://kolscan.io/leaderboard", headers={"user-agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    seen, out = set(), []
    for m in re.finditer(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])", html):
        a = m.group(0)
        if a in seen or a in (PUMP, WSOL):
            continue
        seen.add(a)
        # nama KOL biasanya ada dekat alamat di payload Next.js
        ctx = html[max(0, m.start() - 300):m.end() + 300]
        nm = re.search(r'name\\?"\s*:\s*\\?"([^"\\]{1,40})', ctx)
        out.append({"wallet": a, "name": nm.group(1) if nm else ""})
        if len(out) >= n:
            break
    return out


def wallet_trade(tx, wallet):
    """Trade wallet di satu transaksi dari perubahan saldo: dict atau None."""
    meta, msg = tx.get("meta") or {}, (tx.get("transaction") or {}).get("message") or {}
    if meta.get("err"):
        return None
    keys = list(msg.get("accountKeys") or [])
    la = meta.get("loadedAddresses") or {}
    keys += la.get("writable", []) + la.get("readonly", [])
    if wallet not in keys:
        return None
    wi = keys.index(wallet)
    sol = (meta["postBalances"][wi] - meta["preBalances"][wi]) / 1e9
    tok = {}
    for side, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for b in meta.get(side) or []:
            if b.get("owner") != wallet:
                continue
            ua = b.get("uiTokenAmount") or {}
            amt = float(ua.get("uiAmountString") or ua.get("uiAmount") or 0)
            tok[b["mint"]] = tok.get(b["mint"], 0.0) + sign * amt
    sol += tok.pop(WSOL, 0.0)
    tok = {m: v for m, v in tok.items() if abs(v) > 1e-9}
    if len(tok) != 1:
        return None
    mint, dt = next(iter(tok.items()))
    if (dt > 0 and sol >= 0) or (dt < 0 and sol <= 0):
        return None                                   # transfer/airdrop, bukan trade
    ev = [e for e in trade_events(meta.get("logMessages")) if e["mint"] == mint and e["user"] == wallet]
    t = {"mint": mint, "tok": dt, "sol": sol, "slot": tx["slot"], "t": tx.get("blockTime"),
         "sig": (tx["transaction"].get("signatures") or [""])[0], "curve": bool(ev)}
    if ev:
        e = ev[-1]
        t.update(c_sol=round(sum(x["sol"] for x in ev), 9), c_tok=round(sum(x["tok"] for x in ev), 6),
                 v_sol=e["v_sol"], v_tok=e["v_tok"])
    return t


def rounds(trades):
    """Kelompokkan trade satu wallet per koin jadi ronde: beli pembuka .. posisi habis."""
    by = {}
    for t in sorted(trades, key=lambda x: (x["slot"], x["sig"])):
        by.setdefault(t["mint"], []).append(t)
    out = []
    for mint, ts in by.items():
        pos, peak, cur = 0.0, 0.0, None
        for t in ts:
            if t["tok"] > 0:
                if cur is None or pos <= peak * 0.01:
                    cur = {"mint": mint, "open": t, "adds": [], "sells": [], "sol_in": 0.0, "sol_out": 0.0}
                    out.append(cur)
                    pos, peak = 0.0, 0.0
                else:
                    cur["adds"].append(t)
                pos += t["tok"]
                peak = max(peak, pos)
                cur["sol_in"] += -t["sol"]
            elif cur is not None and pos > 0:
                frac = min(1.0, -t["tok"] / pos)
                pos = max(0.0, pos + t["tok"])
                cur["sells"].append(dict(t, frac=frac))
                cur["sol_out"] += t["sol"]
        if cur is not None:
            cur["left"] = pos / peak if peak else 0.0
    for r in out:
        r.setdefault("left", 0.0)
    return out


def anchor_after(slots_sorted, sigs_sorted, slot):
    """Signature wallet pertama dengan slot > slot (batas 'before' saat membaca histori koin)."""
    import bisect
    i = bisect.bisect_right(slots_sorted, slot)
    return sigs_sorted[i] if i < len(sigs_sorted) else None


def curve_points(rpc, mint, ev_sig, ev_slot, anchor, cache, max_pages=5):
    """Harga kurva (v_sol, v_tok) di ev_slot + SLOTS, dari transaksi lain di koin itu sesudah ev_sig.
    None kalau jendelanya tidak terjangkau."""
    lst, before, reached = [], anchor, False
    for _ in range(max_pages):
        page = rpc.sigs(mint, 1000, before=before, until=ev_sig)
        lst += page
        if len(page) < 1000 or (page and page[-1]["slot"] <= ev_slot + max(SLOTS)):
            reached = True
            break
        before = page[-1]["signature"]
    if not reached:
        return None, 0
    later = sorted([s for s in lst if not s.get("err") and ev_slot < s["slot"] <= ev_slot + max(SLOTS)],
                   key=lambda s: s["slot"])
    out = {}
    for k in SLOTS:
        cand = [s for s in later if s["slot"] <= ev_slot + k]
        state = None
        for s in reversed(cand):                       # transaksi terakhir yang benar-benar trade di kurva
            sg = s["signature"]
            if sg not in cache:
                tx = rpc.tx(sg)
                evs = [e for e in trade_events(((tx or {}).get("meta") or {}).get("logMessages")) if e["mint"] == mint]
                cache[sg] = [evs[-1]["v_sol"], evs[-1]["v_tok"]] if evs else None
            if cache[sg]:
                state = cache[sg]
                break
        out[str(k)] = state                            # None = tidak ada trade lain -> harga = sesudah trade dia
    return out, len(later)


def fetch(args):
    os.makedirs(args.out, exist_ok=True)
    rpc = Rpc(args.rate)
    t_start = time.time()
    deadline = t_start + args.minutes * 60
    try:
        sol_usd = json.load(urllib.request.urlopen(urllib.request.Request(
            "https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
            headers={"user-agent": UA}), timeout=20))["solana"]["usd"]
    except Exception:
        sol_usd = None
    wallets = kolscan_wallets(args.wallets)
    print(f"[fetch] {len(wallets)} wallet dari kolscan, SOL ${sol_usd}", flush=True)
    data = {"fetched_at": time.time(), "sol_usd": sol_usd, "slots": SLOTS, "wallets": [], "after": {}}
    budget_per_wallet = (args.minutes * 60 * 0.5) / max(1, len(wallets))
    anchors = {}
    for wi, w in enumerate(wallets):
        t_w = time.time()
        sigs, before = [], None
        while len(sigs) < args.max_sigs:
            page = rpc.sigs(w["wallet"], 1000, before=before)
            if not page:
                break
            sigs += page
            if len(page) < 1000 or (page[-1].get("blockTime") or 0) < time.time() - args.days * 86400:
                break
            before = page[-1]["signature"]
        asc = sorted(((s["slot"], s["signature"]) for s in sigs), key=lambda x: x[0])
        anchors[w["wallet"]] = ([a for a, _ in asc], [b for _, b in asc])
        sigs = [s for s in sigs[:args.max_sigs] if not s.get("err")
                and (s.get("blockTime") or 0) >= time.time() - args.days * 86400]
        trades, n_read = [], 0
        for s in sigs:
            if time.time() - t_w > budget_per_wallet or time.time() > deadline:
                break
            tx = rpc.tx(s["signature"])
            n_read += 1
            if tx:
                t = wallet_trade(tx, w["wallet"])
                if t:
                    trades.append(t)
        read = sigs[:n_read]
        w.update(n_sigs=len(read), trades=trades,
                 span_h=round(((read[0].get("blockTime") or 0) - (read[-1].get("blockTime") or 0)) / 3600, 1) if read else 0)
        print(f"[fetch] {wi + 1}/{len(wallets)} {w['name'] or w['wallet'][:6]}: {n_read}/{len(sigs)} tx dibaca, "
              f"{len(trades)} trade, rentang {w['span_h']} jam, rpc {rpc.n} call ({rpc.err} gagal), "
              f"{time.time() - t_start:.0f}s", flush=True)
        data["wallets"].append(w)
    save(args.out, data)
    cache, jobs = {}, []
    for w in data["wallets"]:
        sl, sg = anchors[w["wallet"]]
        for r in rounds(w["trades"]):
            for ev in ([r["open"]] if r["open"]["curve"] else []) + [s for s in r["sells"] if s["curve"]]:
                jobs.append((ev, anchor_after(sl, sg, ev["slot"] + max(SLOTS))))
    jobs.sort(key=lambda j: -j[0]["slot"])            # terbaru dulu kalau waktu habis
    print(f"[fetch] {len(jobs)} titik harga kurva untuk dicari", flush=True)
    done = miss = 0
    for ev, anchor in jobs:
        if time.time() > deadline:
            break
        pts, n_later = curve_points(rpc, ev["mint"], ev["sig"], ev["slot"], anchor, cache)
        if pts is None:
            miss += 1
        else:
            data["after"][ev["sig"]] = pts
        done += 1
        if done % 200 == 0:
            print(f"[fetch] harga {done}/{len(jobs)} ({miss} tak terjangkau), rpc {rpc.n} ({rpc.err} gagal), "
                  f"{time.time() - t_start:.0f}s", flush=True)
            save(args.out, data)
    data.update(price_jobs=len(jobs), price_done=done, price_miss=miss, rpc_calls=rpc.n, rpc_err=rpc.err)
    save(args.out, data)
    print(f"[fetch] selesai: harga {done}/{len(jobs)} ({miss} tak terjangkau), rpc {rpc.n} call "
          f"({rpc.err} gagal), {time.time() - t_start:.0f}s")


def save(out, data):
    p = os.path.join(out, "raw.json.gz")
    with gzip.open(p + ".tmp", "wt") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(p + ".tmp", p)


# ---------------------------------------------------------------- analyze

def curve_buy(v_sol, v_tok, sol_in):
    return v_tok - v_sol * v_tok / (v_sol + sol_in)


def curve_sell(v_sol, v_tok, tok_in):
    return v_sol - v_sol * v_tok / (v_tok + tok_in)


def sim_round(r, delay, size_sol, after):
    """Hasil copy satu ronde (SOL keluar/masuk) dengan jeda 'delay' (0 = harga sama persis dengan dia,
    atau jumlah slot). None kalau data harga tidak lengkap."""
    o = r["open"]
    if not o.get("curve"):
        return None
    if delay == 0:
        st = (o["v_sol"] - o["c_sol"], o["v_tok"] + o["c_tok"])   # kondisi kurva sebelum dia beli
    else:
        a = after.get(o["sig"])
        if a is None:
            return None
        st = a.get(str(delay)) or (o["v_sol"], o["v_tok"])
    buy_sol = size_sol - PRIO
    tokens = curve_buy(st[0], st[1], buy_sol * (1 - FEE)) * (1 - SLIP)
    held, got, flags = tokens, 0.0, set()
    for s in r["sells"]:
        last = s is r["sells"][-1] and r["left"] <= 0.01
        q = held if last else held * s["frac"]
        if q <= 0:
            continue
        if s.get("curve"):
            if delay == 0:
                st = (s["v_sol"] + s["c_sol"], s["v_tok"] - s["c_tok"])   # kondisi sebelum dia jual
            else:
                a = after.get(s["sig"])
                if a is None:
                    return None
                st = a.get(str(delay)) or (s["v_sol"], s["v_tok"])
            sol = curve_sell(st[0], st[1], q)
        else:
            # dia jual di luar kurva (sudah migrasi ke PumpSwap): pakai harga rata-rata jual dia (optimis)
            sol = q * (s["sol"] / -s["tok"])
            flags.add("amm")
        got += max(0.0, sol * (1 - FEE) * (1 - SLIP) - PRIO)
        held -= q
    if held > tokens * 0.01:
        flags.add("open")                              # dia belum jual semua: sisa dihitung 0 (pesimis)
    return {"x": got / size_sol, "flags": sorted(flags)}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def summarize(label, rows, sol_usd, start_usd=200.0, per_trade_usd=20.0):
    n = len(rows)
    if n == 0:
        print(f"  {label}: 0 trade")
        return
    xs = [x for _, x in rows]
    w = sum(x > 1 for x in xs)
    lo, hi = wilson(w, n)
    mean = sum(xs) / n
    med = sorted(xs)[n // 2]
    bal, peak_dd, peak = start_usd, 0.0, start_usd
    for _, x in sorted(rows):
        if bal < per_trade_usd:
            break
        bal += per_trade_usd * (x - 1)
        peak = max(peak, bal)
        peak_dd = max(peak_dd, 1 - bal / peak)
    note = "  (<30 trade, belum bisa disimpulkan)" if n < 30 else ""
    print(f"  {label}: n={n}, winrate {w / n:.0%} (95% CI {lo:.0%}-{hi:.0%}), rata-rata {mean:.2f}x, median {med:.2f}x"
          f" | simulasi $200 (${per_trade_usd:.0f}/trade): akhir ${bal:,.0f} ({bal / start_usd - 1:+.0%}), "
          f"drawdown maks {peak_dd:.0%}{note}")


def analyze(args):
    with gzip.open(os.path.join(args.out, "raw.json.gz"), "rt") as f:
        data = json.load(f)
    sol_usd = data.get("sol_usd") or 150.0
    size_sol = 20.0 / sol_usd
    t_fetch = data["fetched_at"]
    cut = t_fetch - 24 * 3600                           # jendela leaderboard (harian) = in-sample
    print(f"Data diambil {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(t_fetch))}, SOL ${sol_usd}, "
          f"ukuran copy $20 ({size_sol:.3f} SOL), fee {FEE:.2%}, slippage {SLIP:.0%}, priority {PRIO} SOL")
    print(f"Titik harga kurva dicari {data.get('price_done')}/{data.get('price_jobs')} ({data.get('price_miss')} tak terjangkau), rpc {data.get('rpc_calls')} call "
          f"({data.get('rpc_err')} gagal)\n")
    allr = []
    print("Per wallet (hasil dia sendiri, semua venue, dari perubahan saldo):")
    for w in data["wallets"]:
        rs = rounds(w["trades"])
        closed = [r for r in rs if r["left"] <= 0.01 and r["sol_in"] > 0]
        pnl = sum(r["sol_out"] - r["sol_in"] for r in closed)
        wins = sum(r["sol_out"] > r["sol_in"] for r in closed)
        print(f"  {w['name'] or '-':<16} {w['wallet'][:8]}  {w['n_sigs']:>5} tx  rentang {w['span_h']:>6} jam  "
              f"{len(rs):>4} ronde ({len(closed)} tutup, win {wins}/{len(closed) or 1})  PnL tutup {pnl:+.1f} SOL")
        for r in rs:
            r["wallet"] = w["wallet"]
        allr += rs
    delays = [0] + SLOTS
    print("\nCopy trade semua wallet (beli pembuka di kurva pump.fun saja):")
    stats = {}
    for period, sel in (("SEBELUM masuk leaderboard (>24 jam lalu) = out-of-sample", lambda r: r["open"]["t"] and r["open"]["t"] < cut),
                        ("24 jam terakhir = jendela leaderboard, IN-SAMPLE (terlalu bagus)", lambda r: r["open"]["t"] and r["open"]["t"] >= cut)):
        print(f"\n {period}")
        for d in delays:
            rows, skip, fl = [], 0, {}
            for r in allr:
                if not sel(r):
                    continue
                res = sim_round(r, d, size_sol, data.get("after", {}))
                if res is None:
                    skip += 1
                    continue
                for f_ in res["flags"]:
                    fl[f_] = fl.get(f_, 0) + 1
                rows.append((r["open"]["t"], res["x"]))
            lab = "jeda 0 (harga sama persis dengan dia)" if d == 0 else f"jeda {d} slot (~{d * 0.4:.1f} dtk)"
            summarize(lab, rows, sol_usd)
            if skip or fl:
                print(f"      dilewati {skip} (data harga kurang), jual di AMM {fl.get('amm', 0)} (pakai harga dia, optimis),"
                      f" masih dipegang {fl.get('open', 0)} (dihitung 0)")
            stats[(period[:7], d)] = rows
    print("\nCatatan: wallet dipilih dari leaderboard HARI INI, jadi periode 24 jam terakhir pasti kelihatan bagus.\n"
          "Yang relevan untuk keputusan adalah periode sebelumnya, dan jeda >=1 slot (jeda 0 tidak mungkin dicapai).")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["fetch", "analyze"])
    ap.add_argument("--out", default="riset/data")
    ap.add_argument("--wallets", type=int, default=12)
    ap.add_argument("--max-sigs", type=int, default=1500)
    ap.add_argument("--days", type=float, default=7)
    ap.add_argument("--minutes", type=float, default=150)
    ap.add_argument("--rate", type=float, default=8)
    a = ap.parse_args()
    fetch(a) if a.mode == "fetch" else analyze(a)


if __name__ == "__main__":
    main()

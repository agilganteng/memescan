"""Bedah satu wallet (28 Okt 2026): pola beli/jual dari rekaman memescan + riwayat transaksi on-chain (RPC publik).

Pakai: python3 riset/wallet_cek.py --data data --addr <alamat> [--n-tx 400]
Hanya membaca data publik. Tidak ada kunci privat / trading.
"""
import argparse
import base64
import bisect
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import memescan as ms  # noqa: E402

RPC = os.environ.get("RPC_HTTP", "https://api.mainnet-beta.solana.com")
PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
DISC_TRADE = bytes([189, 219, 127, 211, 78, 230, 97, 238])
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
JITO_TIPS = {"96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
             "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
             "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
             "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"}
KNOWN = {PUMP: "pump.fun kurva", PUMPSWAP: "PumpSwap", "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter",
         "ComputeBudget111111111111111111111111111111": "ComputeBudget (priority fee)",
         "11111111111111111111111111111111": "System (transfer SOL)",
         "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token program",
         "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "Token-2022",
         "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated Token",
         "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ": "pump.fun fee"}


def b58(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def trade_events(logs):
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
        i += 8
        v_sol = int.from_bytes(raw[i:i + 8], "little") / 1e9; i += 8
        v_tok = int.from_bytes(raw[i:i + 8], "little") / 1e6
        out.append({"mint": mint, "sol": sol, "tok": tok, "buy": buy, "user": user, "v_sol": v_sol, "v_tok": v_tok})
    return out


class Rpc:
    def __init__(self, rate=4.0):
        self.gap, self.last, self.err = 1.0 / rate, 0.0, 0

    def call(self, method, params):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
        for attempt in range(7):
            wait = self.last + self.gap - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                req = urllib.request.Request(RPC, body, {"content-type": "application/json", "user-agent": UA})
                with urllib.request.urlopen(req, timeout=40) as r:
                    d = json.load(r)
                if "error" in d:
                    msg = str(d["error"])
                    if "429" in msg or "rate" in msg.lower():
                        raise urllib.error.HTTPError(RPC, 429, msg, None, None)
                    self.err += 1
                    return None
                return d.get("result")
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
                time.sleep(min(60, 2 ** attempt * (3 if getattr(e, "code", 0) == 429 else 1)))
        self.err += 1
        return None


def wallet_trade(tx, wallet):
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
    progs = [keys[ix["programIdIndex"]] for ix in msg.get("instructions") or [] if ix["programIdIndex"] < len(keys)]
    jito = sum(1 for k in keys if k in JITO_TIPS)
    base = {"slot": tx["slot"], "t": tx.get("blockTime"), "fee": meta.get("fee", 0) / 1e9, "progs": progs,
            "jito": bool(jito), "signer": keys[0] == wallet}
    if len(tok) != 1:
        return dict(base, kind="lain", sol=sol)
    mint, dt = next(iter(tok.items()))
    if (dt > 0 and sol >= 0) or (dt < 0 and sol <= 0):
        return dict(base, kind="transfer", mint=mint, tok=dt, sol=sol)
    ev = [e for e in trade_events(meta.get("logMessages")) if e["mint"] == mint and e["user"] == wallet]
    t = dict(base, kind="beli" if dt > 0 else "jual", mint=mint, tok=dt, sol=sol, curve=bool(ev))
    if ev:
        t["mcap"] = ev[-1]["v_sol"] / ev[-1]["v_tok"] * 1e9 if ev[-1]["v_tok"] else 0.0
    return t


def recorder_part(data_dir, pref):
    d = os.path.join(data_dir, "rec")
    rows, n_coins, t_min, t_max = [], 0, math.inf, 0
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                if pref not in line:
                    n_coins += 1
                    continue
                n_coins += 1
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                mine = [x for x in r.get("w") or [] if x[1] == pref]
                if not mine:
                    continue
                t0 = float(r["t0"])
                t_min, t_max = min(t_min, t0), max(t_max, t0)
                cs = [(ms.rec_bucket_start(x[0]), float(x[3])) for x in r["c"]]
                st = [x[0] for x in cs]
                pa = lambda a: cs[max(0, bisect.bisect_right(st, a) - 1)][1] if cs else float(r.get("m0") or 30)
                buys = [(float(a), float(s)) for a, _, b, s in mine if b]
                sells = [(float(a), float(s)) for a, _, b, s in mine if not b]
                tok = sum(s / max(pa(a), 1e-9) for a, s in buys) - sum(s / max(pa(a), 1e-9) for a, s in sells)
                bs, ss = sum(s for _, s in buys), sum(s for _, s in sells)
                peak = max((float(x[1]) for x in r["c"]), default=0.0)
                rows.append(dict(t0=t0, dev=r.get("dev") == pref, buys=buys, sells=sells, bs=bs, ss=ss,
                                 left=max(tok, 0.0) * float(r["c"][-1][3]) if r["c"] else 0.0,
                                 m_buy=pa(buys[0][0]) if buys else float("nan"), peak=peak,
                                 end_mc=float(r["c"][-1][3]) if r["c"] else 0.0, n_trades=len(r["w"])))
    print(f"\n==== DARI REKAMAN MEMESCAN ({n_coins:,} koin pump.fun, trade 5 menit pertama, alamat 10 huruf '{pref}')")
    if not rows:
        print("   Wallet ini tidak muncul di 5 menit pertama koin mana pun yang terekam.")
        return
    print(f"   Muncul di {len(rows):,} koin ({time.strftime('%d/%m %H:%M', time.gmtime(t_min))} - "
          f"{time.strftime('%d/%m %H:%M', time.gmtime(t_max))} UTC). Sebagai dev: {sum(r['dev'] for r in rows)}")
    days = max(1e-9, (t_max - t_min) / 86400)
    print(f"   ~{len(rows) / days:.0f} koin per hari")
    fb = np.array([r["buys"][0][0] for r in rows if r["buys"]])
    if len(fb):
        print(f"   Umur koin saat dia beli pertama: median {np.median(fb):.1f} dtk; < 1 dtk {np.mean(fb < 1):.0%}, "
              f"< 3 dtk {np.mean(fb < 3):.0%}, < 10 dtk {np.mean(fb < 10):.0%}, > 60 dtk {np.mean(fb > 60):.0%}")
        sz = np.array([r["bs"] for r in rows if r["buys"]])
        print(f"   Ukuran beli per koin: median {np.median(sz):.3f} SOL, rata {sz.mean():.3f}, maks {sz.max():.2f}. "
              f"Ukuran yang sama persis berulang: {Counter(np.round(sz, 3)).most_common(3)}")
        mb = np.array([r["m_buy"] for r in rows if r["buys"]])
        print(f"   Mcap saat beli: median {np.median(mb):.1f} SOL (~${np.median(mb) * 200:,.0f})")
    hold = [r["sells"][-1][0] - r["buys"][0][0] for r in rows if r["buys"] and r["sells"]]
    if hold:
        h = np.array(hold)
        print(f"   Lama tahan (beli pertama -> jual terakhir, yang terekam): median {np.median(h):.1f} dtk; "
              f"< 5 dtk {np.mean(h < 5):.0%}, < 30 dtk {np.mean(h < 30):.0%}, < 120 dtk {np.mean(h < 120):.0%}")
    sold = sum(1 for r in rows if r["sells"])
    print(f"   Koin yang sudah dia jual dalam 5 menit: {sold}/{len(rows)} ({sold / len(rows):.0%})")
    res = np.array([(r["ss"] + r["left"]) / r["bs"] for r in rows if r["bs"] > 0])
    if len(res):
        tot_in = sum(r["bs"] for r in rows)
        tot_out = sum(r["ss"] + r["left"] for r in rows)
        print(f"   Hasil sendiri per koin (perkiraan harga candle): median {np.median(res):.3f}x, untung {np.mean(res > 1):.0%}; "
              f"total SOL masuk {tot_in:.2f} -> keluar+sisa {tot_out:.2f} ({tot_out / tot_in - 1:+.1%})")
    print(f"   Nasib koin yang dia beli: puncak 30m median {np.median([r['peak'] for r in rows]):.1f} SOL mcap, "
          f"akhir median {np.median([r['end_mc'] for r in rows]):.1f} SOL")


def rpc_part(addr, n_tx):
    rpc = Rpc()
    sigs, before = [], None
    for _ in range(10):
        o = {"limit": 1000}
        if before:
            o["before"] = before
        page = rpc.call("getSignaturesForAddress", [addr, o]) or []
        if not page:
            break
        sigs += page
        before = page[-1]["signature"]
        if len(page) < 1000:
            break
    print(f"\n==== DARI BLOCKCHAIN (RPC publik): {len(sigs):,} transaksi terbaru diambil")
    if not sigs:
        print("   Gagal ambil / tidak ada transaksi.")
        return
    tt = np.array([s["blockTime"] for s in sigs if s.get("blockTime")], dtype=float)
    span = (tt.max() - tt.min()) / 3600 if len(tt) > 1 else 0
    errs = sum(1 for s in sigs if s.get("err"))
    print(f"   Rentang: {time.strftime('%d/%m %H:%M', time.gmtime(tt.min()))} - "
          f"{time.strftime('%d/%m %H:%M', time.gmtime(tt.max()))} UTC ({span:.1f} jam) -> {len(tt) / max(span, 1e-9):.0f} tx/jam; "
          f"gagal {errs} ({errs / len(sigs):.0%})")
    gaps = np.diff(np.sort(tt))
    if len(gaps):
        print(f"   Jeda antar transaksi: median {np.median(gaps):.0f} dtk, 10% tercepat <= {np.quantile(gaps, 0.1):.0f} dtk, "
              f"tx di detik yang sama {np.mean(gaps == 0):.0%}")
    hrs = Counter(int(time.gmtime(t).tm_hour) for t in tt)
    print("   Aktif per jam UTC: " + " ".join(f"{h:02d}:{hrs.get(h, 0)}" for h in range(24)))
    print(f"   Jam tanpa transaksi sama sekali dalam rentang ini: "
          f"{sum(1 for h in range(24) if hrs.get(h, 0) == 0)} dari 24 (bot biasanya aktif 24 jam)")

    sample = [s["signature"] for s in sigs[:n_tx] if not s.get("err")]
    trades, progs, n_ok = [], Counter(), 0
    for sg in sample:
        tx = rpc.call("getTransaction", [sg, {"encoding": "json", "maxSupportedTransactionVersion": 0}])
        if not tx:
            continue
        n_ok += 1
        t = wallet_trade(tx, addr)
        if t is None:
            continue
        for p in set(t["progs"]):
            progs[p] += 1
        trades.append(t)
    print(f"\n   Detail {n_ok} transaksi terbaru (berhasil dibaca):")
    kinds = Counter(t["kind"] for t in trades)
    print(f"   Jenis: {dict(kinds)}. Ditandatangani wallet ini sendiri: {sum(t['signer'] for t in trades)}; "
          f"pakai tip Jito (bundle/MEV): {sum(t['jito'] for t in trades)}")
    fees = np.array([t["fee"] for t in trades])
    if len(fees):
        print(f"   Fee jaringan per tx: median {np.median(fees):.6f} SOL, maks {fees.max():.5f}")
    print("   Program yang dipanggil (top 12):")
    for p, n in progs.most_common(12):
        print(f"     {n:4d}x  {KNOWN.get(p, '(tidak dikenal = router bot/aggregator?)')}  {p}")
    tr = [t for t in trades if t["kind"] in ("beli", "jual")]
    if not tr:
        return
    b = [t for t in tr if t["kind"] == "beli"]
    s = [t for t in tr if t["kind"] == "jual"]
    venues = Counter("kurva pump.fun" if t.get("curve") else "lain (PumpSwap/DEX)" for t in tr)
    print(f"   Beli {len(b)}, jual {len(s)}, koin berbeda {len({t['mint'] for t in tr})}; venue {dict(venues)}")
    if b:
        sz = np.array([-t["sol"] for t in b])
        print(f"   Ukuran beli: median {np.median(sz):.3f} SOL, rata {sz.mean():.3f}, maks {sz.max():.2f}; "
              f"ukuran berulang {Counter(np.round(sz, 2)).most_common(3)}")
        mc = [t["mcap"] for t in b if t.get("mcap")]
        if mc:
            print(f"   Mcap saat beli (kurva): median {np.median(mc):.1f} SOL")
    # ronde per koin: beli pertama -> jual terakhir dalam sampel
    by = {}
    for t in sorted(tr, key=lambda x: x["slot"]):
        by.setdefault(t["mint"], []).append(t)
    rr = []
    for m, ts in by.items():
        bi = sum(-t["sol"] for t in ts if t["kind"] == "beli")
        so = sum(t["sol"] for t in ts if t["kind"] == "jual")
        tb = [t["t"] for t in ts if t["kind"] == "beli"]
        tsl = [t["t"] for t in ts if t["kind"] == "jual"]
        if bi > 0 and so > 0 and tb and tsl:
            rr.append((so / bi, max(tsl) - min(tb), bi))
    if rr:
        x = np.array([r[0] for r in rr])
        h = np.array([r[1] for r in rr])
        print(f"   Koin yang beli & jualnya ada di sampel: {len(rr)}. Hasil SOL jual/beli: median {np.median(x):.3f}x, "
              f"untung {np.mean(x > 1):.0%}, total {sum(r[0] * r[2] for r in rr) - sum(r[2] for r in rr):+.3f} SOL")
        print(f"   Lama tahan: median {np.median(h):.0f} dtk; < 10 dtk {np.mean(h < 10):.0%}, < 60 dtk {np.mean(h < 60):.0%}, "
              f"< 10 mnt {np.mean(h < 600):.0%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--addr", required=True)
    ap.add_argument("--n-tx", type=int, default=400)
    a = ap.parse_args()
    print(f"== Wallet {a.addr}")
    recorder_part(a.data, a.addr[:10])
    rpc_part(a.addr, a.n_tx)


if __name__ == "__main__":
    main()

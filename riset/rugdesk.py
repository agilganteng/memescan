"""Uji maju (paper) setup "Grok Bot rug desk" dari artikel X @0xboan (17 Okt 2026).

Setup aslinya, angka persis dari config.py artikel:
  LEAD   : token Solana yang baru bayar profil DexScreener (token-profiles/latest)
  FACTS  : laporan rugcheck.xyz, mati kalau: tidak ada laporan, sudah rug, mint/freeze authority
           masih terbuka, ada risiko 'danger', skor > 40, LP terkunci < 90%, top 10 > 30%,
           dev pegang > 5%, ada insider
  POOL   : pool DexScreener terdalam, mati kalau: likuiditas < $30rb, tiket > 1% pool,
           umur < 30 menit atau > 72 jam, >= 20 beli dan 0 jual dalam 1 jam
  JUDGE  : Grok baca X (TIDAK ditiru di sini, butuh kunci xAI berbayar)
  DESK   : tiket $25, maks 4 posisi, maks 6 masuk per hari, berhenti kalau rugi hari itu $50
  EXIT   : likuiditas turun 40% -> keluar | -35% -> keluar | +100% jual 1/2 | +200% jual 1/4 |
           sisanya trailing 30% dari puncak | 6 jam belum +20% -> keluar. Dicek tiap 10 menit.

Tidak bisa diuji mundur (DexScreener tidak menyimpan daftar profil lama), jadi ini perekam maju:
  run     : tiap 2 menit ambil profil baru, cek filter SEKALI (persis artikel) dan catat alasannya;
            harga + likuiditas SEMUA token dicatat tiap 1 menit selama 12 jam
  report  : simulasi desk di atas + pembanding (semua token tanpa filter, token yang dibunuh filter)
Paper saja. Tidak ada wallet, tidak ada kunci.

Pakai: python3 riset/rugdesk.py run --data data --duration 21000
       python3 riset/rugdesk.py report --data data
"""
import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request

PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
DS = "https://api.dexscreener.com/tokens/v1/solana"
RC = "https://api.rugcheck.xyz/v1/tokens"
UA = {"User-Agent": "memescan-riset/1.0 (github.com/agilganteng/memescan)", "Accept": "application/json"}

FACTS = {"max_risk_score": 40, "min_lp_locked_pct": 90, "max_top10_pct": 30, "max_dev_pct": 5,
         "max_insiders": 0, "min_liquidity_usd": 30000, "max_ticket_share": 0.01,
         "min_age_min": 30, "max_age_hours": 72}
TICKET, MAX_OPEN, MAX_PER_DAY, DAY_HALT = 25.0, 4, 6, 50.0
EXIT = {"stop_pct": -35, "ladder": [(100, 0.50), (200, 0.25)], "trail_pct": 30,
        "time_stop_hours": 6, "time_stop_min_pct": 20, "liq_drop_pct": 40}
TRACK_H = 12
COST = 0.015          # fee pool + slippage per sisi (tiket <= 1% pool)
PRIO_USD = 0.05       # priority fee per transaksi
START = 200.0


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1) if e.code != 429 else 15 * (i + 1))
        except Exception:   # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


# ---------------------------------------------------------------- filter (disalin dari artikel)
def rc_report(mint):
    d = get(f"{RC}/{mint}/report")
    if not d:
        return None
    token = d.get("token") or {}
    known = d.get("knownAccounts") or {}

    def is_pool(h):
        tag = known.get(h.get("owner")) or known.get(h.get("address")) or {}
        return str(tag.get("type", "")).upper() in ("AMM", "LOCKER")

    holders = [h for h in (d.get("topHolders") or []) if not is_pool(h)]
    markets = sorted(d.get("markets") or [],
                     key=lambda m: ((m.get("lp") or {}).get("baseUSD") or 0) + ((m.get("lp") or {}).get("quoteUSD") or 0),
                     reverse=True)
    lp = (markets[0].get("lp") or {}) if markets else {}
    supply = token.get("supply") or 0
    risks = d.get("risks") or []
    return {
        "rugged": bool(d.get("rugged")), "risk_score": d.get("score_normalised"),
        "danger": [x.get("name") for x in risks if x.get("level") == "danger"],
        "mint_authority": token.get("mintAuthority", d.get("mintAuthority")),
        "freeze_authority": token.get("freezeAuthority", d.get("freezeAuthority")),
        "lp_locked_pct": lp.get("lpLockedPct", d.get("lpLockedPct")),
        "top10_pct": round(sum(h.get("pct") or 0 for h in holders[:10]), 2) if holders else None,
        "dev_pct": round((d.get("creatorBalance") or 0) / supply * 100, 2) if supply else None,
        "insiders": sum(1 for h in holders if h.get("insider")) + (d.get("graphInsidersDetected") or 0),
        "holders": d.get("totalHolders"),
    }


def fact_kill(t):
    if not t or t["risk_score"] is None:
        return "no_report"
    if t["rugged"]:
        return "already_rugged"
    if t["mint_authority"]:
        return "mint_open"
    if t["freeze_authority"]:
        return "freeze_open"
    if t["danger"]:
        return "danger:" + str(t["danger"][0])
    if t["risk_score"] > FACTS["max_risk_score"]:
        return "risk_score"
    if t["lp_locked_pct"] is None or t["lp_locked_pct"] < FACTS["min_lp_locked_pct"]:
        return "lp_unlocked"
    if t["top10_pct"] is None or t["top10_pct"] > FACTS["max_top10_pct"]:
        return "top10_heavy"
    if t["dev_pct"] is None or t["dev_pct"] > FACTS["max_dev_pct"]:
        return "dev_holds"
    if t["insiders"] > FACTS["max_insiders"]:
        return "insiders"
    return None


def pool_from_pairs(mint, pairs, now):
    pairs = [p for p in pairs or [] if (p.get("baseToken") or {}).get("address") == mint]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    h1 = (p.get("txns") or {}).get("h1") or {}
    born = p.get("pairCreatedAt")
    return {"symbol": (p.get("baseToken") or {}).get("symbol"), "price": float(p.get("priceUsd") or 0),
            "liq_usd": (p.get("liquidity") or {}).get("usd") or 0,
            "age_min": round((now * 1000 - born) / 60000) if born else None,
            "buys_1h": h1.get("buys", 0), "sells_1h": h1.get("sells", 0), "dex": p.get("dexId")}


def market_kill(m):
    if not m:
        return "no_pool"
    if m["price"] <= 0:
        return "no_price"
    if m["liq_usd"] < FACTS["min_liquidity_usd"]:
        return "thin_pool"
    if TICKET / m["liq_usd"] > FACTS["max_ticket_share"]:
        return "ticket_too_big"
    if m["age_min"] is None or m["age_min"] < FACTS["min_age_min"]:
        return "too_fresh"
    if m["age_min"] > FACTS["max_age_hours"] * 60:
        return "too_old"
    if m["buys_1h"] >= 20 and m["sells_1h"] == 0:
        return "nobody_can_sell"
    return None


# ---------------------------------------------------------------- perekam
def run(data, duration):
    d = os.path.join(data, "rugdesk")
    os.makedirs(d, exist_ok=True)
    leads_fp = os.path.join(d, "leads.jsonl")
    leads = {}
    if os.path.exists(leads_fp):
        for line in open(leads_fp):
            try:
                x = json.loads(line)
                leads[x["mint"]] = x
            except ValueError:
                pass
    t_end = time.time() + duration
    next_scan = next_px = 0.0
    n_new = n_err = 0
    print(f"rugdesk mulai, {len(leads)} token sudah tercatat sebelumnya", flush=True)
    while time.time() < t_end:
        now = time.time()
        if now >= next_scan:
            next_scan = now + 120
            try:
                prof = get(PROFILES) or []
            except Exception as e:   # noqa: BLE001
                print("profil gagal:", e, flush=True)
                prof = []
            for p in prof:
                mint = p.get("tokenAddress")
                if p.get("chainId") != "solana" or not mint or mint in leads:
                    continue
                rec = {"mint": mint, "t": round(time.time(), 1)}
                try:
                    rc = rc_report(mint)
                    rec["rc"] = rc
                    rec["fact"] = fact_kill(rc)
                except Exception as e:   # noqa: BLE001
                    rec["rc"], rec["fact"] = None, f"rc_error:{type(e).__name__}"
                    n_err += 1
                try:
                    pr = get(f"{DS}/{mint}")
                    m = pool_from_pairs(mint, pr if isinstance(pr, list) else (pr or {}).get("pairs"), time.time())
                    rec["pool"] = m
                    rec["market"] = market_kill(m)
                except Exception as e:   # noqa: BLE001
                    rec["pool"], rec["market"] = None, f"ds_error:{type(e).__name__}"
                rec["verdict"] = rec["fact"] or rec["market"] or "PASS"
                leads[mint] = rec
                with open(leads_fp, "a") as f:
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                n_new += 1
                if rec["verdict"] == "PASS":
                    print(f"PASS {m['symbol']} {mint} liq ${m['liq_usd']:,.0f} umur {m['age_min']} mnt", flush=True)
                time.sleep(1.0)
        if now >= next_px:
            next_px = now + 60
            live = [m for m, x in leads.items() if now - x["t"] < TRACK_H * 3600]
            rows = []
            for i in range(0, len(live), 30):
                chunk = live[i:i + 30]
                try:
                    pr = get(f"{DS}/{','.join(chunk)}") or []
                except Exception:   # noqa: BLE001
                    continue
                pr = pr if isinstance(pr, list) else pr.get("pairs") or []
                for mint in chunk:
                    m = pool_from_pairs(mint, pr, now)
                    if m:
                        rows.append([round(now), mint, m["price"], round(m["liq_usd"])])
                    else:
                        rows.append([round(now), mint, 0.0, 0])
            if rows:
                with open(os.path.join(d, time.strftime("px-%Y%m%d.jsonl", time.gmtime(now))), "a") as f:
                    for r in rows:
                        f.write(json.dumps(r, separators=(",", ":")) + "\n")
        time.sleep(5)
    print(f"rugdesk selesai: {n_new} token baru, {n_err} gagal rugcheck", flush=True)


# ---------------------------------------------------------------- laporan
def load_all(data):
    d = os.path.join(data, "rugdesk")
    leads = {}
    for line in open(os.path.join(d, "leads.jsonl")) if os.path.exists(os.path.join(d, "leads.jsonl")) else []:
        try:
            x = json.loads(line)
            leads[x["mint"]] = x
        except ValueError:
            pass
    px = {}
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if fn.startswith("px-"):
            for line in open(os.path.join(d, fn)):
                try:
                    t, mint, p, liq = json.loads(line)
                except ValueError:
                    continue
                px.setdefault(mint, []).append((t, p, liq))
    for v in px.values():
        v.sort()
    return leads, px


def trade(series, t_in, step=600, allow_open=False):
    """Aturan jual artikel, dicek tiap `step` detik. Return (hasil x, waktu keluar) atau None."""
    pts = [x for x in series if x[0] >= t_in and x[1] > 0]
    if not pts:
        return None
    t0, p0, liq0 = pts[0]
    entry = p0 * (1 + COST)
    left, got, peak, steps, last_check = 1.0, 0.0, p0, 0, t0
    t_out = t0
    for t, p, liq in pts[1:]:
        if t - last_check < step:
            continue
        last_check = t
        t_out = t
        if p <= 0 or liq <= 0:
            return got - (1 + steps) * PRIO_USD / TICKET, t   # pool hilang, sisa token dianggap nol
        peak = max(peak, p)
        pct = (p / p0 - 1) * 100
        sell = lambda frac: frac * p * (1 - COST) / entry
        if liq < liq0 * (1 - EXIT["liq_drop_pct"] / 100) or pct <= EXIT["stop_pct"]:
            got += sell(left)
            left = 0
            break
        if steps < len(EXIT["ladder"]) and pct >= EXIT["ladder"][steps][0]:
            frac = EXIT["ladder"][steps][1]
            got += sell(frac)
            left -= frac
            steps += 1
            continue
        if steps > 0 and p <= peak * (1 - EXIT["trail_pct"] / 100):
            got += sell(left)
            left = 0
            break
        if (t - t0) / 3600 >= EXIT["time_stop_hours"] and pct < EXIT["time_stop_min_pct"]:
            got += sell(left)
            left = 0
            break
    if left > 0:
        if pts[-1][0] - t0 < 5.5 * 3600 and not allow_open:
            return None            # rekaman belum cukup lama, belum bisa dinilai
        got += left * pts[-1][1] * (1 - COST) / entry
    n_tx = 1 + steps + (1 if left > 0 or steps == 0 else 0)
    return got - n_tx * PRIO_USD / TICKET, t_out


def desk_sim(trades):
    bal, open_, per_day, day_pnl, n, w = START, [], {}, {}, 0, 0
    for t_in, x, t_out in sorted(trades):
        open_ = [o for o in open_ if o > t_in]
        day = time.strftime("%Y%m%d", time.gmtime(t_in))
        if len(open_) >= MAX_OPEN or per_day.get(day, 0) >= MAX_PER_DAY or day_pnl.get(day, 0) <= -DAY_HALT:
            continue
        pnl = TICKET * (x - 1)
        bal += pnl
        open_.append(t_out)
        per_day[day] = per_day.get(day, 0) + 1
        day_pnl[day] = day_pnl.get(day, 0) + pnl
        n, w = n + 1, w + (x > 1)
    return bal, n, w


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    c = (p + z * z / (2 * n)) / (1 + z * z / n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return c - h, c + h


def report(data):
    leads, px = load_all(data)
    if not leads:
        print("Belum ada data.")
        return
    ts = sorted(x["t"] for x in leads.values())
    print(f"== RUG DESK @0xboan, uji maju: {len(leads)} token berprofil DexScreener, "
          f"{time.strftime('%d/%m %H:%M', time.gmtime(ts[0]))} - {time.strftime('%d/%m %H:%M', time.gmtime(ts[-1]))} UTC")
    reasons = {}
    for x in leads.values():
        k = x["verdict"].split(":")[0] if not x["verdict"].startswith("danger") else "danger"
        reasons[k] = reasons.get(k, 0) + 1
    print("   alasan mati: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda z: -z[1])))

    def group(sel, step=600, allow_open=False):
        tr = []
        for mint, x in leads.items():
            if sel(x) and mint in px:
                r = trade(px[mint], x["t"] + 60, step, allow_open)
                if r:
                    tr.append((x["t"] + 60, r[0], r[1]))
        return tr

    for name, sel in (("LOLOS FILTER (yang dibeli desk)", lambda x: x["verdict"] == "PASS"),
                      ("semua token berprofil, tanpa filter", lambda x: True),
                      ("yang dibunuh filter", lambda x: x["verdict"] != "PASS"),
                      ("lolos rugcheck, hanya mati karena umur < 30 mnt", lambda x: not x["fact"] and x["market"] == "too_fresh")):
        tr = group(sel)
        v = [t[1] for t in tr]
        n = len(v)
        if n < 2:
            print(f"\n   {name}: {n} trade yang sudah bisa dinilai")
            continue
        m = sum(v) / n
        sd = math.sqrt(sum((a - m) ** 2 for a in v) / (n - 1))
        win = sum(a > 1 for a in v)
        print(f"\n   {name}: n={n}, menang {win / n:.0%}, rata {m:.3f}x (CI bawah {m - 1.96 * sd / math.sqrt(n):.3f})"
              + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))
        if name.startswith("LOLOS"):
            bal, k, w = desk_sim(tr)
            lo, hi = wilson(w, k)
            print(f"   SIMULASI $200 (desk artikel: $25, maks 4 posisi, 6/hari, stop rugi $50/hari): {k} trade, "
                  f"menang {w}{f' ({w / k:.0%}, CI {lo:.0%}-{hi:.0%})' if k else ''}, akhir ${bal:.2f} ({bal - START:+.2f})")
    for name, sel in (("SEMENTARA lolos filter (posisi yang belum 6 jam dinilai di harga terakhir)", lambda x: x["verdict"] == "PASS"),
                      ("SEMENTARA semua token tanpa filter", lambda x: True)):
        v = [t[1] for t in group(sel, allow_open=True)]
        if v:
            print(f"\n   {name}: n={len(v)}, menang {sum(a > 1 for a in v) / len(v):.0%}, rata {sum(v) / len(v):.3f}x")
    print("\n   Langkah Grok (baca X) tidak ditiru: butuh kunci xAI berbayar. Jual dicek tiap 10 menit seperti artikel,"
          f" biaya {COST:.1%} per sisi + ${PRIO_USD} per transaksi. Trade yang rekamannya belum 6 jam belum dihitung.")
    print("   Data mulai 25 Okt 2026 (uji maju), jadi Jan 2026 - sekarang tidak bisa disimulasikan.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--duration", type=int, default=21000)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.data, a.duration)
    else:
        report(a.data)


if __name__ == "__main__":
    main()

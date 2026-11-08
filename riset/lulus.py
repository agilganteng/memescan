"""Perekam maju (paper): koin pump.fun yang LULUS ke PumpSwap, harga sampai 72 jam (8 Nov 2026).

Kenapa: recorder memescan berhenti saat koin lulus (kurva cuma bisa ~15x dari lahir). Run 10x-1000x yang
dilihat user terjadi SETELAH lulus, jadi tidak ada di data kita. Data gratis lama (GeckoTerminal candle)
bias dan punya lonjakan palsu. Jadi direkam maju, tanpa memilih:
  - tiap ~90 dtk baca pool baru Solana di GeckoTerminal (new_pools, 3 halaman), ambil pool dex 'pumpswap'
    yang token dasarnya berakhiran 'pump' (lulusan pump.fun).
  - saat terdeteksi: latar belakang SEKALI (DexScreener pair, rugcheck, profil X) seperti telecall.
  - harga DexScreener (pair likuiditas terbesar): tiap 60 dtk sampai 6 jam, lalu tiap 5 menit sampai 72 jam.
    Kolom: t, mint, harga usd, likuiditas usd, mcap usd, volume m5, beli m5, jual m5.
Paper saja. Tidak ada wallet, kunci, atau login.

Pakai: python3 riset/lulus.py run --data data --duration 20400
       python3 riset/lulus.py status --data data
"""
import argparse
import calendar
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telecall as tc  # noqa: E402

GT = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"
TRACK_H = 72
FINE_H = 6
POLL_S = 90


def gt_new(since):
    """Pool baru terbaru dulu; ambil halaman sampai pool tertua lebih lama dari 'since' (maks 10 halaman)."""
    out = []
    for page in range(1, 11):
        try:
            d = tc.http(f"{GT}?page={page}&include=base_token", {**tc.UA_JSON, "Accept": "application/json"})
        except Exception as e:   # noqa: BLE001
            print(f"GT gagal hal {page}: {type(e).__name__}", flush=True)
            break
        for p in (d or {}).get("data") or []:
            a = p.get("attributes") or {}
            rel = p.get("relationships") or {}
            dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
            base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
            mint = base.split("_", 1)[1] if "_" in base else base
            out.append({"pool": a.get("address"), "dex": dex, "mint": mint, "created": a.get("pool_created_at"),
                        "name": a.get("name"), "fdv": a.get("fdv_usd"), "liq": a.get("reserve_in_usd")})
        time.sleep(2.5)
        oldest = min([iso_ts(x["created"]) or 0 for x in out[-20:]] + [time.time()])
        if not (d or {}).get("data") or oldest < since:
            break
    return out


def iso_ts(s):
    try:
        return calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except (AttributeError, ValueError):
        return None


def run(data, duration):
    d = os.path.join(data, "lulus")
    os.makedirs(d, exist_ok=True)
    tok_fp = os.path.join(d, "tokens.jsonl")
    tokens = {}
    for line in open(tok_fp) if os.path.exists(tok_fp) else []:
        try:
            x = json.loads(line)
            tokens[x["mint"]] = [x["t_seen"], 0.0]
        except (ValueError, KeyError):
            continue
    seen_dex = {}
    t_end = time.time() + duration
    next_scan = next_px = 0.0
    last_scan, pages = time.time() - 900, []
    n_new = n_px = 0
    print(f"lulus mulai: {len(tokens)} token dari run sebelumnya", flush=True)
    while time.time() < t_end:
        now = time.time()
        if now >= next_scan:
            next_scan = now + POLL_S
            pools = gt_new(last_scan - 120)
            last_scan = now
            pages.append(len(pools) // 20)
            for p in pools:
                seen_dex[p["dex"]] = seen_dex.get(p["dex"], 0) + 1
                if p["dex"] != "pumpswap" or not p["mint"].endswith("pump") or p["mint"] in tokens:
                    continue
                rec = tc.background(p["mint"])
                rec.update(t_seen=round(time.time(), 1), pool=p["pool"], t_pool=iso_ts(p["created"]),
                           gt_fdv=p["fdv"], gt_liq=p["liq"], name=p["name"])
                tokens[p["mint"]] = [rec["t_seen"], 0.0]
                with open(tok_fp, "a") as f:
                    f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                n_new += 1
                ds = rec.get("ds") or {}
                lag = rec["t_seen"] - rec["t_pool"] if rec.get("t_pool") else None
                print(f"LULUS {ds.get('symbol')} {p['mint']} mcap ${ds.get('mcap') or 0:,.0f} "
                      f"liq ${ds.get('liq') or 0:,.0f} telat {lag and round(lag)} dtk", flush=True)
                time.sleep(0.5)
        if now >= next_px:
            next_px = now + 60
            due = []
            for m, (t0, last) in tokens.items():
                age = now - t0
                if age >= TRACK_H * 3600:
                    continue
                gap = 55 if age < FINE_H * 3600 else 295
                if now - last >= gap:
                    due.append(m)
            rows = []
            for i in range(0, len(due), 30):
                chunk = due[i:i + 30]
                try:
                    pr = tc.http(f"{tc.DS}/{','.join(chunk)}", tc.UA_JSON) or []
                except Exception:   # noqa: BLE001
                    continue
                pr = pr if isinstance(pr, list) else pr.get("pairs") or []
                for m in chunk:
                    p = tc.best_pair(m, pr)
                    tokens[m][1] = now
                    if p:
                        v5 = (p.get("volume") or {}).get("m5") or 0
                        t5 = (p.get("txns") or {}).get("m5") or {}
                        rows.append([round(now), m, float(p.get("priceUsd") or 0),
                                     round((p.get("liquidity") or {}).get("usd") or 0),
                                     round(p.get("marketCap") or p.get("fdv") or 0), round(v5),
                                     t5.get("buys", 0), t5.get("sells", 0)])
                    else:
                        rows.append([round(now), m, 0.0, 0, 0, 0, 0, 0])
                time.sleep(0.3)
            if rows:
                with gzip.open(os.path.join(d, time.strftime("px-%Y%m%d.jsonl.gz", time.gmtime(now))), "at") as f:
                    for r in rows:
                        f.write(json.dumps(r, separators=(",", ":")) + "\n")
                n_px += len(rows)
        time.sleep(3)
    print(f"lulus selesai: {n_new} token baru, {n_px} baris harga, total {len(tokens)} token. "
          f"halaman GT per scan rata {sum(pages) / max(1, len(pages)):.1f} (10 = mungkin ada yang terlewat), "
          f"dex terlihat: {dict(sorted(seen_dex.items(), key=lambda x: -x[1])[:8])}", flush=True)


def status(data):
    d = os.path.join(data, "lulus")
    if not os.path.isdir(d):
        print("belum ada data")
        return
    toks = [json.loads(x) for x in open(os.path.join(d, "tokens.jsonl"))] if os.path.exists(
        os.path.join(d, "tokens.jsonl")) else []
    n_rows = 0
    for fn in sorted(os.listdir(d)):
        if fn.startswith("px-"):
            with gzip.open(os.path.join(d, fn), "rt") as f:
                n_rows += sum(1 for _ in f)
    lags = sorted(t["t_seen"] - t["t_pool"] for t in toks if t.get("t_pool"))
    print(f"{len(toks)} token lulus, {n_rows:,} baris harga. "
          f"telat deteksi median {lags[len(lags) // 2]:.0f} dtk" if lags else f"{len(toks)} token")
    if toks:
        print(f"pertama {time.strftime('%d/%m %H:%M', time.gmtime(toks[0]['t_seen']))} UTC, "
              f"terakhir {time.strftime('%d/%m %H:%M', time.gmtime(toks[-1]['t_seen']))} UTC")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--duration", type=int, default=20400)
    a = ap.parse_args()
    run(a.data, a.duration) if a.cmd == "run" else status(a.data)


if __name__ == "__main__":
    main()

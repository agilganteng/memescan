"""Ambil candle 15 menit (10,4 hari setelah lulus) dari GeckoTerminal untuk satu bagian daftar koin (7 Nov 2026).

Pakai: python3 riset/swing_fetch.py --list data/swing/list.json --shard 0 --of 6 --out data/swing/shard0.json
"""
import argparse
import json
import os
import time
import urllib.request

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
UA = {"User-Agent": "Mozilla/5.0 memescan-riset", "Accept": "application/json"}
GAP = 6.5          # detik antar permintaan (batas gratis GeckoTerminal)


def get(url, tries=6):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(20 * (k + 1))
                continue
            if e.code == 404:
                return None
            print("   HTTP", e.code, url[:90], flush=True)
            return None
        except Exception as e:  # noqa: BLE001
            time.sleep(10 * (k + 1))
            print("   err", str(e)[:80], flush=True)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="data/swing/list.json")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--of", type=int, default=1)
    ap.add_argument("--out", default="data/swing/shard0.json")
    ap.add_argument("--max-minutes", type=float, default=330)
    a = ap.parse_args()
    t_start = time.time()
    items = [x for i, x in enumerate(json.load(open(a.list))) if i % a.of == a.shard]
    print(f"shard {a.shard}/{a.of}: {len(items)} koin", flush=True)
    pools = {}
    for i in range(0, len(items), 30):
        batch = [x["mint"] for x in items[i:i + 30]]
        d = get(f"{GT}/tokens/multi/{','.join(batch)}")
        time.sleep(GAP)
        for t in (d or {}).get("data", []):
            tp = t.get("relationships", {}).get("top_pools", {}).get("data", [])
            if tp:
                pools[t["attributes"]["address"]] = tp[0]["id"].split("_", 1)[1]
    print(f"  pool ditemukan {len(pools)}/{len(items)} ({time.time() - t_start:.0f} dtk)", flush=True)
    out = []
    for k, x in enumerate(items):
        if time.time() - t_start > a.max_minutes * 60:
            print("  batas waktu, berhenti", flush=True)
            break
        pool = pools.get(x["mint"])
        if not pool:
            out.append({**x, "pool": None, "c": []})
            continue
        bt = int(min(time.time(), x["t"] + 1000 * 900))
        d = get(f"{GT}/pools/{pool}/ohlcv/minute?aggregate=15&limit=1000&before_timestamp={bt}&currency=usd&token={x['mint']}")
        time.sleep(GAP)
        c = (d or {}).get("data", {}).get("attributes", {}).get("ohlcv_list", []) if d else []
        out.append({**x, "pool": pool, "c": sorted(c)})
        if k % 50 == 0:
            print(f"  {k}/{len(items)} ({time.time() - t_start:.0f} dtk)", flush=True)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f)
    print(f"Selesai shard {a.shard}: {sum(1 for o in out if o['c'])} koin dengan candle")


if __name__ == "__main__":
    main()

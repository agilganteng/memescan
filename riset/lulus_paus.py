#!/usr/bin/env python3
"""Perekam maju (paper): pembelian BESAR di koin pump.fun yang sudah lulus (PumpSwap), beserta wallet pembelinya.

Permintaan user 20 Nov 2026: "copy whale (bukan dev) yang beli ratusan juta". Pembelian sebesar itu tidak ada di
kurva pump.fun (sudah diuji, whale_besar.py), adanya di koin yang sudah lulus. Perekam riset-lulus hanya
menyimpan harga, jadi perekam ini mengisi lubang itu.

Cara kerja (hanya baca API publik GeckoTerminal, tanpa wallet/kunci/login):
  - tiap ~10 menit: perbarui daftar pool = pool PumpSwap ber-volume 24 jam terbesar (5 halaman) + pool trending
    Solana (3 halaman) yang dex-nya pumpswap dan mint berakhiran 'pump'. Maks 90 pool.
  - berputar terus: untuk tiap pool baca trades dengan volume >= MIN_USD (endpoint trades = 24 jam terakhir,
    maks 300 baris), simpan yang belum pernah terlihat: paus-YYYYMMDD.jsonl.gz
    [t_blok, pool, mint, jenis(1 beli/0 jual), usd, harga_token_usd, wallet, tx]
  - tiap putaran simpan harga + likuiditas tiap pool (pools/multi): ppx-YYYYMMDD.jsonl.gz [t, pool, harga, liq, fdv]
Harga keluar untuk uji nanti diambil ulang per menit dari OHLCV GeckoTerminal (bukan dari polling kasar ini).
"""
import argparse
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telecall as tc  # noqa: E402

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
MIN_USD = 1000
MAX_POOLS = 90
GAP = 2.3          # jeda antar panggilan GT (batas gratis ~30/menit)
HDR = {**tc.UA_JSON, "Accept": "application/json"}


def get(url):
    try:
        r = tc.http(url, HDR)
    except Exception as e:   # noqa: BLE001
        print(f"GT gagal: {type(e).__name__} {url[len(GT):][:60]}", flush=True)
        r = None
    time.sleep(GAP)
    return r


def iso_ts(s):
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except (TypeError, ValueError):
        return None


def universe():
    out = {}
    urls = [f"{GT}/dexes/pumpswap/pools?sort=h24_volume_usd_desc&page={p}&include=base_token" for p in range(1, 6)]
    urls += [f"{GT}/trending_pools?page={p}&include=base_token,dex" for p in range(1, 4)]
    for u in urls:
        d = get(u)
        for p in (d or {}).get("data") or []:
            a = p.get("attributes") or {}
            rel = p.get("relationships") or {}
            dex = ((rel.get("dex") or {}).get("data") or {}).get("id") or ""
            base = ((rel.get("base_token") or {}).get("data") or {}).get("id") or ""
            mint = base.split("_", 1)[1] if "_" in base else base
            if dex != "pumpswap" or not mint.endswith("pump") or not a.get("address"):
                continue
            out.setdefault(a["address"], {"mint": mint, "name": a.get("name"), "created": iso_ts(a.get("pool_created_at")),
                                          "liq": a.get("reserve_in_usd"), "fdv": a.get("fdv_usd")})
            if len(out) >= MAX_POOLS:
                return out
    return out


def run(data, duration):
    d = os.path.join(data, "paus")
    os.makedirs(d, exist_ok=True)
    seen_fp = os.path.join(d, "seen.json")
    try:
        seen = {k: v for k, v in json.load(open(seen_fp)).items() if v > time.time() - 2 * 86400}
    except (OSError, ValueError):
        seen = {}
    pools_fp = os.path.join(d, "pools.jsonl")
    known = set()
    for line in open(pools_fp) if os.path.exists(pools_fp) else []:
        try:
            known.add(json.loads(line)["pool"])
        except (ValueError, KeyError):
            pass
    t_end = time.time() + duration
    uni, next_uni = {}, 0.0
    n_tr = n_px = n_cyc = 0
    sample = True
    print(f"paus mulai: {len(seen)} transaksi sudah terlihat, {len(known)} pool dikenal", flush=True)
    while time.time() < t_end:
        now = time.time()
        if now >= next_uni or not uni:
            u = universe()
            if u:
                uni = u
            next_uni = now + 600
            with open(pools_fp, "a") as f:
                for a, v in uni.items():
                    if a not in known:
                        known.add(a)
                        f.write(json.dumps({"pool": a, "t_seen": round(now), **v}, separators=(",", ":")) + "\n")
            print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] daftar pool {len(uni)} · transaksi besar {n_tr} · "
                  f"baris harga {n_px} · putaran {n_cyc}", flush=True)
            if not uni:
                time.sleep(30)
                continue
        addrs = list(uni)
        rows = []
        for i in range(0, len(addrs), 30):
            dd = get(f"{GT}/pools/multi/{','.join(addrs[i:i + 30])}")
            for p in (dd or {}).get("data") or []:
                a = p.get("attributes") or {}
                try:
                    rows.append([round(time.time()), a.get("address"), float(a.get("base_token_price_usd") or 0),
                                 float(a.get("reserve_in_usd") or 0), float(a.get("fdv_usd") or 0)])
                except (TypeError, ValueError):
                    pass
        trs = []
        for a in addrs:
            if time.time() >= t_end:
                break
            dd = get(f"{GT}/pools/{a}/trades?trade_volume_in_usd_greater_than={MIN_USD}")
            for t in (dd or {}).get("data") or []:
                x = t.get("attributes") or {}
                if sample:
                    print("contoh transaksi:", json.dumps(x)[:700], flush=True)
                    sample = False
                tx = x.get("tx_hash") or t.get("id")
                key = f"{tx}:{x.get('kind')}:{x.get('volume_in_usd')}"
                if not tx or key in seen:
                    continue
                ts = iso_ts(x.get("block_timestamp")) or time.time()
                seen[key] = ts
                buy = 1 if x.get("kind") == "buy" else 0
                try:
                    m_from = x.get("from_token_address") == uni[a]["mint"]
                    px = float((x.get("price_from_in_usd") if m_from else x.get("price_to_in_usd")) or 0)
                    usd = float(x.get("volume_in_usd") or 0)
                except (TypeError, ValueError):
                    continue
                trs.append([round(ts), a, uni[a]["mint"], buy, round(usd, 1), px, x.get("tx_from_address"), tx])
        day = time.strftime("%Y%m%d", time.gmtime(now))
        try:
            if rows:
                with gzip.open(os.path.join(d, f"ppx-{day}.jsonl.gz"), "at") as f:
                    for r in rows:
                        f.write(json.dumps(r, separators=(",", ":")) + "\n")
                n_px += len(rows)
            if trs:
                with gzip.open(os.path.join(d, f"paus-{day}.jsonl.gz"), "at") as f:
                    for r in trs:
                        f.write(json.dumps(r, separators=(",", ":")) + "\n")
                n_tr += len(trs)
            json.dump(seen, open(seen_fp, "w"))
        except OSError as e:
            print("gagal simpan:", e, flush=True)
        n_cyc += 1
    print(f"paus selesai: {n_tr} transaksi besar baru, {n_px} baris harga, {n_cyc} putaran", flush=True)


def status(data):
    d = os.path.join(data, "paus")
    if not os.path.isdir(d):
        print("belum ada data paus")
        return
    n = nb = 0
    big = {5000: 0, 10000: 0, 20000: 0, 50000: 0}
    wal, pools, t0, t1 = {}, set(), None, None
    for fn in sorted(os.listdir(d)):
        if not fn.startswith("paus-"):
            continue
        for line in gzip.open(os.path.join(d, fn), "rt"):
            try:
                t, pool, mint, buy, usd, px, w, tx = json.loads(line)
            except ValueError:
                continue
            n += 1
            t0, t1 = min(t0 or t, t), max(t1 or t, t)
            pools.add(pool)
            if buy:
                nb += 1
                wal[w] = wal.get(w, 0) + 1
                for k in big:
                    big[k] += usd >= k
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t)) if t else "-"  # noqa: E731
    print(f"paus: {n} transaksi >= ${MIN_USD} ({nb} beli) di {len(pools)} pool, {fmt(t0)} s/d {fmt(t1)}")
    print("beli besar: " + ", ".join(f">=${k:,}: {v}" for k, v in big.items()))
    print(f"wallet pembeli: {len(wal)}; dengan >=3 beli besar: {sum(v >= 3 for v in wal.values())}; "
          f">=10: {sum(v >= 10 for v in wal.values())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "status"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--duration", type=int, default=20400)
    a = ap.parse_args()
    run(a.data, a.duration) if a.cmd == "run" else status(a.data)


if __name__ == "__main__":
    main()

"""[Cadangan, 8 Nov] Sama seperti swing_list.py tapi dengan batas waktu: transaksi diproses dalam urutan acak
(supaya kalau dipotong waktu, sebaran hari tetap merata) dan hasil ditulis walau belum semua selesai.

Daftar koin pump.fun yang LULUS (migrasi ke PumpSwap) sejak tanggal tertentu, dari RPC Solana publik (7 Nov 2026).

Sumber: semua transaksi wallet migrasi pump.fun 39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg (instruksi Migrate/MigrateV2).
Sampel merata per hari (supaya tidak berat sebelah ke hari ramai), lalu ambil mint dari tiap transaksi.
Tidak ada seleksi berdasarkan harga sesudahnya -> tidak ada bias "yang selamat".

Pakai: python3 riset/swing_list.py --since 2026-06-10 --per-day 22 --out data/swing/list.json
"""
import argparse
import calendar
import json
import os
import random
import time
import urllib.request

RPC = "https://api.mainnet-beta.solana.com"
MIG = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"
WSOL = "So11111111111111111111111111111111111111112"


def rpc(method, params, tries=8):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    for k in range(tries):
        try:
            req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json",
                                                                   "User-Agent": "memescan-riset"})
            with urllib.request.urlopen(req, timeout=40) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(str(d["error"])[:200])
            return d["result"]
        except Exception as e:  # noqa: BLE001
            time.sleep(min(60, 2 ** k))
            last = e
    raise RuntimeError(f"RPC gagal {method}: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-06-10")
    ap.add_argument("--per-day", type=int, default=22)
    ap.add_argument("--out", default="data/swing/list.json")
    ap.add_argument("--max-minutes", type=float, default=150)
    a = ap.parse_args()
    t_start = time.time()
    t_since = calendar.timegm(time.strptime(a.since, "%Y-%m-%d"))
    t_end = time.time() - 11 * 86400       # koin harus punya >= 10 hari data sesudah lulus... kecuali yang paling baru
    sigs, before, t0 = [], None, time.time()
    while True:
        p = {"limit": 1000}
        if before:
            p["before"] = before
        r = rpc("getSignaturesForAddress", [MIG, p])
        if not r:
            break
        for s in r:
            if s.get("err") is None and s.get("blockTime"):
                sigs.append((s["blockTime"], s["signature"]))
        before = r[-1]["signature"]
        bt = r[-1].get("blockTime") or 0
        if len(sigs) % 50000 < 1000:
            print(f"  {len(sigs):,} sig, sampai {time.strftime('%Y-%m-%d %H:%M', time.gmtime(bt))} ({time.time() - t0:.0f} dtk)",
                  flush=True)
        if bt and bt < t_since:
            break
        if time.time() - t_start > a.max_minutes * 60 * 0.6:
            print("  batas waktu paging tanda tangan: mulai dari tanggal yang sudah tercapai", flush=True)
            break
        time.sleep(0.25)
    sigs = [s for s in sigs if s[0] >= t_since]
    print(f"{len(sigs):,} transaksi migrasi sukses sejak {a.since}", flush=True)
    byday = {}
    for bt, sg in sigs:
        byday.setdefault(bt // 86400, []).append((bt, sg))
    rng = random.Random(42)
    pick = []
    for d in sorted(byday):
        v = byday[d]
        pick += rng.sample(v, min(a.per_day, len(v)))
    print(f"sampel {len(pick):,} transaksi dari {len(byday)} hari (rata {len(sigs) / max(1, len(byday)):.0f} tx/hari)",
          flush=True)
    seen, out = set(), []
    rng.shuffle(pick)
    for i, (bt, sg) in enumerate(pick):
        if time.time() - t_start > a.max_minutes * 60:
            print(f"  batas waktu: berhenti di {i}/{len(pick)} tx", flush=True)
            break
        try:
            tx = rpc("getTransaction", [sg, {"maxSupportedTransactionVersion": 0, "encoding": "json"}])
        except RuntimeError as e:
            print("  lewati", e)
            continue
        if not tx:
            continue
        logs = " ".join(tx["meta"].get("logMessages") or [])
        if "Migrate" not in logs:
            continue
        mints = {b["mint"] for b in tx["meta"].get("postTokenBalances") or []} - {WSOL}
        for m in mints:
            if m not in seen:
                seen.add(m)
                out.append({"mint": m, "t": bt, "recent": bt > t_end})
        if i % 300 == 0:
            print(f"  {i}/{len(pick)} tx -> {len(out)} koin", flush=True)
        time.sleep(0.2)
    out.sort(key=lambda x: x["t"])
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(out, f)
    print(f"Selesai: {len(out):,} koin lulus -> {a.out}")


if __name__ == "__main__":
    main()

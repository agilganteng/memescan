#!/usr/bin/env python3
"""telecall_retro: periksa kenapa laporan telecall hanya punya 101 trade, lalu isi harga SUSULAN.

Perekam harga telecall (DexScreener tiap 60 dtk untuk semua token 24 jam terakhir) diduga kewalahan saat token
jadi puluhan ribu. Skrip ini:
  1. diag  : hitung cakupan harga asli (berapa token punya harga dalam 5 menit setelah call).
  2. retro : ambil sampel ACAK N token (seed tetap), tarik candle 1 menit GeckoTerminal 24 jam sejak call pertama,
             bersihkan lonjakan palsu (close > 3x dari median 5 tetangga dibuang), isi maju ke kisi 60 dtk,
             tulis ke px-retro.jsonl, pindahkan px asli, lalu jalankan laporan pra-registrasi yang sama.
Batas jujur: koin yang pool-nya ditarik tampak "harga terakhir tetap" (optimis); isi stop = close menit itu.
"""
import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telecall as tc

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
_last = [0.0]


def gt(path):
    for a in range(5):
        w = 2.1 - (time.time() - _last[0])
        if w > 0:
            time.sleep(w)
        _last[0] = time.time()
        try:
            return tc.http(f"{GT}/{path}", tc.UA_JSON, tries=1)
        except Exception as e:  # noqa: BLE001
            if "404" in str(e):
                return None
            time.sleep(20 + 20 * a)
    return None


def candles(mint, t0):
    r = gt(f"tokens/{mint}/pools?page=1")
    pools = (r or {}).get("data") or []
    if not pools:
        return None
    best = max(pools, key=lambda p: float((p.get("attributes") or {}).get("reserve_in_usd") or 0))
    addr = (best.get("attributes") or {}).get("address")
    out = {}
    for end, lim in ((t0 + 990 * 60, 1000), (t0 + 1445 * 60, 500)):
        r = gt(f"pools/{addr}/ohlcv/minute?aggregate=1&limit={lim}&before_timestamp={int(end)}&currency=usd")
        for c in (((r or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []:
            out[int(c[0])] = float(c[4])
    return sorted(out.items())


def clean(cs):
    keep = []
    for i, (t, p) in enumerate(cs):
        nb = sorted(x[1] for x in cs[max(0, i - 2):i + 3])
        med = nb[len(nb) // 2]
        if p > 0 and med > 0 and (p > 3 * med or p < med / 3):
            continue
        keep.append((t, p))
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--n", type=int, default=800)
    a = ap.parse_args()
    d = os.path.join(a.data, "telecall")
    toks, calls, px = tc.load_all(a.data)
    first = {}
    for c in sorted(calls, key=lambda c: c["t_seen"]):
        first.setdefault(c["mint"], c["t_seen"])
    # ---- diagnosa
    ok5 = sum(1 for m, t in first.items() if any(t + 30 <= x[0] <= t + 330 and x[1] > 0 for x in px.get(m, [])))
    anyp = sum(1 for m in first if any(x[1] > 0 for x in px.get(m, [])))
    nopair = sum(1 for m in first if not (toks.get(m) or {}).get("ds"))
    print(f"[diag] token di-call {len(first)}; tanpa pair DexScreener saat call {nopair}; punya harga >0 kapan pun {anyp}; "
          f"punya harga dalam 5 menit setelah call {ok5}", flush=True)
    for fn in sorted(os.listdir(d)):
        if fn.startswith("px-"):
            n = z = 0
            ms = set()
            for line in open(os.path.join(d, fn)):
                try:
                    t, m, p, _ = json.loads(line)
                except ValueError:
                    continue
                n += 1
                z += p <= 0
                ms.add(m)
            print(f"[diag] {fn}: {n} baris, {len(ms)} token, harga 0 = {z}", flush=True)
    by_day = {}
    for m, t in first.items():
        k = time.strftime("%m-%d", time.gmtime(t))
        by_day[k] = by_day.get(k, 0) + 1
    print(f"[diag] token baru per hari: {sorted(by_day.items())}", flush=True)
    by_ch = {}
    for c in calls:
        by_ch[c["ch"]] = by_ch.get(c["ch"], 0) + 1
    print(f"[diag] call per channel (15 teratas): {sorted(by_ch.items(), key=lambda x: -x[1])[:15]}", flush=True)
    # ---- harga susulan
    now = time.time()
    pool = sorted(m for m, t in first.items() if now - t > 25 * 3600)
    random.Random(1).shuffle(pool)
    pick = pool[:a.n]
    rows, got, nopool, short = [], 0, 0, 0
    T0 = time.time()
    for i, m in enumerate(pick):
        if time.time() - T0 > 5.2 * 3600:
            print(f"[retro] waktu habis di {i}", flush=True)
            break
        t0 = first[m]
        cs = candles(m, t0)
        if cs is None:
            nopool += 1
            continue
        cs = clean(cs)
        before = [c for c in cs if c[0] <= t0 + 30]
        after = [c for c in cs if c[0] > t0 + 30]
        if not before:
            short += 1
            continue
        got += 1
        last, j = before[-1][1], 0
        for t in range(int(t0) + 30, int(t0) + 24 * 3600 + 61, 60):
            while j < len(after) and after[j][0] + 60 <= t:
                last = after[j][1]
                j += 1
            rows.append([t, m, last, 0])
        if i % 50 == 0:
            print(f"  {i}/{len(pick)} token, dapat {got}, tanpa pool {nopool}, tanpa candle sebelum call {short} "
                  f"({time.time() - T0:.0f}s)", flush=True)
    print(f"[retro] sampel {len(pick)}: dapat harga {got}, tanpa pool GT {nopool}, tanpa candle sebelum call {short}",
          flush=True)
    for fn in os.listdir(d):
        if fn.startswith("px-"):
            os.rename(os.path.join(d, fn), os.path.join(d, "asli-" + fn))
    with open(os.path.join(d, "px-retro.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print("\n===== LAPORAN PRA-REGISTRASI DENGAN HARGA SUSULAN (hanya token sampel) =====", flush=True)
    tc.report(a.data)


if __name__ == "__main__":
    main()

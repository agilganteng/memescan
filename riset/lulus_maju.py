#!/usr/bin/env python3
"""lulus_maju: uji MAJU aturan beku 18 Nov 2026 (lihat hasil-2026-11-18.md).

Aturan: masuk 10 menit setelah lulus terdeteksi, hanya koin gt_fdv >= 157.300, tahan 1 jam, biaya 1,5% per sisi.
Data uji: koin yang lulus setelah 16 Nov 2026 00:45 UTC (tidak dipakai saat mencari). Lulus: n >= 30, rata > 1,
rata tanpa koin terbaik > 1. Pembanding: semua koin periode sama, dan aturan yang sama di periode lama (sudah dilihat).
Tidak ada ambang yang diubah.
"""
import argparse
import calendar
import time

import numpy as np

import lulus_cari as lc

CUT = calendar.timegm((2026, 11, 16, 0, 45, 0))
FDV = 157300.0
EX = dict(T=3600)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    toks, px, t_last = lc.load(a.data)
    f = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"data harga terakhir {f(t_last)} UTC; batas uji maju {f(CUT)} UTC")
    rows = []
    for m, x in toks.items():
        v = px.get(m)
        if not v or x["t_seen"] + 600 + 3600 + 300 > t_last:
            continue
        ts_ = [z[0] for z in v]
        i0 = lc.entry_index(v, ts_, x, 600)
        if i0 is None:
            continue
        ps = [z[1] for z in v]
        r = lc.sim(ts_, ps, i0, EX)
        moved = len({round(p, 12) for t, p in zip(ts_[i0:], ps[i0:]) if t - ts_[i0] <= 3600}) > 1
        rows.append((x["t_seen"], lc.num(x.get("gt_fdv")), r, moved, x.get("name"), m))
    rows.sort()
    for lab, sel in (("LAMA (sudah dilihat), FDV besar", lambda r: r[0] < CUT and r[1] >= FDV),
                     ("LAMA, semua koin", lambda r: r[0] < CUT),
                     ("MAJU (baru), semua koin", lambda r: r[0] >= CUT),
                     ("MAJU (baru), FDV besar  <== ATURAN BEKU", lambda r: r[0] >= CUT and r[1] >= FDV)):
        s = [r for r in rows if sel(r)]
        print(f"\n{lab}: {lc.stat([r[2] for r in s])}; harga bergerak dalam 1 jam {np.mean([r[3] for r in s]) if s else 0:.0%}")
        for d in sorted({time.strftime('%m-%d', time.gmtime(r[0])) for r in s}):
            y = [r[2] for r in s if time.strftime('%m-%d', time.gmtime(r[0])) == d]
            print(f"    {d}: n={len(y)} rata {np.mean(y):.3f}x median {np.median(y):.3f}x menang {np.mean(np.array(y) > 1):.0%}")
    s = [r for r in rows if r[0] >= CUT and r[1] >= FDV]
    print("\nTrade uji maju satu per satu (waktu lulus, FDV, hasil, nama):")
    for r in s:
        print(f"  {f(r[0])} fdv ${r[1]:,.0f} {r[2]:.3f}x {'gerak' if r[3] else 'DIAM'} {r[4]}")
    y = np.array([r[2] for r in s])
    ok = len(y) >= 30 and y.mean() > 1 and (y.sum() - y.max()) / (len(y) - 1) > 1
    print(f"\n[putusan] {'LULUS' if ok else 'BELUM/TIDAK LULUS'} (n={len(y)})")


if __name__ == "__main__":
    main()

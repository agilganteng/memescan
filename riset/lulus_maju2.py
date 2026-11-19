#!/usr/bin/env python3
"""lulus_maju2: uji MAJU 3 aturan beku dari lulus_cari2 (dibekukan 18 Nov 2026, run 44297871048).

Hanya koin yang lulus SETELAH 18 Nov 2026 06:45 UTC (data yang belum ada saat aturan dipilih). Tidak ada penyetelan.
Lulus: n >= 30, rata > 1, rata tanpa koin terbaik > 1. Kalau n < 30: belum bisa disimpulkan.
"""
import argparse
import calendar
import time

import numpy as np

import lulus_cari as lc
import lulus_cari2 as c2

CUT2 = calendar.timegm((2026, 11, 18, 6, 45, 0))
BEKU = [
    (2, "M120", "H2", [("ds_beli_h1", "<=", 239), ("ds_rasio_beli", "<=", 0.5359)]),
    (3, "M120", "H5m", [("jam_utc", "<=", 4), ("jual30m", ">=", 13.5)]),
    (3, "TEMBUS2", "TRAIL10 arm1.1 SL10", [("beli5", "<=", 416), ("puncak_dari_awal", "<=", 2.319)]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    f = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    for st in (2, 3):
        lc.HOR, lc.EXITS = c2.SETS[st]
        toks, px, t_last = lc.load(a.data)
        toks = {m: x for m, x in toks.items() if not (lc.num(x.get("gt_fdv")) > 1e6)}
        D = lc.build(toks, px, t_last)
        exn = list(lc.EXITS)
        print(f"\n## set {st}: koin lulus setelah {f(CUT2)} UTC, data terakhir {f(t_last)} UTC", flush=True)
        for s, en, ex, conds in BEKU:
            if s != st:
                continue
            d = D.get(en)
            if d is None:
                print(f"  {en} | {ex}: tidak ada data", flush=True)
                continue
            e = exn.index(ex)
            names = list(d["names"])
            fm = (d["seen"] >= CUT2) & ~np.isnan(d["Y"][:, e])
            mk = fm.copy()
            for nm, op, thr in conds:
                x = d["X"][:, names.index(nm)]
                with np.errstate(invalid="ignore"):
                    mk &= (x <= thr) if op == "<=" else (x >= thr)
            y, ya = d["Y"][mk, e], d["Y"][fm, e]
            ok = len(y) >= 30 and y.mean() > 1 and (y.sum() - y.max()) / (len(y) - 1) > 1
            lab = " & ".join(f"{n}{o}{t}" for n, o, t in conds)
            ver = "LULUS" if ok else ("BELUM CUKUP (n<30)" if len(y) < 30 else "GAGAL")
            print(f"  {en} | {ex} | {lab}\n     aturan: {lc.stat(y)}  => {ver}\n     semua koin periode sama: {lc.stat(ya)}", flush=True)
    print(f"[selesai] {time.time() - lc.T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

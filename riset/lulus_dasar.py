#!/usr/bin/env python3
"""lulus_dasar: hasil beli SEMUA lulusan PumpSwap untuk tiap cara masuk x cara keluar set 3 (tanpa pemilihan apa pun).
Dipakai menjawab "gimana kalau jual di 1,1x / stop di 1,1x". Biaya 1,5% per sisi sudah di dalam sim."""
import argparse

import numpy as np

import lulus_cari as lc
import lulus_cari2 as c2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    lc.HOR, lc.EXITS = c2.SETS[3]
    lc.EXITS = dict(lc.EXITS)
    H = 3600
    lc.EXITS.update({"TP1.1 tanpa SL 1j": dict(tp=1.1, sl=0.99, T=H), "TP1.1 SL5": dict(tp=1.1, sl=0.05, T=H),
                     "TP1.1 SL30": dict(tp=1.1, sl=0.30, T=H), "TP1.05 SL10": dict(tp=1.05, sl=0.10, T=H),
                     "TRAIL5 arm1.1 SL10": dict(arm=1.1, trail=0.05, sl=0.10, T=H)})
    toks, px, t_last = lc.load(a.data)
    toks = {m: x for m, x in toks.items() if not (lc.num(x.get("gt_fdv")) > 1e6)}
    D = lc.build(toks, px, t_last)
    exn = list(lc.EXITS)
    for en, d in D.items():
        o = np.argsort(d["seen"])
        print(f"\n## masuk {en}", flush=True)
        for e, ex in enumerate(exn):
            y = d["Y"][o, e]
            y = y[~np.isnan(y)]
            print(f"  {ex}: {lc.stat(y)} | kena >=1.05x bersih {(y >= 1.05).mean():.0%}, rugi >=10% {(y <= 0.90).mean():.0%}, rugi >=25% {(y <= 0.75).mean():.0%}", flush=True)


if __name__ == "__main__":
    main()

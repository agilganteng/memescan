"""Diagnosa rekonstruksi harga per trade untuk riset/kol.py (sekali jalan)."""
import math, os, sys, bisect
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kol

coins = kol.load(sys.argv[1] if len(sys.argv) > 1 else "data")
std = [c for c in coins if c.kfrom < math.inf and c.kbad == math.inf and c.tbad == math.inf]
bad = [c for c in coins if c.kbad < math.inf or c.tbad < math.inf]
print(f"{len(coins):,} koin; standar {len(std):,}; tidak standar {len(bad):,}")
for nm, cl in (("standar", std), ("tidak standar", bad)):
    if not cl: continue
    m0 = np.array([c.m0 for c in cl])
    print(f"  m0 {nm}: p5 {np.percentile(m0, 5):.2f} p25 {np.percentile(m0, 25):.2f} median {np.median(m0):.2f} "
          f"p75 {np.percentile(m0, 75):.2f}, < 27.5: {np.mean(m0 < 27.5):.0%}")
for scale in (1.0, 0.99, 1e-9):
    errs, errs_first = [], []
    for c in std[::max(1, len(std) // 4000)]:
        ends = [x[1] for x in c.cs]
        for k in range(1, len(c.cs)):
            e0, e1 = c.cs[k - 1][1], c.cs[k][1]
            if e1 > c.cov or c.cs[k][0] != e0:
                continue
            v = math.sqrt(kol.K_CURVE * c.cs[k - 1][4])
            for ag, w, isb, sol in c.w:
                if e0 < ag <= e1:
                    v = v + sol * scale if isb else max(1e-6, v - sol * scale)
            errs.append(abs(v * v / kol.K_CURVE / c.cs[k][4] - 1))
    e = np.array(errs)
    print(f"  cek per candle (skala sol {scale}): {len(e):,} titik, median {np.median(e):.2%}, >10% {np.mean(e > .1):.1%}")
for c in std[:3]:
    print("\nKOIN t0", c.t0, "m0", c.m0, "end", c.end, "cov", c.cov)
    print("  candle:", [(x[0], x[1], round(x[4], 2)) for x in c.cs[:10]])
    print("  w:", [(a, round(s, 3), b) for a, _, b, s in c.w[:25]])

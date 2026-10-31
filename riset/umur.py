"""Berapa lama koin pump.fun hidup: dari lahir ke ATH, lalu dari ATH sampai jebol (31 Okt 2026).

Data : semua koin rekaman memescan (14 Okt - sekarang), hanya kurva standar (harga bisa dipercaya).
       Rekaman per koin maksimal 30 menit setelah lahir dan berhenti lebih awal kalau koin mati/sepi.
Ukur : kelipatan puncak = high tertinggi / harga lahir; umur ATH; dari ATH berapa lama sampai close <= 50%,
       <= 20%, <= 10% dari ATH. Koin yang sudah hampir lulus (likuiditas >= 75 SOL) dihitung terpisah karena
       setelah lulus pindah ke PumpSwap dan tidak terekam lagi.

Pakai: python3 riset/umur.py --data data
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import insider4 as i4  # noqa: E402
import hybrid as hy  # noqa: E402

FI = i4.FI
MCAP0_SOL = 27.96            # market cap kurva standar saat lahir
BUCKETS = ((1.0, 1.5, "< 1,5x"), (1.5, 3.0, "1,5-3x"), (3.0, 10.0, "3-10x"), (10.0, math.inf, ">= 10x"))
DROPS = (0.5, 0.2, 0.1)


def fmt_t(x):
    if not np.isfinite(x):
        return "-"
    return f"{x:.0f} dtk" if x < 120 else f"{x / 60:.1f} mnt"


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else math.nan


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t0 = time.time()
    _, ps, src = hy.sol_prices(time.time() - 20 * 86400, time.time())
    su = float(np.median(ps))
    coins, _, n_all, n_bug = i4.load(a.data, 0.0, every=10 ** 12)
    rows = []
    for c in coins:
        if not (c.kfrom <= 10 and c.kbad == math.inf) or not c.cs:
            continue
        hi = np.array([x[2] for x in c.cs])
        cl = np.array([x[4] for x in c.cs])
        st = np.array([x[0] for x in c.cs])
        en = np.array([x[1] for x in c.cs])
        p0 = c.m0
        if p0 <= 0:
            continue
        k = int(np.argmax(hi))
        ath, t_ath = hi[k], float(st[k])
        mult = ath / p0
        after = cl[k:]
        tafter = en[k:]
        drops = []
        for d in DROPS:
            j = np.nonzero(after <= ath * d)[0]
            drops.append(float(tafter[j[0]]) - t_ath if len(j) else math.inf)
        liq_max = max((float(s[FI["liq_sol"]]) for s in c.snaps.values()), default=0.0)
        rows.append((mult, t_ath, *drops, float(c.end), liq_max >= 75, cl[-1] / ath))
    R = np.array(rows, dtype=float)
    print(f"== {n_all:,} koin terekam, {len(R):,} kurva standar dianalisis (sisanya kurva non-standar/bug). "
          f"Harga SOL {src} median ${su:.0f}; market cap lahir ~{MCAP0_SOL:.0f} SOL = ${MCAP0_SOL * su:,.0f}.")
    print("   Rekaman maks 30 menit per koin. ({:.0f} dtk)\n".format(time.time() - t0))
    mult, tath, d50, d20, d10, end, grad, last = R.T
    grad = grad > 0

    print("### SEMUA KOIN")
    print(f"   puncak tertinggi (kelipatan dari harga lahir): median {np.median(mult):.2f}x, "
          f"p75 {pct(mult, 75):.2f}x, p90 {pct(mult, 90):.2f}x, p99 {pct(mult, 99):.1f}x")
    for lo, hi_, name in BUCKETS:
        m = (mult >= lo) & (mult < hi_)
        print(f"   puncak {name:<7}: {m.mean():6.1%} koin")
    print(f"   hampir lulus (likuiditas >= 75 SOL): {grad.mean():.2%} koin")
    print(f"   rekaman berhenti < 5 menit (koin mati/sepi): {(end < 300).mean():.1%}, "
          f"masih terekam sampai 30 menit: {(end >= 1799).mean():.1%}")

    print("\n### PER UKURAN PUNCAK (tanpa koin yang hampir lulus)")
    print("   kolom: jumlah | umur saat ATH (median, p25-p75) | ATH -> -50% | ATH -> -80% | ATH -> -90% (median) | "
          "sudah -90% dalam rekaman | harga terakhir vs ATH (median)")
    for lo, hi_, name in BUCKETS:
        m = (mult >= lo) & (mult < hi_) & ~grad
        if m.sum() < 30:
            continue
        line = (f"   {name:<7} n={m.sum():>7,} | ATH umur {fmt_t(np.median(tath[m]))} "
                f"({fmt_t(pct(tath[m], 25))}-{fmt_t(pct(tath[m], 75))})")
        for d in (d50, d20, d10):
            ok = m & np.isfinite(d)
            line += f" | {fmt_t(np.median(d[ok])) if ok.sum() else '-'} ({ok.sum() / m.sum():.0%} kena)"
        line += f" | terakhir {np.median(last[m]):.0%} dari ATH"
        print(line)
    gm = grad
    if gm.sum() >= 30:
        print(f"\n### HAMPIR LULUS (n={gm.sum():,}): ATH umur median {fmt_t(np.median(tath[gm]))} "
              f"(p25 {fmt_t(pct(tath[gm], 25))}, p75 {fmt_t(pct(tath[gm], 75))}); puncak median {np.median(mult[gm]):.1f}x. "
              "Setelah lulus tidak terekam (pindah ke PumpSwap).")

    print("\n### WAKTU JATUH DARI ATH (semua koin dengan puncak >= 1,5x, tanpa yang hampir lulus)")
    m = (mult >= 1.5) & ~grad
    for d, name in zip((d50, d20, d10), ("-50%", "-80%", "-90%")):
        ok = m & np.isfinite(d)
        if ok.sum():
            print(f"   ATH -> {name}: {ok.sum() / m.sum():.0%} koin kena dalam rekaman; median {fmt_t(np.median(d[ok]))}, "
                  f"p25 {fmt_t(pct(d[ok], 25))}, p75 {fmt_t(pct(d[ok], 75))}, p90 {fmt_t(pct(d[ok], 90))}")
    print(f"\nSelesai {time.time() - t0:.0f} dtk.")


if __name__ == "__main__":
    main()

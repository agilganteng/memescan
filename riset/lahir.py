"""Beli begitu koin LAHIR, jual cepat (naik sedikit atau setelah beberapa detik). 28 Okt 2026.

Ide user: auto beli saat koin baru dibuat, lalu beberapa detik kemudian atau saat naik sedikit langsung jual.
Mesin harga sama dengan riset/kol.py (harga per trade dari kurva, dipasang ulang ke close tiap candle; jual juga kena
jeda >= 0,4 dtk; biaya 1,25%/3% per sisi + priority fee 0,0005 SOL x2 + dampak harga order 0,1 SOL).
Waktu lahir = trade pertama yang terekam (biasanya beli dev di blok pembuatan).
Jeda beli: 0 (mustahil, satu blok dengan dev), 0,4 / 1 / 2 / 3 dtk.
Cara jual: TP +3/5/10/20/50% x maks tahan 2/5/10/30/60 dtk x SL tidak ada/10%/25% (75 cara).
Pilih cara jual terbaik di B (50% koin paling lama), uji sekali di C (50% terbaru) + simulasi $200.
Kurva tidak standar dibuang pakai SELURUH data koin, jadi hasil cenderung terlalu bagus (batas atas).

Pakai: python3 riset/lahir.py --data data
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kol  # noqa: E402

LATS = (0.0, 0.4, 1.0, 2.0, 3.0)
EX = {}
for tp in (1.03, 1.05, 1.10, 1.20, 1.50):
    for T in (2, 5, 10, 30, 60):
        for sl in (None, 0.10, 0.25):
            name = f"TP +{tp - 1:.0%} maks {T}s" + (f" SL {sl:.0%}" if sl else "")
            EX[name] = dict(tp=tp, T=T, **({"sl": sl} if sl else {}))
kol.EXITS.update(EX)
N_SAMPLE = int(os.environ.get("N_SAMPLE", 15000))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t0 = time.time()
    coins = [c for c in kol.load(a.data) if c.kfrom < math.inf and c.kbad == math.inf and c.tbad == math.inf
             and c.w[0][0] < 1.0]
    N = len(coins)
    half = N // 2
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"== {N:,} koin kurva standar dengan trade pertama < 1 dtk. B {ts(coins[0].t0)}-{ts(coins[half - 1].t0)} | "
          f"C {ts(coins[half].t0)}-{ts(coins[-1].t0)} UTC")
    rs = np.random.default_rng(7)
    Bi = sorted(rs.choice(half, min(N_SAMPLE, half), replace=False))
    Ci = sorted(half + rs.choice(N - half, min(N_SAMPLE, N - half), replace=False))
    idx = list(Bi) + list(Ci)
    paths = {i: kol.Path(coins[i], 0) for i in idx}
    print(f"   Sampel {len(Bi):,} koin B + {len(Ci):,} koin C. Siap {time.time() - t0:.0f} dtk.")

    # harga setelah lahir (relatif ke harga setelah trade pertama), tanpa biaya
    base = np.array([paths[i].entry(0.0) for i in idx])
    print("\n== Harga setelah lahir (relatif ke harga tepat setelah trade pertama), tanpa biaya:")
    for dt in (0.4, 1, 2, 3, 5, 10, 30, 60):
        r = np.array([paths[i].price_at(coins[i].w[0][0] + dt) for i in idx]) / base
        print(f"   +{dt:>4} dtk: median {np.median(r):.3f}x, rata {np.mean(r):.3f}x, naik >5% {np.mean(r > 1.05):.0%}, "
              f"turun >5% {np.mean(r < 0.95):.0%}")
    rt = kol.mult(30.0, 30.0, "1,25%")
    print(f"   Biaya pulang-pergi kalau harga tidak bergerak (fee 1,25% x2 + prio + dampak 0,1 SOL): {rt:.3f}x "
          f"-> harga harus naik ~{1 / rt - 1:.1%} hanya untuk impas")

    for L in LATS:
        res = {}
        for ex in EX:
            res[ex] = [kol.sim(paths[i], L, ex, []) for i in idx]

        def tr(sel, ex, cost):
            o = []
            for k in sel:
                x = res[ex][k]
                if x:
                    p_in, p_out, tx = x
                    c = coins[idx[k]]
                    o.append((c.t0 + c.w[0][0] + L, kol.mult(p_in, p_out, cost), c.t0 + tx))
            return o

        sB = range(len(Bi))
        sC = range(len(Bi), len(idx))
        mB = {ex: np.mean([x for _, x, _ in tr(sB, ex, "1,25%")] or [0]) for ex in EX}
        mC = {ex: np.mean([x for _, x, _ in tr(sC, ex, "1,25%")] or [0]) for ex in EX}
        best = max(mB, key=mB.get)
        n_c = sum(v > 1 for v in mC.values())
        top = sorted(mC.items(), key=lambda kv: -kv[1])[:3]
        print(f"\n jeda beli {L} dtk{' (MUSTAHIL: satu blok dengan dev)' if L == 0 else ''}: "
              f"{n_c} dari {len(EX)} cara jual untung di C. Pilihan B: {best} (B {mB[best]:.3f}x)")
        for cost in kol.COSTS:
            print("   " + kol.report(f"UJI C biaya {cost}", tr(sC, best, cost)))
        print("   3 terbaik di C (dipilih setelah lihat C, cuma info): " +
              ", ".join(f"{k} {v:.3f}x" for k, v in top))
        tp_hit = np.mean([1 if (x := res["TP +5% maks 10s"][k]) and x[1] >= x[0] * 1.05 else 0 for k in sC])
        print(f"   TP +5% dalam 10 dtk tercapai (harga jual nyata >= +5%): {tp_hit:.0%} koin")
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk.")


if __name__ == "__main__":
    main()

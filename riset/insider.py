"""Kalau yang di-copy wallet INSIDER (dev, bundler, sniper detik pertama), untung atau tidak? (28 Okt 2026)

Lanjutan riset/kol.py, mesin harga & simulasi sama (harga per trade dari kurva, jeda 0/0,4/1/3/9 dtk, 64 cara jual,
biaya 1,25%/3% per sisi + priority fee + dampak harga 0,1 SOL).
Wallet insider dikenali dari periode A (50% koin paling lama), lalu diuji di koin baru:
  dev koin ini   : dev pembuat koin beli lagi koinnya sendiri (beli pertama setelah 0,5 dtk)
  bundler        : wallet yang di >= 5 koin A beli < 1 dtk setelah koin dibuat (blok yang sama / bundle)
  bundler untung : bundler yang hasilnya sendiri di A untung (SOL jual + sisa token > SOL beli)
  dev berantai   : wallet yang di A sudah bikin >= 3 koin, sekarang beli koin orang lain
Pilih cara jual terbaik di B (20%), uji sekali di C (30% paling baru) + simulasi $200.
Catatan: hampir semua beli insider terjadi < 10 dtk, sebelum snapshot kurva pertama. Kurva tidak standar dibuang pakai
SELURUH data koin (info masa depan), jadi hasil di sini cenderung TERLALU BAGUS (batas atas).

Pakai: python3 riset/insider.py --data data
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kol  # noqa: E402

LATS, EXITS = kol.LATS, kol.EXITS


def own_result(c, w):
    """Hasil wallet itu sendiri di koin c: (SOL jual + sisa token x harga terakhir) / SOL beli."""
    bs = ss = tok = 0.0
    for ag, ww, isb, sol in c.w:
        if ww != w:
            continue
        p = max(kol.candle_close(c, ag), 1e-9)
        if isb:
            bs += sol
            tok += sol / p
        else:
            ss += sol
            tok -= sol / p
    if bs <= 0:
        return None
    return (ss + max(tok, 0.0) * c.cs[-1][4]) / bs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t0 = time.time()
    coins = [c for c in kol.load(a.data) if c.kfrom < math.inf and c.kbad == math.inf and c.tbad == math.inf]
    N = len(coins)
    iA, iB = int(N * 0.5), int(N * 0.7)
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"== {N:,} koin kurva standar (dicek pakai seluruh data koin = optimis). A {ts(coins[0].t0)}-"
          f"{ts(coins[iA - 1].t0)} | B {ts(coins[iA].t0)}-{ts(coins[iB - 1].t0)} | C {ts(coins[iB].t0)}-"
          f"{ts(coins[-1].t0)} UTC. Baca {time.time() - t0:.0f} dtk.")

    # ---------- kenali insider di A
    fast, own, devn = {}, {}, {}
    for c in coins[:iA]:
        if c.dev:
            devn[c.dev] = devn.get(c.dev, 0) + 1
        seen = set()
        for ag, w, isb, sol in c.w:
            if not isb or w in seen:
                continue
            seen.add(w)
            if ag < 1.0 and w != c.dev:
                fast[w] = fast.get(w, 0) + 1
                r = own_result(c, w)
                if r is not None:
                    own.setdefault(w, []).append(r)
    bund = {w for w, n in fast.items() if n >= 5}
    bund_ok = {w for w in bund if len(own.get(w, [])) >= 5 and np.mean(own[w]) > 1.0}
    serial = {w for w, n in devn.items() if n >= 3}
    allown = [x for w in bund for x in own.get(w, [])]
    print(f"   Bundler (>= 5 koin beli < 1 dtk di A): {len(bund):,} wallet, hasil SENDIRI rata "
          f"{np.mean(allown):.3f}x, median {np.median(allown):.3f}x. Yang untung sendiri: {len(bund_ok):,}. "
          f"Dev berantai (>= 3 koin): {len(serial):,}.")

    groups = {"dev koin ini": None, "bundler": bund, "bundler untung": bund_ok, "dev berantai": serial}
    ev = {g: [] for g in groups}
    for ci in range(iA, N):
        c = coins[ci]
        done = set()
        for j, (ag, w, isb, sol) in enumerate(c.w):
            if not isb:
                continue
            for g, S in groups.items():
                if g in done:
                    continue
                hit = (w == c.dev and ag >= 0.5) if S is None else (w in S and w != c.dev)
                if hit:
                    done.add(g)
                    sells = sorted(x[0] for x in c.w if x[1] == w and not x[2])
                    ev[g].append((ci, j, sells))
    # Batasi: maks 4000 sinyal B + 6000 sinyal C per kelompok (sampel acak tetap), supaya muat waktu.
    rs = np.random.default_rng(1)
    for g, E in ev.items():
        Bx = [e for e in E if e[0] < iB]
        Cx = [e for e in E if e[0] >= iB]
        if len(Bx) > 4000:
            Bx = [Bx[i] for i in sorted(rs.choice(len(Bx), 4000, replace=False))]
        if len(Cx) > 6000:
            Cx = [Cx[i] for i in sorted(rs.choice(len(Cx), 6000, replace=False))]
        print(f"   {g}: {len(E):,} sinyal di B+C, dipakai {len(Bx) + len(Cx):,}")
        ev[g] = Bx + Cx
    paths = {}

    def P(ci, j):
        if (ci, j) not in paths:
            paths[(ci, j)] = kol.Path(coins[ci], j)
        return paths[(ci, j)]

    for g, E in ev.items():
        if len(E) < 60:
            print(f"\n== {g.upper()}: cuma {len(E)} sinyal, terlalu sedikit.")
            continue
        ages = np.array([coins[ci].w[j][0] for ci, j, _ in E])
        print(f"\n== COPY {g.upper()}: {len(E):,} koin (umur saat dia beli median {np.median(ages):.1f} dtk)")
        base = np.array([P(ci, j).entry(0.0) for ci, j, _ in E])
        for dt in (0.4, 1, 3, 10, 60, 300):
            r = np.array([P(ci, j).price_at(coins[ci].w[j][0] + dt) for ci, j, _ in E]) / base
            print(f"   harga +{dt} dtk setelah dia beli: median {np.median(r):.3f}x, rata {np.mean(r):.3f}x")
        Bi = [k for k, (ci, _, _) in enumerate(E) if ci < iB]
        Ci = [k for k, (ci, _, _) in enumerate(E) if ci >= iB]
        for L in LATS:
            res = {}
            for ex in EXITS:
                out = []
                for k, (ci, j, sells) in enumerate(E):
                    r = kol.sim(P(ci, j), L, ex, sells)
                    out.append(None if r is None else (r, coins[ci].t0))
                res[ex] = out

            def tr(idx, ex, cost):
                o = []
                for k in idx:
                    x = res[ex][k]
                    if x:
                        (p_in, p_out, tx), t0c = x
                        o.append((t0c + coins[E[k][0]].w[E[k][1]][0] + L, kol.mult(p_in, p_out, cost), t0c + tx))
                return o
            mB = {ex: np.mean([x for _, x, _ in tr(Bi, ex, "1,25%")] or [0]) for ex in EXITS}
            best = max(mB, key=mB.get)
            n_c = sum(np.mean([x for _, x, _ in tr(Ci, ex, "1,25%")] or [0]) > 1 for ex in EXITS)
            print(f" jeda {L} dtk{' (MUSTAHIL)' if L == 0 else ''}: untung di C {n_c} dari {len(EXITS)} cara jual. "
                  f"Pilihan B: {best} (B {mB[best]:.3f}x)")
            for cost in kol.COSTS:
                print("   " + kol.report(f"UJI C biaya {cost}", tr(Ci, best, cost)))
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk.")


if __name__ == "__main__":
    main()

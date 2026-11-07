"""Backtest bot "pumpfunbots-reverse" dari post X @zostaff (7 Nov 2026): "666 wallet di-reverse-engineer, 7 bot".

Aturan diambil persis dari post + artikel (ditulis di sini SEBELUM melihat hasil):
  B1 SNIPER: koin baru, dev beli >= 0,5 SOL (SNIPER_MIN_DEV_BUY) -> beli 0,1 SOL.
     Jual versi post   : TP 2x, SL -50%, maks 120 dtk.
     Jual versi artikel: TP 1,5x, SL -30% (0,7x), maks 30 dtk.
     Varian dev buy: 0 (snipe buta) / 0,5 / 1 / 2 SOL. Jeda beli setelah trade pertama: 0,4 / 1 / 2 dtk
     (bot websocket + Helius; artikel sendiri bilang copy 1-2 dtk). Grid jual TP {1,2 1,5 2 3} x SL {0,5 0,7 0,85}
     x maks {10, 30, 120, 300 dtk} = 48 cara jual, dipilih di A, diuji sekali di B.
  B2 GRADUATION SNIPER: beli saat kurva terisi >= 92% (mcap ~364 SOL), jeda 1 dtk.
     Rekaman kita berhenti saat koin lulus (pindah ke PumpSwap), jadi "tahan sampai lulus" dinilai di harga kurva
     terakhir = BATAS ATAS (harga AMM setelah lulus tidak terlihat). Jual: TP {+5, +10%} / SL {-10, -20%} /
     maks {30, 120, 600 dtk} / tahan sampai rekaman habis.
  B3 COPY TRADER wallet "Direct HFT 80% win": wallet yang di periode A (5 menit pertama tiap koin) trade >= 20 koin,
     menang >= 80% (SOL jual > SOL beli per koin), total untung > 0. Ditiru di B: beli jeda 1 / 2 dtk setelah dia beli,
     jual jeda sama setelah dia jual (maks 30 menit), ukuran 0,05 SOL (COPY_BUY_SOL).
Biaya: fee 1,25%/sisi + priority/tip 0,0005 SOL x2 + dampak kurva. Koin kurva tidak standar dibuang (pakai seluruh
data koin -> sedikit optimistis, sama dengan riset/lahir.py).
Modal $100/$200/$1000, ukuran tetap 0,1 SOL per trade (0,05 untuk copy), maks 3 posisi bersamaan.
BATAS: rekaman mulai Okt 2026, tiap koin 30 menit pertama di kurva; Jan 2026 - sekarang TIDAK bisa disimulasikan.

Pakai: python3 riset/zostaff.py --data data
"""
import argparse
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bevan  # noqa: E402
import kol  # noqa: E402
import memescan as ms  # noqa: E402

PRIO = 0.0005
FEE = 0.0125
CAPS = (100.0, 200.0, 1000.0)
GRAD_MC = (30 + 0.92 * 85) ** 2 / kol.K_CURVE      # ~364 SOL
SN_EXITS = [(tp, sl, T) for tp in (1.2, 1.5, 2.0, 3.0) for sl in (0.5, 0.7, 0.85) for T in (10, 30, 120, 300)]
POST_EXIT = SN_EXITS.index((2.0, 0.5, 120))
ART_EXIT = SN_EXITS.index((1.5, 0.7, 30))
GR_EXITS = [(tp, sl, T) for tp in (1.05, 1.10, math.inf) for sl in (0.9, 0.8, 0.0) for T in (30, 120, 600, 1800)]


def mult(p_in, p_out, size):
    e = p_in * (1 + size / ms.v_sol_at(p_in)) / (1 - FEE)
    s = p_out * (1 - FEE) / (1 + size / ms.v_sol_at(max(p_out, 1e-9)))
    return s / e - 2 * PRIO / size


def exit_tp_sl(c, path, te, p_in, tp, sl, T, lx):
    tpp, slp, tl = p_in * tp, p_in * sl, te + T
    for t, cl, hi, lo in path.points(te):
        if t >= tl:
            return path.price_at(tl + lx), tl + lx
        if lo <= slp:
            return min(slp, path.price_at(t + lx)), t + lx
        if hi >= tpp:
            return (path.price_at(t + lx) if hi == lo else tpp), t + lx
    return path.price_at(c.end), c.end


def sim_fixed(raw, cap, size_sol, sol_usd, max_pos=3):
    """raw: (t_in, x, t_out). Ukuran tetap size_sol."""
    eq, open_, n, k, peak, mdd = cap, [], 0, 0, cap, 0.0
    stake = size_sol * sol_usd
    for t, x, tx in sorted(raw):
        still = []
        for te, xx in open_:
            if te <= t:
                eq += stake * xx
            else:
                still.append((te, xx))
        open_ = still
        if len(open_) >= max_pos or eq < stake:
            continue
        eq -= stake
        open_.append((tx, x))
        n += 1
        k += x > 1
        tot = eq + stake * len(open_)
        peak = max(peak, tot)
        mdd = max(mdd, 1 - tot / peak)
    eq += sum(stake * xx for _, xx in open_)
    return eq, n, k, mdd


def report(label, raw, size_sol, sol_usd):
    xs = np.array([x for _, x, _ in raw])
    if not len(xs):
        return f"   {label}: 0 trade"
    k = int((xs > 1).sum())
    lo, hi = ms.wilson(k, len(xs))
    s = (f"   {label}: n={len(xs)}{' (<30!)' if len(xs) < 30 else ''} rata {xs.mean():.3f}x median {np.median(xs):.3f}x "
         f"menang {k / len(xs):.0%} [{lo:.0%}-{hi:.0%}]")
    for cap in CAPS:
        eq, n, kk, mdd = sim_fixed(raw, cap, size_sol, sol_usd)
        s += f" | ${cap:.0f}->${eq:,.2f} ({n} trade)"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t0 = time.time()
    import hybrid as hy
    hs, ps, src = hy.sol_prices(time.time() - 40 * 86400, time.time())
    sol_usd = float(np.median(ps))
    coins, n_all = bevan.load(a.data)
    coins = [c for c in coins if c.std and c.w[0][0] < 1.0]
    for i, c in enumerate(coins):
        c.i = i
    half_t = coins[len(coins) // 2].t0
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))  # noqa: E731
    print(f"== {len(coins):,} koin pump.fun kurva standar dengan data trade ({ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC), "
          f"A < {ts(half_t)} <= B. SOL ${sol_usd:.0f} ({src}).")
    print("   BATAS: rekaman mulai Okt 2026; Jan 2026 - sekarang tidak bisa disimulasikan.")

    # ================= B1 SNIPER
    print("\n################ B1 SNIPER (dev buy filter + TP/SL/timeout)")
    devbuy = np.array([sum(s for ag, w, b, s in c.w if b and w == c.dev and ag < 1.0) for c in coins])
    isA = np.array([c.t0 < half_t for c in coins])
    print(f"   Dev beli >= 0,5 SOL: {np.mean(devbuy >= 0.5):.0%} koin; >= 1: {np.mean(devbuy >= 1):.0%}; >= 2: {np.mean(devbuy >= 2):.0%}")
    rng = np.random.default_rng(11)
    for L in (0.4, 1.0, 2.0):
        for dmin in (0.0, 0.5, 1.0, 2.0):
            idx = np.where(devbuy >= dmin)[0]
            if len(idx) > 30000:      # sampel supaya cepat
                idx = np.sort(rng.choice(idx, 30000, replace=False))
            X = np.full((len(idx), len(SN_EXITS)), np.nan)
            R = [[None] * len(SN_EXITS) for _ in idx]
            for r, ci in enumerate(idx):
                c = coins[ci]
                p = bevan.path(c)
                te = c.w[0][0] + L
                if te >= c.end - 1:
                    c.path = None
                    continue
                p_in = p.price_at(te)
                for k, (tp, sl, T) in enumerate(SN_EXITS):
                    p_out, tx = exit_tp_sl(c, p, te, p_in, tp, sl, T, max(L, 0.4))
                    X[r, k] = mult(p_in, p_out, 0.1)
                    R[r][k] = (c.t0 + te, X[r, k], c.t0 + tx)
                c.path = None
            ok = ~np.isnan(X[:, 0])
            a_ = isA[idx] & ok
            b_ = ~isA[idx] & ok
            mA = X[a_].mean(axis=0)
            mB = X[b_].mean(axis=0)
            kb = int(np.argmax(mA))
            print(f"\n   jeda {L} dtk, dev buy >= {dmin} SOL ({int(ok.sum()):,} koin): cara jual untung di A {int((mA > 1).sum())}/48,"
                  f" di B {int((mB > 1).sum())}/48, keduanya {int(((mA > 1) & (mB > 1)).sum())}")
            for lab, k in (("versi POST  TP2x SL-50% 120s", POST_EXIT), ("versi ARTIKEL TP1.5x SL-30% 30s", ART_EXIT),
                           (f"terbaik di A TP{SN_EXITS[kb][0]}x SL{SN_EXITS[kb][1]} {SN_EXITS[kb][2]}s", kb)):
                raw = [R[r][k] for r in np.where(b_)[0]]
                print(report(f"{lab} [B]", raw, 0.1, sol_usd) + f" | A {mA[k]:.3f}x")

    # ================= B2 GRADUATION SNIPER
    print(f"\n################ B2 GRADUATION SNIPER (beli saat mcap >= {GRAD_MC:.0f} SOL = kurva 92%)")
    sig = []
    for c in coins:
        hit = next((x[0] for x in c.cs if x[2] >= GRAD_MC), None)
        if hit is None:
            continue
        p = bevan.path(c)
        # waktu pertama harga >= ambang (tick kalau dalam cakupan trade, kalau tidak awal candle)
        t_hit = next((t for t, cl, hi, lo in p.points(0.0) if hi >= GRAD_MC), None)
        c.path = None
        if t_hit is not None:
            sig.append((c.i, t_hit))
    end_mc = np.array([coins[ci].cs[-1][4] for ci, _ in sig] or [0.0])
    print(f"   {len(sig):,} koin pernah sampai 92% ({len(sig) / len(coins):.2%} dari semua). Harga akhir rekaman >= 98% kurva "
          f"(kemungkinan lulus): {np.mean(end_mc >= (30 + 0.98 * 85) ** 2 / kol.K_CURVE):.0%}")
    for L in (1.0, 3.0):
        XA, XB, RB = [], [], {k: [] for k in range(len(GR_EXITS))}
        for ci, th in sig:
            c = coins[ci]
            p = bevan.path(c)
            te = th + L
            if te >= c.end - 1:
                c.path = None
                continue
            p_in = p.price_at(te)
            xs = []
            for k, (tp, sl, T) in enumerate(GR_EXITS):
                p_out, tx = exit_tp_sl(c, p, te, p_in, tp, sl if sl > 0 else 1e-9, T, L)
                x = mult(p_in, p_out, 0.1)
                xs.append(x)
                if c.t0 >= half_t:
                    RB[k].append((c.t0 + te, x, c.t0 + tx))
            c.path = None
            (XA if c.t0 < half_t else XB).append(xs)
        if not XA or not XB:
            print(f"   jeda {L} dtk: data kurang (A {len(XA)}, B {len(XB)})")
            continue
        XA, XB = np.array(XA), np.array(XB)
        mA, mB = XA.mean(axis=0), XB.mean(axis=0)
        kb = int(np.argmax(mA))
        hold = GR_EXITS.index((math.inf, 0.0, 1800))
        print(f"\n   jeda {L} dtk: A n={len(XA)}, B n={len(XB)}. Cara jual untung di A {int((mA > 1).sum())}/{len(GR_EXITS)}, "
              f"B {int((mB > 1).sum())}, keduanya {int(((mA > 1) & (mB > 1)).sum())}")
        for lab, k in (("tahan sampai lulus/rekaman habis (BATAS ATAS)", hold),
                       (f"terbaik di A {GR_EXITS[kb]}", kb)):
            print(report(f"{lab} [B]", RB[k], 0.1, sol_usd) + f" | A {mA[k]:.3f}x")

    # ================= B3 COPY "80% WIN" WALLETS
    print("\n################ B3 COPY TRADER wallet 'Direct HFT 80% win' (dinilai di A, ditiru di B)")
    st = {}
    for c in coins:
        if c.t0 >= half_t:
            break
        per = {}
        for ag, w, b, s in c.w:
            d = per.setdefault(w, [0.0, 0.0])
            d[0 if b else 1] += s
        for w, (bs, ss) in per.items():
            if bs <= 0 or ss <= 0:
                continue
            e = st.setdefault(w, [0, 0, 0.0])
            e[0] += 1
            e[1] += ss > bs
            e[2] += ss - bs
    good = {w for w, (n, k, pnl) in st.items() if n >= 20 and k / n >= 0.8 and pnl > 0}
    print(f"   Wallet dengan >= 20 koin di A: {sum(1 for v in st.values() if v[0] >= 20):,}; lolos 'menang >= 80% & untung': "
          f"{len(good):,}")
    if good:
        tops = sorted(((st[w][2], w) for w in good), reverse=True)[:5]
        print("   5 teratas di A (wallet 10 huruf, untung SOL, koin, menang): " +
              "; ".join(f"{w} +{p:.1f} SOL {st[w][0]} koin {st[w][1] / st[w][0]:.0%}" for p, w in tops))
    for L in (1.0, 2.0):
        raw, xs_win = [], []
        for c in coins:
            if c.t0 < half_t:
                continue
            seen = set()
            for j, (ag, w, b, s) in enumerate(c.w):
                if not b or w not in good or w in seen:
                    continue
                seen.add(w)
                sells = [a2 for a2, w2, b2, s2 in c.w if w2 == w and not b2 and a2 > ag]
                p = kol.Path(c, j)
                r = kol.sim(p, L, "ikut jual KOL (maks 30 mnt)", sells)
                if r:
                    p_in, p_out, tx = r
                    x = mult(p_in, p_out, 0.05)
                    raw.append((c.t0 + ag + L, x, c.t0 + tx))
        print(report(f"copy jeda {L} dtk, ikut jual [B]", raw, 0.05, sol_usd))
    print(f"\nSelesai {time.time() - t0:.0f} dtk. Paper saja, tidak ada transaksi.")


if __name__ == "__main__":
    main()

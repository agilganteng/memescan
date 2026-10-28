"""Beli SEMUA koin (saldo tak terbatas), lalu bandingkan koin yang untung vs rugi (28 Okt 2026).

Pertanyaan user: dari ratusan ribu koin pasti ada yang untung. Apa bedanya dengan yang rugi, dan apakah
beda itu bisa dilihat SAAT kita beli?

Cara (ditulis sebelum lihat hasil):
  - Umur beli 10 / 30 / 60 / 120 dtk. Fitur hanya dari data sebelum umur itu (snapshot + trade wallet).
  - Kurva standar dicek kausal (snapshot sebelum umur beli), jeda isi acak 3-9 dtk.
  - Hasil per koin: (1) tahan 5 menit, (2) TP 2x / SL 50% / maks 30 menit, biaya 1,25% per sisi.
    Plus "puncak": harga tertinggi 30 menit setelah beli (bukan hasil nyata, cuma untuk lihat yang terbang).
  - Periode A (50% koin paling lama) untuk MENCARI beda; periode B (50% terbaru) untuk MENGUJI beda itu.
  - Model gabungan semua fitur (regresi logistik) dilatih di A, dinilai di B; koin skor tertinggi di B
    dibeli -> simulasi $200.

Pakai: python3 riset/pemenang.py --data data
"""
import argparse
import bisect
import math
import os
import random
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep  # noqa: E402

FI, ms = deep.FI, deep.ms
AGES = (10, 30, 60, 120)
LAT = (3.0, 9.0)
# fee bot 1,25% (atau 3%) per sisi + priority fee 0,0005 SOL pada order 0,1 SOL (~0,5% per sisi)
C1, C3 = 0.0175, 0.035
SNAP_F = ["inflow_sol", "inflow_rate", "unique_buyers", "buyer_rate", "holders", "top10", "top20", "dev_pct",
          "dev_sold_any", "creator_prev_tokens", "creator_prev_rugs", "bundle", "mcap_sol", "liq_sol", "growth",
          "drawdown", "buy_sell_ratio"]
EXTRA_F = ["momentum_10dtk", "beli_sol_10dtk", "jual_sol_10dtk", "n_pembeli", "pembeli_terbesar", "net_beli",
           "porsi_flip", "dev_jual", "dev_beli_sol", "jam_utc"]
FEATS = SNAP_F + EXTRA_F
NAMA = {"inflow_sol": "SOL masuk bersih", "inflow_rate": "SOL masuk per dtk", "unique_buyers": "jumlah pembeli unik",
        "buyer_rate": "pembeli per dtk", "holders": "jumlah holder", "top10": "porsi top-10 holder",
        "top20": "porsi top-20 holder", "dev_pct": "porsi dev", "dev_sold_any": "dev sudah jual",
        "creator_prev_tokens": "koin dev sebelumnya", "creator_prev_rugs": "rug dev sebelumnya",
        "bundle": "porsi bundle", "mcap_sol": "mcap (SOL)", "liq_sol": "SOL di kurva", "growth": "kenaikan dari awal",
        "drawdown": "turun dari puncak", "buy_sell_ratio": "rasio beli/jual", "momentum_10dtk": "naik sejak snapshot sblm",
        "beli_sol_10dtk": "SOL beli 10 dtk terakhir", "jual_sol_10dtk": "SOL jual 10 dtk terakhir",
        "n_pembeli": "wallet pembeli", "pembeli_terbesar": "porsi pembeli terbesar", "net_beli": "porsi beli dr volume",
        "porsi_flip": "porsi pembeli yg sudah jual", "dev_jual": "dev jual (trade)", "dev_beli_sol": "SOL beli dev",
        "jam_utc": "jam UTC"}


def rng_for(c, a):
    return random.Random(zlib.crc32(f"{c.i}:{a}:pm".encode()))


def outcome(c, a):
    """(t_isi, p_in, mult_tahan5m_kotor, mult_tp2sl50_kotor, puncak30m, t_keluar_tp) atau None."""
    r = rng_for(c, a)
    te = a + r.uniform(*LAT)
    if te >= c.end:
        return None
    p_in = deep.price_at(c, te)
    if p_in <= 0:
        return None
    t5 = te + 300 + r.uniform(*LAT)
    p5 = deep.price_at(c, min(t5, c.end))
    k = bisect.bisect_right(c.starts, te)
    peak, out, tx = p_in, None, te + 1800
    for st, en, hi, lo, cl in c.cs[k:]:
        if st >= te + 1800:
            break
        if lo <= p_in * 0.5 and out is None:
            tf = st + r.uniform(*LAT)
            out, tx = min(p_in * 0.5, deep.price_at(c, tf)), tf
        if hi >= p_in * 2 and out is None:
            tf = st + r.uniform(*LAT)
            out, tx = max(p_in * 2 * 0.97, min(p_in * 2, deep.price_at(c, tf))), tf
        peak = max(peak, hi)
    if out is None:
        tx = min(te + 1800, c.end)
        out = deep.price_at(c, tx)
    return te, p_in, p5 / p_in, out / p_in, peak / p_in, tx


def features(c, a):
    s = c.snaps.get(a)
    if s is None:
        return None
    v = [float(s[FI[k]]) for k in SNAP_F]
    pa = max([x for x in ms.REC_SNAPS if x < a], default=None)
    prev = c.snaps.get(pa) if pa else None
    mc, mcp = float(s[FI["mcap_sol"]]), float(prev[FI["mcap_sol"]]) if prev else float("nan")
    mom = mc / mcp if prev and mcp > 0 else float("nan")
    b10 = sum(x for bl in c.buys.values() for t, x in bl if a - 10 <= t < a)
    s10 = sum(x for sl in c.sells.values() for t, x in sl if a - 10 <= t < a)
    bsol, n_b, mx, flip = 0.0, 0, 0.0, 0
    for w, bl in c.buys.items():
        x = sum(y for t, y in bl if t < a)
        if x <= 0:
            continue
        n_b += 1
        bsol += x
        mx = max(mx, x)
        flip += any(t < a for t, _ in c.sells.get(w, []))
    ssol = sum(y for sl in c.sells.values() for t, y in sl if t < a)
    dev_sold = float(any(t < a for t, _ in c.sells.get(c.dev, [])))
    dev_buy = sum(y for t, y in c.buys.get(c.dev, []) if t < a)
    hour = time.gmtime(c.t0).tm_hour
    v += [mom, b10, s10, n_b, mx / bsol if bsol else float("nan"), bsol / (bsol + ssol) if bsol + ssol else float("nan"),
          flip / n_b if n_b else float("nan"), dev_sold, dev_buy, hour]
    return v


def auc(x, y):
    m = ~np.isnan(x)
    x, y = x[m], y[m]
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(x, kind="mergesort")
    ranks = np.empty(len(x))
    xs = x[order]
    # rank rata-rata untuk nilai sama
    i = 0
    r = np.arange(1, len(x) + 1, dtype=float)
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[i]:
            j += 1
        r[i:j + 1] = (i + j + 2) / 2
        i = j + 1
    ranks[order] = r
    return (ranks[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def qtrans(Xa, X):
    """Ubah tiap fitur ke peringkat 0..1 berdasarkan sebaran di A (NaN -> 0,5)."""
    out = np.empty_like(X)
    for j in range(X.shape[1]):
        ref = np.sort(Xa[:, j][~np.isnan(Xa[:, j])])
        col = X[:, j]
        q = np.searchsorted(ref, col, side="right") / max(1, len(ref)) if len(ref) else np.full(len(col), 0.5)
        q = np.where(np.isnan(col), 0.5, q)
        out[:, j] = q
    return out


def logit_fit(X, y, l2=1.0, it=300, lr=0.5):
    X1 = np.hstack([X, X ** 2, np.ones((len(X), 1))])
    w = np.zeros(X1.shape[1])
    for _ in range(it):
        p = 1 / (1 + np.exp(-(X1 @ w)))
        g = X1.T @ (p - y) / len(y) + l2 * w / len(y)
        w -= lr * g
    return w


def logit_pred(w, X):
    X1 = np.hstack([X, X ** 2, np.ones((len(X), 1))])
    return 1 / (1 + np.exp(-(X1 @ w)))


def net(g, c):
    return g * (1 - c) / (1 + c)


def sim(rows, c):
    tr = [(t, net(g, c), tx) for t, g, tx in rows]
    out, mdd = deep.sim200(tr)
    n = len(out)
    w = sum(r[0] > 1 for r in out)
    lo, hi = ms.wilson(w, n)
    eq = out[-1][2] if out else 200.0
    return f"{n} trade, menang {w / n if n else 0:.0%} (CI {lo:.0%}-{hi:.0%}), $200 -> ${eq:.2f}, MDD {mdd:.0%}"


def stat(g, c=C1):
    x = net(g, c)
    return (f"n={len(x):,}, rata {x.mean():.3f}x (CI bawah {x.mean() - 1.96 * x.std() / math.sqrt(len(x)):.3f}), "
            f"median {np.median(x):.3f}x, untung {np.mean(x > 1):.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    args = ap.parse_args()
    t_start = time.time()
    coins, _, n_bad = deep.load(args.data, floor="causal")
    print(f"== {len(coins):,} koin dimuat ({n_bad:,} dibuang: data rusak/inflow 0). "
          f"{time.strftime('%d/%m %H:%M', time.gmtime(coins[0].t0))} - "
          f"{time.strftime('%d/%m %H:%M', time.gmtime(coins[-1].t0))} UTC")
    half = coins[len(coins) // 2].t0
    print(f"   A (cari beda): sebelum {time.strftime('%d/%m %H:%M', time.gmtime(half))} | B (uji): sesudahnya")
    print("   Biaya 1,25% fee + ~0,5% priority fee per sisi (order 0,1 SOL) kecuali disebut lain. Jeda isi acak 3-9 dtk.")

    for a in AGES:
        rows = []
        for c in coins:
            if not (c.kfrom <= a and c.kbad > a and c.tbad > a):
                continue
            o = outcome(c, a)
            if o is None:
                continue
            f = features(c, a)
            if f is None:
                continue
            rows.append((c.t0, o, f))
        if len(rows) < 1000:
            print(f"\n== umur {a}: terlalu sedikit koin ({len(rows)})")
            continue
        t0 = np.array([r[0] for r in rows])
        te = np.array([r[1][0] for r in rows])
        g5 = np.array([r[1][2] for r in rows])
        gt = np.array([r[1][3] for r in rows])
        pk = np.array([r[1][4] for r in rows])
        tx = np.array([r[1][5] for r in rows])
        X = np.array([r[2] for r in rows], dtype=float)
        A, B = t0 < half, t0 >= half
        y = net(g5, C1) > 1
        print(f"\n\n######## BELI SEMUA KOIN DI UMUR {a} DTK ({len(rows):,} koin hidup & kurva standar)")
        for nm, gg in (("tahan 5 menit", g5), ("TP 2x / SL 50% / maks 30m", gt)):
            print(f"  {nm}: semua {stat(gg)}")
            print(f"      A {stat(gg[A])}")
            print(f"      B {stat(gg[B])}")
        x5 = net(g5, C1)
        srt = np.sort(x5 - 1)[::-1]
        tot = srt[srt > 0].sum()
        print(f"  Puncak 30m setelah beli: >=2x {np.mean(pk >= 2):.1%}, >=5x {np.mean(pk >= 5):.2%}, "
              f">=10x {np.mean(pk >= 10):.2%} koin. Rata hasil SEMUA (tahan 5m) {x5.mean():.3f}x.")
        print(f"  Untung dari 1% koin terbaik = {srt[:max(1, len(srt) // 100)].sum() / tot:.0%} dari total untung; "
              f"total untung {tot:,.0f} unit vs total rugi {-srt[srt < 0].sum():,.0f} unit (1 unit = modal 1 trade)")

        # 1. beda per fitur
        print(f"\n  -- BEDA PEMENANG (tahan 5m untung setelah biaya) vs PECUNDANG, per fitur --")
        print(f"     AUC 0,5 = tidak ada beda; >0,5 = makin besar makin sering menang; <0,5 kebalikannya.")
        print(f"     {'fitur':32s} {'median menang A':>16s} {'median kalah A':>15s} {'AUC A':>6s} {'AUC B':>6s}")
        res = []
        for j, k in enumerate(FEATS):
            xa, xb = X[A, j], X[B, j]
            ua, ub = auc(xa, y[A]), auc(xb, y[B])
            mw = np.nanmedian(xa[y[A]]) if np.any(~np.isnan(xa[y[A]])) else float("nan")
            ml = np.nanmedian(xa[~y[A]]) if np.any(~np.isnan(xa[~y[A]])) else float("nan")
            res.append((abs(ua - 0.5), j, k, mw, ml, ua, ub))
        res.sort(reverse=True)
        for _, j, k, mw, ml, ua, ub in res:
            print(f"     {NAMA[k]:32s} {mw:16.4g} {ml:15.4g} {ua:6.3f} {ub:6.3f}")

        # 2. desil untuk 5 fitur terkuat (ambang dari A, dipakai di B)
        print(f"\n  -- 5 fitur terkuat di A: hasil per kelompok (desil, ambang dari A) di A dan B, tahan 5m --")
        for _, j, k, *_ in res[:5]:
            xa = X[A, j]
            qs = np.unique(np.nanquantile(xa[~np.isnan(xa)], np.linspace(0, 1, 11)))
            print(f"   {NAMA[k]}:")
            for lo_, hi_ in zip(qs[:-1], qs[1:]):
                ma = A & (X[:, j] >= lo_) & (X[:, j] <= hi_)
                mb = B & (X[:, j] >= lo_) & (X[:, j] <= hi_)
                if ma.sum() < 30 or mb.sum() < 30:
                    continue
                print(f"     {lo_:9.4g} .. {hi_:9.4g}: A rata {x5[ma].mean():.3f}x untung {np.mean(x5[ma] > 1):.0%} "
                      f"(n={ma.sum():,}) | B rata {x5[mb].mean():.3f}x untung {np.mean(x5[mb] > 1):.0%} "
                      f"(n={mb.sum():,})")

        # 3. model gabungan semua fitur
        Q = qtrans(X[A], X)
        w = logit_fit(Q[A], y[A].astype(float))
        p = logit_pred(w, Q)
        print(f"\n  -- MODEL GABUNGAN {len(FEATS)} fitur (dilatih di A) --")
        print(f"     AUC di A {auc(p[A], y[A]):.3f} | AUC di B (uji) {auc(p[B], y[B]):.3f}")
        cuts = {f: np.quantile(p[A], 1 - f) for f in (0.10, 0.05, 0.01)}
        for fr, cut in cuts.items():
            mb = B & (p >= cut)
            ma = A & (p >= cut)
            print(f"     {fr:.0%} skor tertinggi (ambang dari A): A {stat(g5[ma])}")
            print(f"        B tahan 5m: {stat(g5[mb])}")
            print(f"        B TP2x/SL50: {stat(gt[mb])}")
            idx = np.where(mb)[0]
            r5 = [(t0[i] + te[i], g5[i], t0[i] + te[i] + 300) for i in idx]
            rt = [(t0[i] + te[i], gt[i], t0[i] + tx[i]) for i in idx]
            print(f"        $200 sim B tahan 5m biaya 1,25%+prio: {sim(r5, C1)} | biaya 3%+prio: {sim(r5, C3)}")
            print(f"        $200 sim B TP2x/SL50 biaya 1,25%+prio: {sim(rt, C1)} | biaya 3%+prio: {sim(rt, C3)}")

        # 4. koin yang terbang (puncak >= 5x) vs semua: apa bedanya di detik beli?
        big = pk >= 5
        print(f"\n  -- KOIN YANG TERBANG (puncak >= 5x dalam 30m, {big.sum():,} koin) vs SEMUA, median di detik beli --")
        for _, j, k, *_ in res[:12]:
            print(f"     {NAMA[k]:32s} terbang {np.nanmedian(X[big, j]):10.4g} | semua {np.nanmedian(X[:, j]):10.4g} "
                  f"| AUC terbang A {auc(X[A, j], big[A]):.3f} B {auc(X[B, j], big[B]):.3f}")
        print(f"     Hasil nyata beli koin 'terbang' kalau tahan 5m: rata {x5[big].mean():.3f}x, "
              f"untung {np.mean(x5[big] > 1):.0%} (harga puncak cuma sebentar)")
    print(f"\nSelesai dalam {time.time() - t_start:.0f} dtk.")


if __name__ == "__main__":
    main()

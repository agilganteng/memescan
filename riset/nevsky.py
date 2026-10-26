"""Uji aturan post X @0xNevsky (26 Okt 2026): beli hanya kalau BEBERAPA wallet teratas beli koin yang sama.

Klaim post: bot pantau 10 wallet teratas, beli kalau 4/5/6/7 dari mereka masuk koin yang sama
(koinnya sudah naik 26-47%), jual saat mereka jual. "$78 -> $2.067 semalam, 73,5% menang".

Terjemahan ke data kita (semua trade beli/jual di 5 menit pertama tiap koin pump.fun, sejak 20 Okt):
  A (50% data paling lama) : susun leaderboard wallet (>= 5 koin), versi "untung SOL terbanyak"
                             (seperti leaderboard fomo/GMGN) dan versi "hasil kalau dicopy".
  B (20% berikutnya)       : pilih kombinasi terbaik (top N, k wallet, filter sudah naik, aturan jual)
  C (30% paling baru)      : uji sekali + simulasi $200
Aturan persis post (top 10, >= 4 wallet, ikut jual) tidak dipilih dari data, jadi diuji di B+C.
Koin kurva tidak standar (bug inflow 0 di perekam) dibuang oleh wallet2.load.
Biaya: jeda 3 dtk, fee 1,25%, slippage 2%, priority fee, dampak kurva (sama dengan riset lain).

Pakai: python3 riset/nevsky.py --data data
"""
import argparse
import itertools
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallet2 as w2  # noqa: E402

ms = w2.ms
TOPN = (10, 20, 50, 100, 200)
KS = (1, 2, 3, 4, 5, 6, 7)
PUMP = ((0.0, "tanpa filter"), (1.26, "sudah naik >= 26%"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    cfg = ms.load_config(a.data)
    coins, wid, n_bad = w2.load(a.data)
    N = len(coins)
    if N < 3000:
        print(f"Baru {N} koin dengan data wallet.")
        return
    iA, iB = int(N * 0.5), int(N * 0.7)
    A, B, C = coins[:iA], coins[iA:iB], coins[iB:]
    ts = lambda c: time.strftime("%d/%m %H:%M", time.gmtime(c.t0))
    print(f"== {N:,} koin dengan data wallet ({n_bad} kurva tidak standar dibuang), {len(wid):,} wallet unik.")
    print(f"   A leaderboard {ts(A[0])}-{ts(A[-1])} | B pilih {ts(B[0])}-{ts(B[-1])} | C uji {ts(C[0])}-{ts(C[-1])} UTC")
    S = w2.wallet_stats(A, len(wid), cfg, A[len(A) // 2].t0)
    buy_sol = np.nan_to_num(S["buy_avg"] * S["n"])
    pnl = np.nan_to_num(S["own_roi"] * buy_sol) - buy_sol
    cand = np.nonzero(S["n"] >= 5)[0]
    ranks = {
        "untung SOL terbanyak": cand[np.argsort(-pnl[cand])],
        "hasil copy terbaik": cand[np.argsort(-np.nan_to_num(S["cp_mean"][cand]))],
    }
    print(f"   {len(cand):,} wallet punya >= 5 koin di A.")
    for nm, order in ranks.items():
        t10 = order[:10]
        print(f"   Top 10 '{nm}': untung sendiri {pnl[t10].sum():+.1f} SOL total, "
              f"copy rata {np.nanmean(S['cp_mean'][t10]):.3f}x, sniper bot {int(S['sniper'][t10].sum())}/10")

    def first_buys(cl):
        out = []
        for ci, c in enumerate(cl):
            out.append(sorted((bl[0][0], w) for w, bl in c.buys.items()))
        return out
    FB = {"B": first_buys(B), "C": first_buys(C)}
    cache, hits_cache = {}, {}

    def hits_of(mask, mkey, period):
        key = (mkey, period)
        if key not in hits_cache:
            hl = []
            for ci, fb in enumerate(FB[period]):
                hit = [(t, w) for t, w in fb if mask[w]]
                if hit:
                    hl.append((ci, hit))
            hits_cache[key] = hl
        return hits_cache[key]

    def run(mask, k, pump, e, period, mkey):
        cl = B if period == "B" else C
        tr = []
        for ci, hit in hits_of(mask, mkey, period):
            if len(hit) < k:
                continue
            ent = hit[k - 1][0]
            ws = [w for _, w in hit[:k]]
            c = cl[ci]
            if pump and w2.price_at(c, ent) < pump * c.m0:
                continue
            if e == 0:
                sells = [t for w in ws for t, _ in c.sells.get(w, []) if t > ent]
                ex = min(sells) if sells else min(c.end, max(ent, 300.0))
                key = (period, ci, ent, e, ex)
                if key not in cache:
                    cache[key] = w2.follow_trade(c, ent, ex, cfg)
            else:
                key = (period, ci, ent, e)
                if key not in cache:
                    tp, sl, T = w2.EXITS[e][1]
                    x = ms.res_trade(c.cs, c.end, ent, w2.price_at(c, ent), tp, sl, T, cfg, w2.SIZE)
                    cache[key] = (x[0], x[1]) if x else None
            x = cache[key]
            if x:
                tr.append((c.t0 + ent + cfg["EXEC_DELAY"], x[0], c.t0 + x[1]))
        return tr

    def show(label, tr):
        st = w2.stat([x[1] for x in tr])
        bal, n, w = w2.sim200(tr)
        lo, hi = ms.wilson(w, n) if n else (0, 0)
        print(f"\n {label}")
        print(f"    {w2.fmt(st)} -> {'TERBUKTI' if st[0] >= 30 and st[2] > 1 else 'TIDAK terbukti'}")
        print(f"    SIMULASI $200: {n} trade, menang {w}{f' ({w / n:.0%}, CI {lo:.0%}-{hi:.0%})' if n else ''}, "
              f"akhir ${bal:.2f} ({bal - w2.START:+.2f})" + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))

    def mask_of(rk, n):
        m = np.zeros(len(wid), bool)
        m[ranks[rk][:n]] = True
        return m, (rk, n)

    print("\n== ATURAN PERSIS POST (top 10 untung SOL terbanyak, beli saat >= k masuk, ikut jual), uji di B+C")
    m10 = mask_of("untung SOL terbanyak", 10)
    for k in (1, 2, 3, 4, 7):
        tr = run(*m10[:1], k, 0.0, 0, "B", m10[1]) + run(*m10[:1], k, 0.0, 0, "C", m10[1])
        show(f"top 10, {k} wallet masuk", tr)

    combos = list(itertools.product(ranks, TOPN, KS, range(len(PUMP)), range(len(w2.EXITS))))
    print(f"\n== {len(combos)} kombinasi (2 leaderboard x {len(TOPN)} top N x {len(KS)} k x 2 filter x 4 jual), pilih di B")
    res = []
    for rk, n, k, p, e in combos:
        tr = run(mask_of(rk, n)[0], k, PUMP[p][0], e, "B", (rk, n))
        if len(tr) >= 30:
            v = np.array([x[1] for x in tr])
            res.append((float(v.mean()), len(v), rk, n, k, p, e))
    res.sort(key=lambda r: -r[0])
    print(f"   {len(res)} kombinasi punya >= 30 trade di B, {sum(r[0] > 1 for r in res)} untung di B.")
    ok = 0
    for r in res:
        st = w2.stat([x[1] for x in run(mask_of(r[2], r[3])[0], r[4], PUMP[r[5]][0], r[6], "C", (r[2], r[3]))])
        ok += st[0] >= 30 and st[1] > 1
    print(f"   Dari {len(res)} itu, {ok} tetap untung di C (>= 30 trade).")
    big = [r for r in res if r[4] >= 4]
    print(f"   Khusus k >= 4 (inti klaim post): {len(big)} kombinasi punya >= 30 trade di B, "
          f"{sum(r[0] > 1 for r in big)} untung di B.")
    print("\n== TOP 3 (dipilih di B, diuji sekali di C)")
    for i, r in enumerate(res[:3]):
        print(f"    B: n={r[1]}, rata {r[0]:.3f}x")
        show(f"#{i + 1} top {r[3]} '{r[2]}', {r[4]} wallet masuk, {PUMP[r[5]][1]}, jual {w2.EXITS[r[6]][0]}",
             run(mask_of(r[2], r[3])[0], r[4], PUMP[r[5]][0], r[6], "C", (r[2], r[3])))
    if big:
        r = big[0]
        print(f"\n== TERBAIK DENGAN k >= 4 (B: n={r[1]}, rata {r[0]:.3f}x)")
        show(f"top {r[3]} '{r[2]}', {r[4]} wallet masuk, {PUMP[r[5]][1]}, jual {w2.EXITS[r[6]][0]}",
             run(mask_of(r[2], r[3])[0], r[4], PUMP[r[5]][0], r[6], "C", (r[2], r[3])))
    show("PEMBANDING: beli semua koin di C saat wallet pertama masuk, ikut jual",
         run(np.ones(len(wid), bool), 1, 0.0, 0, "C", "semua"))
    print(f"\n   Selesai {time.time() - t_start:.0f} dtk. Data wallet mulai 20 Okt 2026 dan hanya 5 menit pertama "
          "tiap koin, jadi Jan 2026 - sekarang tidak bisa disimulasikan.")


if __name__ == "__main__":
    main()

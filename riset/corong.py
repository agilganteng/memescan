"""Tiru corong 'GMGN AI Trader' (demo) + banyak variasi filter, uji di semua koin (28 Okt 2026).

Corong demo: safety (bundle <= 30%, dev <= 10%, top-10, honeypot) -> consensus (>= 1 smart money/KOL sudah beli)
-> dev score (reputasi dev) -> timing (bukan 'overheated') -> ML/LLM -> beli 0,01 SOL -> monitor & keluar.
Yang bisa ditiru dari data kita: semua kecuali ML/LLM (honeypot & renounced selalu lolos di pump.fun).

Cara (ditulis sebelum lihat hasil):
  - Bot 'scan' tiap snapshot (umur 10,20,30,45,60,90,120,180 dtk); beli di snapshot PERTAMA yang lolos semua filter.
  - Fitur hanya dari data sebelum umur itu. Kurva standar dicek kausal. Jeda isi acak 3-9 dtk (beli & jual).
  - bundle% = porsi suplai yang dibeli wallet non-dev di detik pertama (dihitung dari SOL / mcap tiap beli).
  - smart wallet = wallet yang di periode A (40% koin paling lama) beli >= 5 koin dan hasil SENDIRI rata >= 1,2x;
    KOL = 93 wallet kolscan (riset/kol_wallets.txt). consensus = jumlah smart+KOL berbeda yang sudah beli.
  - Grid filter: bundle x dev x top10 x consensus x reputasi dev x panas x holder x umur minimal = 11.664 aturan,
    x 6 cara jual = 69.984 strategi. Pilih di B (40-70%), uji SEKALI di C (30% terbaru) + simulasi $200.
  - Biaya: fee 1,25% + priority ~0,5% per sisi (order 0,1 SOL), juga diuji 3% + prio.

Pakai: python3 riset/corong.py --data data
"""
import argparse
import bisect
import itertools
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
AGES = (10, 20, 30, 45, 60, 90, 120, 180)
LAT = (3.0, 9.0)
C1, C3 = 0.0125, 0.03          # fee per sisi; priority fee & dampak harga dihitung terpisah (netx)
SOLUSD = 200.0
STAKE_SOL = 0.1                # diubah oleh --modal (10% modal per trade)
PRIO = 0.0005
EXITS = ["tahan 60 dtk", "tahan 5 mnt", "TP 2x / SL 50% / 30 mnt", "TP +30% / SL 20% / 5 mnt",
         "trail 20% aktif +30% / SL 30% / 30 mnt", "TP +50% / SL 30% / 10 mnt"]
# kolom fitur
BUND, DEV, TOP10, CONS, RUGS, PREV, GROW, HOLD = range(8)


def net(g, c):
    return g * (1 - c) / (1 + c)


def netx(g, mc, c):
    """Hasil bersih: fee per sisi + priority fee 2x + dampak harga order kita sendiri di kurva (v_sol = sqrt(K*mcap))."""
    v_in = np.sqrt(32.19 * np.maximum(mc, 1.0))
    v_out = v_in * np.sqrt(np.maximum(g, 1e-6))
    return g * (1 - c) / (1 + c) / ((1 + STAKE_SOL / v_in) * (1 + STAKE_SOL / v_out)) - 2 * PRIO / STAKE_SOL


def outcomes(c, a):
    """Hasil kotor 6 cara jual + umur keluar, beli di sinyal umur a. None kalau koin sudah selesai."""
    r = random.Random(zlib.crc32(f"{c.i}:{a}:cr".encode()))
    te = a + r.uniform(*LAT)
    if te >= c.end:
        return None
    p = deep.price_at(c, te)
    if p <= 0:
        return None
    lat = lambda: r.uniform(*LAT)
    px = lambda t: deep.price_at(c, min(t, c.end))
    g, tx = [None] * 6, [None] * 6
    t1, t5 = te + 60 + lat(), te + 300 + lat()
    g[0], tx[0] = px(t1) / p, t1
    g[1], tx[1] = px(t5) / p, t5
    rules = {2: (2.0, 0.5, 1800), 3: (1.3, 0.2, 300), 5: (1.5, 0.3, 600)}
    peak, armed = p, False
    k = bisect.bisect_right(c.starts, te)
    for st, en, hi, lo, cl in c.cs[k:]:
        for e, (tp, sl, T) in rules.items():
            if g[e] is not None:
                continue
            if st >= te + T:
                tf = te + T + lat()
                g[e], tx[e] = px(tf) / p, tf
            elif lo <= p * (1 - sl):
                tf = st + lat()
                g[e], tx[e] = min(1 - sl, px(tf) / p), tf
            elif hi >= p * tp:
                tf = st + lat()
                g[e], tx[e] = min(tp, max(tp * 0.97, px(tf) / p)), tf
        if g[4] is None:
            if st >= te + 1800:
                tf = te + 1800 + lat()
                g[4], tx[4] = px(tf) / p, tf
            else:
                stop = max(p * 0.7, peak * 0.8) if armed else p * 0.7
                if lo <= stop:
                    tf = st + lat()
                    g[4], tx[4] = min(stop / p, px(tf) / p), tf
                peak = max(peak, hi)
                armed = armed or peak >= p * 1.3
        if all(x is not None for x in g):
            break
    for e in range(6):
        if g[e] is None:
            g[e], tx[e] = c.cs[-1][4] / p, c.end
    return te, g, tx


def own_res(c, w):
    bs = ss = tok = 0.0
    for t, s in c.buys.get(w, []):
        bs += s
        tok += s / max(deep.price_at(c, t), 1e-9)
    for t, s in c.sells.get(w, []):
        ss += s
        tok -= s / max(deep.price_at(c, t), 1e-9)
    if bs <= 0:
        return None
    return (ss + max(tok, 0.0) * c.cs[-1][4]) / bs


def sim(rows, cost):
    tr = [(t, float(netx(gg, mc, cost)), tx) for t, gg, tx, mc in rows]
    out, mdd = deep.sim200(tr)
    n = len(out)
    w = sum(x[0] > 1 for x in out)
    lo, hi = ms.wilson(w, n)
    eq = out[-1][2] if out else deep.START
    tag = "" if n >= 30 else " (<30 trade, tidak bisa disimpulkan)"
    return (f"{n} trade, menang {w / n if n else 0:.0%} (CI {lo:.0%}-{hi:.0%}), ${deep.START:,.0f} -> ${eq:,.2f}, "
            f"MDD {mdd:.0%}{tag}")


def wallet_board(coins, iA, inv):
    """Wallet yang hasil SENDIRI-nya untung terus di A: dev, bundler/sniper detik pertama, trader lain.
    Lalu: apakah mereka tetap untung di koin sesudahnya (B+C)? Hasil sendiri = harga beli/jual mereka, bukan hasil copy."""
    A, R, devn, fast = {}, {}, {}, {}
    for idx, c in enumerate(coins):
        tgt = A if idx < iA else R
        if idx < iA and c.dev >= 0:
            devn[c.dev] = devn.get(c.dev, 0) + 1
        for w, bl in c.buys.items():
            x = own_res(c, w)
            if x is None:
                continue
            tgt.setdefault(w, []).append(min(x, 1000.0))
            if idx < iA and w != c.dev and min(t for t, _ in bl) < 1.0:
                fast[w] = fast.get(w, 0) + 1
    cats = {
        "DEV (pembuat >= 3 koin di A, hasil di koinnya sendiri)": lambda w: devn.get(w, 0) >= 3,
        "BUNDLER/SNIPER (beli < 1 dtk di >= 5 koin A)": lambda w: fast.get(w, 0) >= 5 and devn.get(w, 0) < 3,
        "TRADER LAIN / smart wallet (>= 10 koin di A)": lambda w: fast.get(w, 0) < 5 and devn.get(w, 0) < 3
        and len(A.get(w, [])) >= 10,
    }
    print("\n==== PAPAN WALLET: hasil SENDIRI di A, lalu di koin sesudahnya (B+C). Alamat = 10 huruf awal (batas rekaman).")
    for name, fn in cats.items():
        ws = [w for w in A if fn(w) and len(A[w]) >= (3 if name.startswith("DEV") else 5)]
        if not ws:
            continue
        allA = np.concatenate([A[w] for w in ws])
        good = [w for w in ws if np.mean(A[w]) >= 1.2 and np.mean(np.array(A[w]) > 1) >= 0.5]
        cont = [w for w in good if len(R.get(w, [])) >= 3]
        stay = [w for w in cont if np.mean(R[w]) > 1.0]
        pool = np.concatenate([R[w] for w in cont]) if cont else np.array([])
        print(f"\n  {name}: {len(ws):,} wallet, rata hasil sendiri di A {allA.mean():.3f}x (median {np.median(allA):.3f}x)")
        print(f"    'untung terus' di A (rata >= 1,2x & menang >= 50%): {len(good):,} wallet. Yang masih aktif di B+C "
              f"(>= 3 koin): {len(cont):,}; tetap untung di B+C: {len(stay):,} ({len(stay) / max(1, len(cont)):.0%}). "
              + (f"Gabungan semua trade mereka di B+C: rata {pool.mean():.3f}x, median {np.median(pool):.3f}x, "
                 f"untung {np.mean(pool > 1):.0%} (n={len(pool):,})" if len(pool) else ""))
        top = sorted(good, key=lambda w: -(np.median(A[w]) * min(len(A[w]), 50)))[:12]
        print(f"    {'wallet':12s} {'koin A':>6s} {'rata A':>8s} {'menang A':>8s} | {'koin B+C':>8s} {'rata B+C':>8s} "
              f"{'menang B+C':>10s}")
        for w in top:
            a, r = np.array(A[w]), np.array(R.get(w, []))
            rb = f"{len(r):8d} {r.mean():8.2f}x {np.mean(r > 1):10.0%}" if len(r) else f"{0:8d} {'-':>9s} {'-':>10s}"
            print(f"    {inv.get(w, '?')[:10]:12s} {len(a):6d} {a.mean():7.2f}x {np.mean(a > 1):8.0%} | {rb}")


def stat(x):
    if len(x) == 0:
        return "0 sinyal"
    lo = x.mean() - 1.96 * x.std() / math.sqrt(len(x)) if len(x) > 1 else float("nan")
    return f"{len(x):,} sinyal, rata {x.mean():.3f}x (CI bawah {lo:.3f}), median {np.median(x):.3f}x, untung {np.mean(x > 1):.0%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--modal", type=float, default=200.0)
    ap.add_argument("--no-smart", action="store_true", help="tanpa syarat smart wallet/KOL sama sekali")
    args = ap.parse_args()
    global STAKE_SOL
    deep.START, deep.MAX_STAKE = args.modal, args.modal * 0.10
    STAKE_SOL = args.modal * 0.10 / SOLUSD
    print(f"== Modal ${args.modal:,.0f}, 10% per trade = {STAKE_SOL:.2f} SOL (SOL ${SOLUSD:.0f}). "
          f"Syarat smart wallet: {'TIDAK dipakai' if args.no_smart else 'ikut diuji'}")
    t_start = time.time()
    coins, wid, n_bad = deep.load(args.data, floor="causal")
    N = len(coins)
    iA, iB = int(N * 0.4), int(N * 0.7)
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"== {N:,} koin. A (kenali smart wallet) {ts(coins[0].t0)}-{ts(coins[iA - 1].t0)} | B (pilih) "
          f"{ts(coins[iA].t0)}-{ts(coins[iB - 1].t0)} | C (uji) {ts(coins[iB].t0)}-{ts(coins[-1].t0)} UTC")

    # smart wallet dari A
    res = {}
    for c in coins[:iA]:
        for w in c.buys:
            if w == c.dev:
                continue
            x = own_res(c, w)
            if x is not None:
                res.setdefault(w, []).append(x)
    smart = {w for w, xs in res.items() if len(xs) >= 5 and np.mean(xs) >= 1.2}
    inv = {v: k for k, v in wid.items()}
    kol_pref = set()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kol_wallets.txt")) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                kol_pref.add(line.split()[0][:10])
    kol = {i for i, w in inv.items() if w[:10] in kol_pref}
    sk = smart | kol
    wallet_board(coins, iA, inv)
    print(f"   smart wallet dari A: {len(smart):,} (dari {sum(len(x) >= 5 for x in res.values()):,} wallet >= 5 koin); "
          f"KOL ditemukan di data: {len(kol)}. Baca {time.time() - t_start:.0f} dtk.")

    nK = len(AGES)
    F = np.full((N, nK, 8), np.nan)
    V = np.zeros((N, nK), dtype=bool)
    G = np.full((N, nK, 6), np.nan)
    MC = np.full((N, nK), 30.0)
    TX = np.zeros((N, nK, 6))
    TE = np.zeros((N, nK))
    for i, c in enumerate(coins[iA:], start=iA):
        bund = 0.0
        for w, bl in c.buys.items():
            if w == c.dev:
                continue
            for t, s in bl:
                if t < 1.0:
                    bund += s / max(deep.price_at(c, t), 1e-9)
        first_buy = {}
        for w in sk & c.buys.keys():
            first_buy[w] = min(t for t, _ in c.buys[w])
        fb = sorted(first_buy.values())
        for k, a in enumerate(AGES):
            s = c.snaps.get(a)
            if s is None or not (c.kfrom <= a and c.kbad > a and c.tbad > a):
                continue
            o = outcomes(c, a)
            if o is None:
                continue
            V[i, k] = True
            F[i, k] = (bund, float(s[FI["dev_pct"]]), float(s[FI["top10"]]), bisect.bisect_left(fb, a),
                       float(s[FI["creator_prev_rugs"]]), float(s[FI["creator_prev_tokens"]]),
                       float(s[FI["growth"]]), float(s[FI["holders"]]))
            TE[i, k] = c.t0 + o[0]
            MC[i, k] = max(float(deep.price_at(c, o[0])), 1.0)
            G[i, k] = o[1]
            TX[i, k] = [c.t0 + x for x in o[2]]
    t0s = np.array([c.t0 for c in coins])
    isB = (np.arange(N) >= iA) & (np.arange(N) < iB)
    isC = np.arange(N) >= iB
    print(f"   Fitur & hasil {V.sum():,} titik scan siap ({time.time() - t_start:.0f} dtk). "
          f"Koin B {isB.sum():,}, C {isC.sum():,}.")

    # dasar: beli semua koin di umur 10 dtk
    for k0 in (0, 2):
        for e in (1, 2):
            m = isC & V[:, k0]
            print(f"   PEMBANDING beli SEMUA koin umur {AGES[k0]} dtk, {EXITS[e]}, C: {stat(netx(G[m, k0, e], MC[m, k0], C1))}")

    grid = dict(
        bund=(0.10, 0.30, 9.0), dev=(0.05, 0.10, 9.0), top10=(0.20, 0.30, 0.55, 9.0), cons=(0,) if args.no_smart else (0, 1, 2, 3),
        rep=("semua", "tanpa rug", "dev baru"), heat=(1.5, 3.0, 1e9), hold=(0, 10, 25), minage=(10, 30, 60))
    keys = list(grid)
    configs = list(itertools.product(*[grid[k] for k in keys]))
    print(f"\n== {len(configs):,} aturan filter x {len(EXITS)} cara jual = {len(configs) * len(EXITS):,} strategi")
    agesA = np.array(AGES)
    rows = []
    for cf in configs:
        p = dict(zip(keys, cf))
        ok = V & (F[:, :, BUND] <= p["bund"]) & (F[:, :, DEV] <= p["dev"]) & (F[:, :, TOP10] <= p["top10"]) \
            & (F[:, :, CONS] >= p["cons"]) & (F[:, :, GROW] <= p["heat"]) & (F[:, :, HOLD] >= p["hold"]) \
            & (agesA[None, :] >= p["minage"])
        if p["rep"] == "tanpa rug":
            ok &= F[:, :, RUGS] == 0
        elif p["rep"] == "dev baru":
            ok &= F[:, :, PREV] == 0
        has = ok.any(1)
        first = ok.argmax(1)
        for part, msk in (("B", isB), ("C", isC)):
            sel = np.where(has & msk)[0]
            kk = first[sel]
            for e in range(len(EXITS)):
                g = G[sel, kk, e]
                rows.append((cf, e, part, len(g), float(netx(g, MC[sel, kk], C1).mean()) if len(g) else float("nan")))
    R = {}
    for cf, e, part, n, m in rows:
        R.setdefault((cf, e), {})[part] = (n, m)
    valid = [(k, v) for k, v in R.items() if v["B"][0] >= 50 and v["C"][0] >= 30]
    nBpos = sum(v["B"][1] > 1 for _, v in valid)
    nCpos = sum(v["C"][1] > 1 for _, v in valid)
    both = sum(v["B"][1] > 1 and v["C"][1] > 1 for _, v in valid)
    print(f"   {len(valid):,} strategi punya >= 50 sinyal di B dan >= 30 di C. Untung di B: {nBpos:,}. "
          f"Untung di C: {nCpos:,}. Untung di B DAN C: {both:,}.")
    # sebaran: apakah yang bagus di B juga bagus di C?
    mb = np.array([v["B"][1] for _, v in valid])
    mc = np.array([v["C"][1] for _, v in valid])
    if len(mb) > 2:
        print(f"   Korelasi hasil B vs C: {np.corrcoef(mb, mc)[0, 1]:.2f}. Hasil C terbaik apa pun "
              f"(dipilih setelah lihat C, cuma info): {mc.max():.3f}x")

    def detail(label, cf, e):
        p = dict(zip(keys, cf))
        ok = V & (F[:, :, BUND] <= p["bund"]) & (F[:, :, DEV] <= p["dev"]) & (F[:, :, TOP10] <= p["top10"]) \
            & (F[:, :, CONS] >= p["cons"]) & (F[:, :, GROW] <= p["heat"]) & (F[:, :, HOLD] >= p["hold"]) \
            & (agesA[None, :] >= p["minage"])
        if p["rep"] == "tanpa rug":
            ok &= F[:, :, RUGS] == 0
        elif p["rep"] == "dev baru":
            ok &= F[:, :, PREV] == 0
        has, first = ok.any(1), ok.argmax(1)
        desc = (f"bundle<={p['bund']:.0%} dev<={p['dev']:.0%} top10<={p['top10']:.0%} smart/KOL>={p['cons']} "
                f"dev:{p['rep']} naik<={p['heat']:g}x holder>={p['hold']} umur>={p['minage']}s | {EXITS[e]}"
                ).replace("900%", "bebas").replace("1e+09x", "bebas")
        print(f"\n {label}: {desc}")
        for part, msk in (("B", isB), ("C", isC)):
            sel = np.where(has & msk)[0]
            kk = first[sel]
            print(f"   {part}: {stat(netx(G[sel, kk, e], MC[sel, kk], C1))}")
        sel = np.where(has & isC)[0]
        kk = first[sel]
        rws = [(TE[i, k], G[i, k, e], TX[i, k, e], MC[i, k]) for i, k in zip(sel, kk)]
        print(f"   sim modal C biaya 1,25%+prio+dampak: {sim(rws, C1)}")
        print(f"   sim modal C biaya 3%+prio+dampak:    {sim(rws, C3)}")

    # 1. aturan demo GMGN apa adanya
    print("\n==== ATURAN DEMO GMGN AI TRADER (bundle <= 30%, dev <= 10%, top10 <= 55%, >= 1 smart/KOL, dev tanpa rug, "
          "bukan overheated <= 3x)")
    for e in range(len(EXITS)):
        detail(f"demo #{e + 1}", (0.30, 0.10, 0.55, 0 if args.no_smart else 1, "tanpa rug", 3.0, 0, 10), e)
    # 2. lima terbaik di B, diuji di C
    valid.sort(key=lambda kv: -kv[1]["B"][1])
    print("\n==== 5 STRATEGI TERBAIK DI B (dipilih tanpa melihat C), diuji di C")
    for r, ((cf, e), v) in enumerate(valid[:5]):
        detail(f"#{r + 1} (B {v['B'][1]:.3f}x n={v['B'][0]})", cf, e)
    print(f"\nSelesai dalam {time.time() - t_start:.0f} dtk.")


if __name__ == "__main__":
    main()

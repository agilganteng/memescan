"""Backtest aturan yang bisa ditiru dari SEMUA video Bevan Pramudito (YouTube, podcast tamu, TikTok, Shorts). 7 Nov 2026.

Aturan ditulis di sini SEBELUM melihat hasil. Sumber tiap aturan ada di laporan
/mnt/project-files/memecoin-screener/bevan-video/strategi-bevan-2026-11-07.md.

DATA: rekaman memescan (koin pump.fun di kurva bonding): candle 5/15/60 dtk sampai 30 menit, snapshot fitur di umur
10..600 dtk, semua trade beli/jual 5 menit pertama (maks 150 trade/koin, wallet 10 huruf pertama, SOL).
Harga per trade direkonstruksi dari kurva (mesin riset/kol.py). Kurva tidak standar dibuang secara kausal.

S1 "CHECKLIST ANTI-RUG" (Leon #2, Behind The Blocks, Folknomics, Theresa, GMGN Trench House):
  Keputusan di umur D = 30/60/120/300 dtk, masuk setelah jeda 3 dtk (manual/GMGN HP; varian 1 dtk).
  Filter (semua dihitung dari data SEBELUM D):
    fresh   : porsi pembeli yang wallet-nya BARU (belum pernah terlihat di rekaman kita, pemanasan 48 jam) <= 30/50/70%/bebas
    awal10  : porsi SOL beli di 10 dtk pertama (selain dev) dari total SOL beli sampai D <= 30/50%/bebas
              (= "berapa persen dibeli di 10 detik pertama / bundle / sniper")
    top10   : top 10 holder <= 25/35%/bebas
    dev     : bebas / dev pegang <= 5% / dev belum jual sama sekali ("tim masih hold")
    rug     : buang pembuat yang pernah dump (ya/tidak)
    holder  : >= 0/30/100
    inflow  : SOL masuk sampai D >= 2/5/20 (ada perhatian/volume)
  Cara jual (versi Bevan, saling bertentangan, semua diuji):
    X1 tahan sampai rekaman habis (30 mnt), tanpa SL ("hold to zero", Ghifari/Brocu)
    X2 cut -30%, sisanya tahan 30 mnt (Leon #2)
    X3 keluar saat dev ATAU pembeli 10 dtk pertama mulai jual ("tim jual = keluar"), SL 50% jaga-jaga.
       Penjualan tim hanya terlihat 5 menit pertama (batas rekaman); setelah itu tahan sampai 30 mnt.
    X4 TP 2x, SL 30% (Pintu: target 2x)
    X5 TP 5x tanpa SL (Inner Circle: jual di 5x)
  4 x 4 x 3 x 3 x 3 x 2 x 3 x 3 = 7.776 filter x 5 cara jual = 38.880 strategi.
  Versi "persis Bevan" (ditetapkan sekarang): D 60, fresh <= 50%, awal10 <= 50%, top10 <= 35%, dev <= 5%, buang rug,
  holder >= 30, inflow >= 5 SOL, jual X2 dan X3.

S2 "SNIPE DEV LANGGANAN" (Short p8xu_3LNGVc: notif GMGN dev yang biasa launch -> snipe; Theresa: target = market
  cap koin tim sebelumnya):
  Sinyal: koin baru dari pembuat yang koin SEBELUMNYA (rekaman sudah selesai sebelum koin ini lahir, kurva standar)
  pernah naik >= M x (puncak/awal) dengan M = 1 (asal pernah launch) / 3 / 10 / 30.
  Masuk: jeda 0,4 dtk (butuh bot cepat), 1 dtk, 3 dtk (notif HP) setelah trade pertama.
  Jual: X1..X5 + X6 = jual saat mcap mencapai puncak koin sebelumnya (target Theresa), tanpa SL.

PEMBAGIAN: koin setelah pemanasan diurut waktu; A = 50% pertama (pilih), B = 50% terakhir (uji SEKALI).
Pilih di A: rata hasil per trade (ukuran 0,1 SOL, biaya ringan), minimal 30 trade di A.
BIAYA: ringan = fee 1,25%/sisi + priority 0,0005 SOL x2 + dampak kurva; realistis = + slippage 2%/sisi.
MODAL: $100/$200/$1000. Ukuran versi Bevan 2% saldo per trade (maks 20 posisi), versi agresif 10% (maks 5).
BATAS: tiap koin cuma 30 menit pertama; Jan 2026 - sekarang TIDAK bisa disimulasikan (rekaman mulai Okt 2026);
  koin lulus (fee > 1-2 SOL), koin umur 3 hari, Nansen/Arkham, narasi tidak ada di data ini.

Pakai: python3 riset/bevan.py --data data
"""
import argparse
import bisect
import itertools
import json
import math
import os
import random
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kol  # noqa: E402
import memescan as ms  # noqa: E402

FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}
PRIO = 0.0005
COSTS = {"ringan": (0.0125, 0.0), "realistis": (0.0125, 0.02)}
RANK_SIZE = 0.1
CAPS = (100.0, 200.0, 1000.0)
SIZINGS = ((0.02, 20, "2%/trade (aturan Bevan)"), (0.10, 5, "10%/trade (agresif)"))
WARMUP = 48 * 3600.0
MIN_INFLOW = 2.0
SAMPLE_EVERY = 25

DS = (30, 60, 120, 300)
FRESH = (0.3, 0.5, 0.7, 9.0)
EARLY = (0.3, 0.5, 9.0)
TOP10 = (0.25, 0.35, 9.0)
DEVR = ("bebas", "dev<=5%", "dev belum jual")
RUG = (True, False)
HOLD = (0, 30, 100)
INFL = (2.0, 5.0, 20.0)
EXITS = {
    "X1 tahan 30 mnt tanpa SL": dict(),
    "X2 cut -30%": dict(sl=0.30),
    "X3 keluar saat tim jual (SL 50%)": dict(team=True, sl=0.50),
    "X4 TP 2x SL 30%": dict(tp=2.0, sl=0.30),
    "X5 TP 5x tanpa SL": dict(tp=5.0),
}
EXN = list(EXITS)
EXACT = (60, 0.5, 0.5, 0.35, "dev<=5%", True, 30, 5.0)


class Coin:
    __slots__ = ("i", "t0", "end", "m0", "cs", "starts", "w", "cov", "kfrom", "kbad", "tbad", "dev", "snaps",
                 "sample", "peak", "std", "path")


def load(data_dir):
    d = os.path.join(data_dir, "rec")
    coins = []
    n_all = 0
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if not r.get("w"):
                        continue
                    n_all += 1
                    c = Coin()
                    c.t0, c.end = float(r["t0"]), float(r["end"])
                    c.m0 = float(r.get("m0") or r["snaps"][0][1])
                    c.cs = [(ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), float(x[1]), float(x[2]),
                             float(x[3])) for x in r["c"]]
                    if not c.cs or c.m0 <= 0:
                        continue
                    c.starts = [x[0] for x in c.cs]
                    c.w = [(float(a), w, int(b), float(s)) for a, w, b, s in r["w"]]
                    c.dev = r.get("dev") or ""
                    c.cov = c.w[-1][0] if len(c.w) >= ms.REC_W_MAX else min(ms.REC_W_AGE, c.end)
                    tb = min([x[1] for x in c.cs if x[3] < kol.FLOOR_MCAP] +
                             [float(s[0]) for s in r["snaps"] if float(s[1]) < kol.FLOOR_MCAP] + [math.inf])
                    kb, kf, ib = math.inf, math.inf, math.inf
                    for sn in r["snaps"]:
                        liq, mc, ag = float(sn[FI["liq_sol"]]), float(sn[1]), float(sn[0])
                        if sn[FI["inflow_sol"]] == 0 and sn[FI["growth"]] > 1.05:
                            ib = min(ib, ag)
                        if liq >= 79 or mc <= 0:
                            continue
                        kf = min(kf, ag)
                        if abs((30 + liq) ** 2 * 1e9 / mc / 3.219e10 - 1) > 0.08:
                            kb = min(kb, ag)
                    c.kfrom, c.kbad, c.tbad = kf, min(kb, ib), tb
                    c.snaps = {int(s[0]): s for s in r["snaps"]}
                    c.sample = n_all % SAMPLE_EVERY == 0
                    c.peak = max(x[2] for x in c.cs)
                    c.std = c.kbad == math.inf and c.tbad == math.inf and c.kfrom < math.inf
                    c.path = None
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                coins.append(c)
    coins.sort(key=lambda c: c.t0)
    for i, c in enumerate(coins):
        c.i = i
    return coins, n_all


def path(c):
    if c.path is None:
        c.path = kol.Path(c, 0)
    return c.path


def run_exit(c, te, p_in, cfg, lx, team_ts, target=None):
    """Return (harga keluar mentah, umur keluar)."""
    p = path(c)
    sl = p_in * (1 - cfg["sl"]) if cfg.get("sl") else -1.0
    tp = p_in * cfg["tp"] if cfg.get("tp") else math.inf
    if target is not None:
        tp = target
    tt = next((t for t in team_ts if t > te), None) if cfg.get("team") else None
    for t, cl, hi, lo in p.points(te):
        if tt is not None and t >= tt:
            return p.price_at(tt + lx), tt + lx
        if lo <= sl:
            return min(sl, p.price_at(t + lx)), t + lx
        if hi >= tp:
            return (p.price_at(t + lx) if hi == lo else tp), t + lx
    if tt is not None and tt < c.end:
        return p.price_at(tt + lx), tt + lx
    return p.price_at(c.end), c.end


def mult(p_in, p_out, size, cost):
    fee, slip = COSTS[cost]
    e = p_in * (1 + size / ms.v_sol_at(p_in)) / ((1 - fee) * (1 - slip))
    s = p_out * (1 - fee) * (1 - slip) / (1 + size / ms.v_sol_at(max(p_out, 1e-9)))
    return s / e - 2 * PRIO / size


def sim_cap(raw, cap, frac, max_pos, cost, sol_usd):
    """raw: list (t_masuk_abs, p_in, p_out, t_keluar_abs). Ukuran = frac x saldo (dihitung ulang tiap trade)."""
    eq, open_, xs, peak, mdd = cap, [], [], cap, 0.0
    for t, p_in, p_out, tx in sorted(raw):
        still = []
        for (t_end, stake, xx) in open_:
            if t_end <= t:
                eq += stake * xx
            else:
                still.append((t_end, stake, xx))
        open_ = still
        tot = eq + sum(s for _, s, _ in open_)
        if len(open_) >= max_pos or tot <= 1.0:
            continue
        stake = min(eq, tot * frac)
        if stake <= 0.05:
            continue
        x = max(0.0, mult(p_in, p_out, stake / sol_usd, cost))
        eq -= stake
        open_.append((tx, stake, x))
        xs.append(x)
        peak = max(peak, tot)
        mdd = max(mdd, 1 - tot / peak)
    eq += sum(s * xx for _, s, xx in open_)
    return eq, xs, mdd


def summ(label, raw, cap, frac, max_pos, cost, sol_usd):
    eq, xs, mdd = sim_cap(raw, cap, frac, max_pos, cost, sol_usd)
    n = len(xs)
    if not n:
        return f"     {label}: ${cap:,.0f} -> 0 trade"
    k = sum(x > 1 for x in xs)
    lo, hi = ms.wilson(k, n)
    return (f"     {label}: ${cap:,.0f} -> ${eq:,.2f} ({eq / cap - 1:+.0%}) | {n} trade{' (<30, tidak bisa disimpulkan)' if n < 30 else ''}"
            f" | menang {k / n:.0%} [CI {lo:.0%}-{hi:.0%}] | rata {np.mean(xs):.3f}x | MDD {mdd:.0%}")


def stats(xs):
    xs = np.asarray(xs)
    if not len(xs):
        return "n=0"
    k = int((xs > 1).sum())
    lo, hi = ms.wilson(k, len(xs))
    best = xs.max()
    wo = (xs.sum() - best) / max(1, len(xs) - 1)
    return (f"n={len(xs)}{' (<30!)' if len(xs) < 30 else ''} rata {xs.mean():.3f}x median {np.median(xs):.3f}x "
            f"menang {k / len(xs):.0%} [{lo:.0%}-{hi:.0%}] tanpa koin terbaik {wo:.3f}x")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    import hybrid as hy
    hs, ps, src = hy.sol_prices(time.time() - 40 * 86400, time.time())
    sol_usd = float(np.median(ps))
    coins, n_all = load(a.data)
    if not coins:
        print("Tidak ada rekaman.")
        return
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))  # noqa: E731
    t_w0 = coins[0].t0
    print(f"== {n_all:,} koin pump.fun dengan data wallet, {ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC. "
          f"Harga SOL {src} median ${sol_usd:.0f}.")
    print("   BATAS DATA: rekaman mulai Okt 2026, tiap koin 30 menit pertama. Jan 2026 - sekarang TIDAK bisa "
          "disimulasikan.")

    # ---- wallet pertama kali terlihat (untuk 'fresh wallet') dan riwayat pembuat
    first_seen = {}
    for c in coins:
        for ag, w, isb, sol in c.w:
            if w not in first_seen:
                first_seen[w] = c.t0 + ag
    pool = [c for c in coins if c.t0 >= t_w0 + WARMUP]
    half_t = pool[len(pool) // 2].t0 if pool else math.inf
    print(f"   Pemanasan 48 jam (untuk 'wallet baru'): dipakai {len(pool):,} koin. A < {ts(half_t)} <= B. "
          f"Wallet unik: {len(first_seen):,}")

    # ================= S1
    print("\n################ S1 CHECKLIST ANTI-RUG BEVAN")
    rows = []    # (ci, D, feats tuple)
    for c in pool:
        for D in DS:
            s = c.snaps.get(D)
            if s is None or D >= c.end - 5 or not (c.kfrom <= D < c.kbad and D < c.tbad):
                continue
            infl = float(s[FI["inflow_sol"]])
            if infl < MIN_INFLOW and not c.sample:
                continue
            buyers, fresh, sol_all, sol_10 = set(), 0, 0.0, 0.0
            for ag, w, isb, sol in c.w:
                if ag > D:
                    break
                if not isb:
                    continue
                sol_all += sol
                if ag < 10 and w != c.dev:
                    sol_10 += sol
                if w not in buyers:
                    buyers.add(w)
                    if first_seen.get(w, 0) >= c.t0 + ag - 1:
                        fresh += 1
            if D > c.cov:   # data wallet tidak lengkap sampai D
                continue
            fr = fresh / max(1, len(buyers))
            ea = sol_10 / sol_all if sol_all else 0.0
            dev_sold = float(s[FI["dev_sold_any"]]) > 0
            rows.append((c.i, D, fr, ea, float(s[FI["top10"]]), float(s[FI["dev_pct"]]), dev_sold,
                         float(s[FI["creator_prev_rugs"]]) > 0, float(s[FI["holders"]]), infl, c.sample))
    print(f"   {len(rows):,} titik keputusan (koin x umur). ({time.time() - t_start:.0f} dtk)")

    # simulasi semua cara jual tiap titik, jeda 3 dtk (+1 dtk untuk varian)
    def team_ts(c):
        early = {w for ag, w, isb, sol in c.w if isb and ag < 10 and w != c.dev}
        return sorted(ag for ag, w, isb, sol in c.w if not isb and (w == c.dev or w in early))

    def sim_row(r, lat):
        c = coins[r[0]]
        te = r[1] + lat
        p_in = path(c).price_at(te)
        if p_in <= 0 or te >= c.end - 1:
            return None
        tts = team_ts(c)
        o = []
        for ex in EXN:
            if not EXITS[ex]:
                p_out, tx = path(c).price_at(c.end), c.end
            else:
                p_out, tx = run_exit(c, te, p_in, EXITS[ex], max(lat, 0.4), tts)
            o.append((c.t0 + te, p_in, p_out, c.t0 + tx))
        return o

    res = {3.0: []}
    last = None
    for r in rows:
        if last is not None and last != r[0]:
            coins[last].path = None          # hemat memori
        last = r[0]
        res[3.0].append(sim_row(r, 3.0))
    if last is not None:
        coins[last].path = None
    print(f"   Simulasi selesai ({time.time() - t_start:.0f} dtk).")
    R = np.array([r[1:10] for r in rows], dtype=float)
    Dv, FR, EA, T10, DP, DS_, RG, HO, IN = R.T
    isA = np.array([coins[r[0]].t0 < half_t for r in rows])
    smp = np.array([r[10] for r in rows])
    XR = {3.0: np.array([[mult(o[k][1], o[k][2], RANK_SIZE, "ringan") if o else np.nan for k in range(len(EXN))]
                         for o in res[3.0]])}

    def lat1(m):
        """Varian jeda 1 dtk, dihitung hanya untuk baris terpilih."""
        X = np.full((len(rows), len(EXN)), np.nan)
        for i in np.where(m)[0]:
            o = sim_row(rows[i], 1.0)
            coins[rows[i][0]].path = None
            if o:
                X[i] = [mult(o[k][1], o[k][2], RANK_SIZE, "ringan") for k in range(len(EXN))]
        return X

    def mask(f):
        D, fr, ea, t10, dv, rg, ho, inf = f
        m = (Dv == D) & (FR <= fr) & (EA <= ea) & (T10 <= t10) & (HO >= ho) & (IN >= inf)
        if dv == "dev<=5%":
            m &= DP <= 0.05
        elif dv == "dev belum jual":
            m &= DS_ == 0
        if rg:
            m &= RG == 0
        return m & ~np.isnan(XR[3.0][:, 0])

    print("\n   Pembanding (sampel acak 1/25 semua koin, tanpa filter, jeda 3 dtk):")
    for D in DS:
        m = smp & (Dv == D) & ~np.isnan(XR[3.0][:, 0])
        print(f"     umur {D:>3}s: " + " | ".join(f"{EXN[k][:2]} {np.nanmean(XR[3.0][m, k]):.3f}x" for k in range(len(EXN)))
              + f" (n={int(m.sum())})")

    def show_rule(f, ks, title, only_b=False):
        m = mask(f)
        print(f"\n   {title}")
        XL = {3.0: XR[3.0], 1.0: lat1(m)}
        for lat in (3.0, 1.0):
            for k in ks:
                for part, pm in (("SEMUA", np.ones_like(isA)), ("A", isA), ("B", ~isA)):
                    if only_b and part != "B":
                        continue
                    print(f"     jeda {lat:.0f}s {EXN[k]} [{part}]: {stats(XL[lat][m & pm, k])}")
        for k in ks:
            raw = [res[3.0][i][k] for i in np.where(m & ~isA)[0]]
            print(f"     -- modal (periode B, jeda 3 dtk), {EXN[k]}:")
            for frac, mp, lab in SIZINGS:
                for cost in COSTS:
                    for cap in CAPS:
                        print(summ(f"{lab}, biaya {cost}", raw, cap, frac, mp, cost, sol_usd))

    show_rule(EXACT, [1, 2], "VERSI PERSIS BEVAN (umur 60s, fresh<=50%, 10dtk<=50%, top10<=35%, dev<=5%, buang rug, "
                             "holder>=30, inflow>=5 SOL)")

    grid = list(itertools.product(DS, FRESH, EARLY, TOP10, DEVR, RUG, HOLD, INFL))
    print(f"\n   GRID: {len(grid):,} filter x {len(EXN)} cara jual = {len(grid) * len(EXN):,} strategi")
    out = []
    for f in grid:
        m = mask(f)
        ma, mb = m & isA, m & ~isA
        na, nb = int(ma.sum()), int(mb.sum())
        if na < 30:
            continue
        xa = XR[3.0][ma].mean(axis=0)
        xb = XR[3.0][mb].mean(axis=0) if nb else np.full(len(EXN), np.nan)
        for k in range(len(EXN)):
            out.append((f, k, na, xa[k], nb, xb[k]))
    ok = [r for r in out if r[4] >= 30]
    pa = sum(r[3] > 1 for r in ok)
    pb = sum(r[5] > 1 for r in ok)
    both = sum(r[3] > 1 and r[5] > 1 for r in ok)
    print(f"   Strategi >= 30 trade di A dan B: {len(ok):,}. Untung di A: {pa:,} | di B: {pb:,} | di keduanya: {both:,}")
    if len(ok) > 10:
        ra = np.argsort(np.argsort([r[3] for r in ok]))
        rb = np.argsort(np.argsort([r[5] for r in ok]))
        print(f"   Korelasi peringkat A vs B: {np.corrcoef(ra, rb)[0, 1]:+.2f}")

    def fdesc(f):
        D, fr, ea, t10, dv, rg, ho, inf = f
        return (f"umur {D}s" + (f", fresh<={fr:.0%}" if fr < 1 else "") + (f", 10dtk<={ea:.0%}" if ea < 1 else "")
                + (f", top10<={t10:.0%}" if t10 < 1 else "") + (f", {dv}" if dv != "bebas" else "")
                + (", buang rug" if rg else "") + (f", holder>={ho}" if ho else "") + f", inflow>={inf:.0f} SOL")

    best = sorted(out, key=lambda r: -r[3])[:10]
    print("\n   10 TERBAIK DI A -> uji sekali di B:")
    for f, k, na, xa, nb, xb in best:
        m = mask(f)
        print(f"\n   * {fdesc(f)} | {EXN[k]}")
        print(f"     A: n={na} {xa:.3f}x -> B: {stats(XR[3.0][m & ~isA, k])}")
        raw = [res[3.0][i][k] for i in np.where(m & ~isA)[0]]
        for frac, mp, lab in SIZINGS:
            for cap in CAPS:
                print(summ(f"{lab}, biaya ringan", raw, cap, frac, mp, "ringan", sol_usd))
    print("\n   (Info saja, dipilih SETELAH lihat B) 5 terbaik di B: ")
    for f, k, na, xa, nb, xb in sorted(ok, key=lambda r: -r[5])[:5]:
        print(f"     {fdesc(f)} | {EXN[k]} | A {xa:.3f}x n={na} | B {xb:.3f}x n={nb}")

    # ================= S2
    print("\n################ S2 SNIPE DEV LANGGANAN (koin baru dari pembuat yang koin sebelumnya pernah naik)")
    hist = {}      # dev -> list (t_selesai, puncak, m0) koin standar yang sudah selesai
    sig = []       # (ci, M_prev, target)
    for c in coins:
        if c.dev and c.t0 >= t_w0 + WARMUP and c.std and c.w[0][0] < 1.0:
            prev = [h for h in hist.get(c.dev, []) if h[0] < c.t0]
            if prev:
                mx = max(prev, key=lambda h: h[1] / h[2])
                sig.append((c.i, mx[1] / mx[2], mx[1]))
        if c.dev and c.std:
            hist.setdefault(c.dev, []).append((c.t0 + c.end, c.peak, c.m0))
    n_dev = sum(1 for c in coins if c.t0 >= t_w0 + WARMUP)
    print(f"   Koin dari pembuat yang pernah launch sebelumnya: {len(sig):,} dari {n_dev:,} "
          f"({len(sig) / max(1, n_dev):.1%})")
    S2EX = EXN + ["X6 jual di puncak koin sebelumnya (tanpa SL)"]
    for M in (1.0, 3.0, 10.0, 30.0):
        sel = [s for s in sig if s[1] >= M]
        print(f"\n   Koin sebelumnya pernah >= {M:.0f}x: {len(sel):,} sinyal")
        for lat in (0.4, 1.0, 3.0):
            by = {k: ([], []) for k in range(len(S2EX))}
            raws = {k: [] for k in range(len(S2EX))}
            for ci, mprev, target in sel:
                c = coins[ci]
                te = c.w[0][0] + lat
                if te >= c.end - 1:
                    continue
                p_in = path(c).price_at(te)
                if p_in <= 0:
                    continue
                tts = team_ts(c)
                for k, ex in enumerate(S2EX):
                    if k < len(EXN):
                        p_out, tx = run_exit(c, te, p_in, EXITS[ex], max(lat, 0.4), tts)
                    else:
                        if target < p_in * 1.2:
                            continue
                        p_out, tx = run_exit(c, te, p_in, {}, max(lat, 0.4), tts, target=target)
                    x = mult(p_in, p_out, RANK_SIZE, "ringan")
                    by[k][0 if c.t0 < half_t else 1].append(x)
                    if c.t0 >= half_t:
                        raws[k].append((c.t0 + te, p_in, p_out, c.t0 + tx))
                c.path = None
            print(f"     jeda {lat} dtk:")
            for k, ex in enumerate(S2EX):
                print(f"       {ex}: A {stats(by[k][0])} | B {stats(by[k][1])}")
            if M in (1.0, 10.0) and lat == 1.0:
                ka = max(range(len(S2EX)), key=lambda k: np.mean(by[k][0]) if by[k][0] else -1)
                print(f"       -> cara jual terbaik di A: {S2EX[ka]}; modal di B:")
                for frac, mp, lab in SIZINGS:
                    for cap in CAPS:
                        print("  " + summ(f"{lab}, biaya ringan", raws[ka], cap, frac, mp, "ringan", sol_usd))
    print(f"\nSelesai {time.time() - t_start:.0f} dtk. Paper saja, tidak ada transaksi.")


if __name__ == "__main__":
    main()

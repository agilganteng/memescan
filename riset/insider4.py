"""Backtest strategi post X @x_insider4 "Grok Bot desk $280 -> $3.412 semalam" + gabungan metode lain (28 Okt 2026).

ATURAN ASLI (dari prompt di post, dipakai persis; bagian yang tidak disebut diisi asumsi yang DITULIS DI SINI sebelum
melihat hasil):
  Scout   : pair baru pump.fun
  Filter  : mint belum dicabut / LP tidak dikunci -> pump.fun selalu lolos (mint dicabut program, LP di kurva/burn).
            top 10 holder > 20% -> buang. Volume 1 jam terakhir < $50.000 -> buang (koin < 1 jam: volume sejak lahir,
            dari candle yang sudah selesai). Dev pernah rug (creator_prev_rugs > 0 di rekaman kita) -> buang.
  Analyst : skor 0-1, di bawah 0,6 tidak beli. Post tidak memberi rumus; kita pakai 5 cek sama bobot:
            rasio beli >= 60% transaksi, harga >= 1,2x harga awal, holder >= 30, dev pegang <= 5%, bundle <= 2.
            Skor = jumlah cek lolos / 5 (>= 0,6 artinya minimal 3 dari 5).
  Executor: 8% saldo saat itu per trade. Maks 1 posisi (varian: maks 5 posisi bersamaan).
  Risk    : stop -6% dari harga isi, trailing aktif setelah +12%. Jarak trailing tidak disebut -> 6% (asumsi).
            Tidak ada batas waktu -> dipegang sampai rekaman habis (umur 30 menit), lalu dinilai harga terakhir.
  Eksekusi: keputusan di snapshot umur 10..600 dtk, isi order setelah jeda acak 3-8 dtk (varian bot cepat 1 dtk).
            Jual juga kena jeda. Dalam satu candle dianggap turun dulu baru naik (pesimis).
  Biaya   : "ringan" = fee 1,25%/sisi + priority fee 0,0005 SOL x2 + dampak harga kurva;
            "realistis" = + slippage 2%/sisi (sama dengan riset Hybrid).
  Modal   : $100, $200, $1000 (8% saldo -> priority fee terasa berat di modal kecil).
Koin kurva tidak standar dibuang SECARA KAUSAL: di snapshot sinyal harus sudah terbukti kurva standar (cek x*y=k).

GABUNGAN METODE LAIN (pilih di periode A = 50% koin pertama, uji SEKALI di B = 50% terakhir):
  top10 maks {20, 28, 35, tanpa}% x volume min {$10k, $25k, $50k, $100k} x dev-rug {buang, abaikan}
  x Analyst {tanpa, >=0,6, >=0,8} x konfirmasi smart wallet {0, >=1, >=2} x umur min {10, 60, 180 dtk}
  x cara jual: SL {6, 15, 30%, tanpa} x trailing {+12%/6%, +30%/15%, +100%/30%, tanpa} x maks tahan {2, 10, 30 menit}
  = 864 filter x 48 cara jual = 41.472 strategi. Smart wallet dinilai HANYA dari koin periode A.

Pakai: python3 riset/insider4.py --data data
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallet2 as w2  # noqa: E402
import hybrid as hy  # noqa: E402

ms = w2.ms
FI = w2.FI
SNAPS = [a for a in ms.REC_SNAPS if a <= 600]
CAPS = (100.0, 200.0, 1000.0)
FRAC = 0.08
LAT = (3.0, 8.0)
PRIO = 0.0005
VOL_LOOSEST = 10000.0
SAMPLE_EVERY = 25
COSTS = {"ringan": (0.0125, 0.0), "realistis": (0.0125, 0.02)}

TOP10S = (0.20, 0.28, 0.35, 9.0)
VOLS = (10000.0, 25000.0, 50000.0, 100000.0)
RUGS = (True, False)
ANALYST = (0.0, 0.6, 0.8)
SMARTS = (0, 1, 2)
MINAGES = (10, 60, 180)
EXITS = []
for sl in (0.06, 0.15, 0.30, 1.0):
    for arm, tr in ((0.12, 0.06), (0.30, 0.15), (1.0, 0.30), (math.inf, 0.0)):
        for tm in (120.0, 600.0, 1800.0):
            EXITS.append((sl, arm, tr, tm))
EX_SL = np.array([e[0] for e in EXITS])
EX_ARM = np.array([e[1] for e in EXITS])
EX_TR = np.array([e[2] for e in EXITS])
EX_TM = np.array([e[3] for e in EXITS])
EXACT_FILTER = (0.20, 50000.0, True, 0.6, 0, 10)
EXACT_EXIT = EXITS.index((0.06, 0.12, 0.06, 1800.0))


def exit_name(k):
    sl, arm, tr, tm = EXITS[k]
    s = f"SL {sl:.0%}" if sl < 1 else "tanpa SL"
    s += f", trailing +{arm:.0%}/{tr:.0%}" if arm < math.inf else ", tanpa trailing"
    return s + f", maks {tm / 60:.0f} mnt"


# ---------------------------------------------------------------- data
class Coin:
    __slots__ = ("i", "t0", "end", "m0", "cs", "starts", "ends", "cumv", "snaps", "buys", "kfrom", "kbad",
                 "has_w", "sample", "dev_sell", "bund_sell", "dev_snap")


def load(data_dir, sol_min_vol, every=None, need_w=False):
    d = os.path.join(data_dir, "rec")
    wid, coins, n_all, n_bug = {}, [], 0, 0
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    n_all += 1
                    tot = sum(float(x[4]) + float(x[5]) for x in r["c"] if ms.rec_bucket_end(x[0]) <= 600)
                    sample = n_all % (every or SAMPLE_EVERY) == 0
                    if tot < sol_min_vol and not sample:
                        continue
                    if need_w and "w" not in r:
                        continue
                    if any(s[FI["inflow_sol"]] == 0 and s[FI["growth"]] > 1.05 for s in r["snaps"]):
                        n_bug += 1
                        continue
                    c = Coin()
                    c.sample = sample
                    c.t0, c.end = float(r["t0"]), float(r["end"])
                    c.m0 = float(r.get("m0") or r["snaps"][0][1])
                    cs, cum, v = [], [], 0.0
                    for x in r["c"]:
                        cs.append((ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), float(x[1]), float(x[2]),
                                   float(x[3])))
                        v += float(x[4]) + float(x[5])
                        cum.append(v)
                    kb, kf = math.inf, math.inf
                    for sn in r["snaps"]:
                        liq, mc, ag = float(sn[FI["liq_sol"]]), float(sn[1]), float(sn[0])
                        if liq >= 79 or mc <= 0:
                            continue
                        kf = min(kf, ag)
                        if abs((30 + liq) ** 2 * 1e9 / mc / 3.219e10 - 1) > 0.08:
                            kb = min(kb, ag)
                    c.kfrom, c.kbad = kf, kb
                    c.cs, c.cumv = cs, cum
                    c.starts = [x[0] for x in cs]
                    c.ends = [x[1] for x in cs]
                    c.snaps = {int(s[0]): s for s in r["snaps"] if int(s[0]) <= 600}
                    b = {}
                    c.has_w = "w" in r
                    dev = r.get("dev")
                    first_sell = {}
                    for age, w, isbuy, sol in r.get("w", []):
                        if isbuy:
                            i = wid.setdefault(w, len(wid))
                            if i not in b:
                                b[i] = float(age)
                        elif w not in first_sell:
                            first_sell[w] = float(age)
                    c.buys = b
                    c.dev_sell = first_sell.get(dev, math.inf) if dev else math.inf
                    bund = {w for age, w, isbuy, sol in r.get("w", []) if isbuy and float(age) < 1.0 and w != dev}
                    c.bund_sell = min([first_sell[w] for w in bund if w in first_sell] + [math.inf])
                    c.dev_snap = min([float(sn[0]) for sn in r["snaps"] if float(sn[FI["dev_sold_any"]]) > 0]
                                     + [math.inf])
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                if c.cs and c.m0 > 0:
                    coins.append(c)
    coins.sort(key=lambda c: c.t0)
    for i, c in enumerate(coins):
        c.i = i
    return coins, wid, n_all, n_bug


def price_at(c, t):
    i = bisect.bisect_right(c.starts, t) - 1
    return c.cs[i][4] if i >= 0 else c.m0


def vol_until(c, t):
    i = bisect.bisect_right(c.ends, t) - 1
    return c.cumv[i] if i >= 0 else 0.0


def analyst(s):
    chk = (s[FI["buy_sell_ratio"]] >= 0.6, s[FI["growth"]] >= 1.2, s[FI["holders"]] >= 30,
           s[FI["dev_pct"]] <= 0.05, s[FI["bundle"]] <= 2)
    return sum(chk) / 5.0


# ---------------------------------------------------------------- smart wallet (dinilai di A saja)
def smart_wallets(coins_a, n_w):
    """Wallet yang di periode A: beli >= 5 koin, dan kalau ditiru (beli 3 dtk setelahnya, jual 5 menit kemudian,
    biaya 1,25%/sisi) rata-ratanya >= 1,2x dan menang >= 40%, bukan sniper (< 50% beli di 2 dtk pertama)."""
    n = np.zeros(n_w)
    s = np.zeros(n_w)
    win = np.zeros(n_w)
    snipe = np.zeros(n_w)
    for c in coins_a:
        if not c.has_w:
            continue
        for w, a in c.buys.items():
            te = a + 3.0
            if te >= c.end:
                continue
            p0 = price_at(c, te)
            p1 = price_at(c, min(c.end, te + 300.0))
            if p0 <= 0:
                continue
            x = p1 / p0 * (1 - 0.0125) ** 2
            n[w] += 1
            s[w] += x
            win[w] += x > 1
            snipe[w] += a < 2.0
    with np.errstate(invalid="ignore", divide="ignore"):
        ok = (n >= 5) & (s / n >= 1.2) & (win / n >= 0.4) & (snipe / n < 0.5)
    return ok


# ---------------------------------------------------------------- simulasi trade (semua cara jual sekaligus)
def trade_all(c, t_sig, cost, size_sol, lat=None):
    """Masuk di t_sig + jeda. Return array hasil (multiplier bersih) per cara jual, array umur keluar, atau None."""
    rng = random.Random(zlib.crc32(f"{c.i}:{t_sig:.1f}".encode()))
    d_in = lat if lat is not None else rng.uniform(*LAT)
    te = t_sig + d_in
    if te >= c.end - 1:
        return None
    p_in = price_at(c, te)
    if p_in <= 0:
        return None
    fee, slip = COSTS[cost]
    entry = p_in * (1 + size_sol / ms.v_sol_at(p_in)) / ((1 - fee) * (1 - slip))
    k = bisect.bisect_right(c.starts, te)
    n = len(EXITS)
    peak = np.full(n, entry)
    armed = np.zeros(n, bool)
    done = np.zeros(n, bool)
    out = np.zeros(n)
    tout = np.full(n, c.end)
    sl_px = entry * (1 - EX_SL)
    last = p_in
    d_out = lat if lat is not None else rng.uniform(*LAT)
    for a, b, h, lo, cl in c.cs[k:]:
        act = ~done
        if not act.any():
            break
        # batas waktu
        tm = act & (a >= te + EX_TM)
        if tm.any():
            px = price_at(c, min(c.end, te + float(EX_TM[tm].min()) + d_out))
            out[tm] = px
            tout[tm] = a
            done |= tm
            act = ~done
        stop = np.where(armed, np.maximum(sl_px, peak * (1 - EX_TR)), sl_px)
        hit = act & (lo <= stop)
        if hit.any():
            pf = price_at(c, min(c.end, a + d_out))
            out[hit] = np.minimum(stop[hit], pf)
            tout[hit] = a
            done |= hit
            act = ~done
        peak = np.where(act, np.maximum(peak, h), peak)
        armed |= act & (peak >= entry * (1 + EX_ARM))
        tr = act & armed & (cl <= peak * (1 - EX_TR))
        if tr.any():
            pf = price_at(c, min(c.end, b + d_out))
            out[tr] = np.minimum(peak[tr] * (1 - EX_TR[tr]), pf)
            tout[tr] = b
            done |= tr
        last = cl
    out[~done] = last
    sell = out * (1 - fee) * (1 - slip) / (1 + size_sol / np.array([ms.v_sol_at(max(p, 1e-9)) for p in out]))
    x = sell / entry - 2 * PRIO / size_sol
    return x, tout, te


# ---------------------------------------------------------------- simulasi modal
def sim(trades, cap, max_pos=1):
    """trades: list (t_masuk_abs, x, t_keluar_abs). Ukuran 8% saldo saat masuk."""
    eq, open_, rows, peak, mdd = cap, [], [], cap, 0.0
    for t, x, tx in sorted(trades):
        still = []
        for (t_end, stake, xx) in open_:
            if t_end <= t:
                eq += stake * xx
            else:
                still.append((t_end, stake, xx))
        open_ = still
        if len(open_) >= max_pos or eq <= 0.01:
            continue
        stake = eq * FRAC
        eq -= stake
        open_.append((tx, stake, x))
        rows.append(x)
        tot = eq + sum(s for _, s, _ in open_)
        peak = max(peak, tot)
        mdd = max(mdd, 1 - tot / peak)
    eq += sum(s * xx for _, s, xx in open_)
    return eq, rows, mdd


def summ(label, trades, cap, max_pos=1):
    eq, rows, mdd = sim(trades, cap, max_pos)
    n = len(rows)
    if not n:
        return f"   {label}: 0 trade"
    k = sum(x > 1 for x in rows)
    lo, hi = ms.wilson(k, n)
    wins = [x - 1 for x in rows if x > 1]
    loss = [x - 1 for x in rows if x <= 1]
    return (f"   {label}: ${cap:,.0f} -> ${eq:,.2f} ({eq / cap - 1:+.0%}) | {n} trade{' (<30!)' if n < 30 else ''} | "
            f"menang {k / n:.0%} [{lo:.0%}-{hi:.0%}] | rata menang {np.mean(wins) if wins else 0:+.1%} "
            f"kalah {np.mean(loss) if loss else 0:+.1%} | terburuk {min(rows) - 1:+.0%} | MDD {mdd:.0%}")


# ---------------------------------------------------------------- utama
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    hs, ps, src = hy.sol_prices(time.time() - 40 * 86400, time.time())
    px = hy.Px(hs, ps)
    coins, wid, n_all, n_bug = load(a.data, VOL_LOOSEST / max(ps))
    if not coins:
        print("Tidak ada rekaman.")
        return
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))  # noqa: E731
    half = coins[len(coins) // 2].t0
    print(f"== Rekaman pump.fun: {n_all:,} koin {ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC. Disimpan {len(coins):,} "
          f"(volume 10 menit >= ${VOL_LOOSEST:,.0f} + sampel 1/{SAMPLE_EVERY} untuk pembanding), {n_bug} bug inflow 0 dibuang.")
    print(f"   Harga SOL {src}: ${min(ps):.0f}-${max(ps):.0f}. Periode A < {ts(half)} <= periode B.")
    print("   Batas data: rekaman mulai pertengahan Okt 2026, tiap koin hanya 30 menit pertama. Jan 2026 - sekarang "
          "TIDAK bisa disimulasikan.")

    smart = smart_wallets([c for c in coins if c.t0 < half], len(wid))
    print(f"   Smart wallet (dinilai di A saja): {int(smart.sum()):,} wallet")

    # baris snapshot (koin, umur) dengan fitur
    R = {k: [] for k in ("ci", "age", "top10", "vol", "rug", "score", "smart", "ok")}
    for c in coins:
        su = px(c.t0)
        sb = sorted(a_ for w, a_ in c.buys.items() if smart[w]) if c.has_w else []
        for age in SNAPS:
            s = c.snaps.get(age)
            if s is None or age > c.end:
                continue
            R["ci"].append(c.i)
            R["age"].append(age)
            R["top10"].append(float(s[FI["top10"]]))
            R["vol"].append(vol_until(c, age) * su)
            R["rug"].append(float(s[FI["creator_prev_rugs"]]) > 0)
            R["score"].append(analyst(s))
            R["smart"].append(bisect.bisect_right(sb, age))
            R["ok"].append(c.kfrom <= age < c.kbad)
    R = {k: np.array(v) for k, v in R.items()}
    print(f"   {len(R['ci']):,} snapshot. Lolos cek kurva standar: {R['ok'].mean():.0%}. ({time.time() - t_start:.0f} dtk)")

    def signals(f):
        t10, vmin, rugk, amin, smin, amin_age = f
        m = (R["ok"] & (R["top10"] <= t10) & (R["vol"] >= vmin) & (R["score"] >= amin - 1e-9)
             & (R["smart"] >= smin) & (R["age"] >= amin_age))
        if rugk:
            m &= ~R["rug"]
        ci, ag = R["ci"][m], R["age"][m]
        first = {}
        for c_, a_ in zip(ci.tolist(), ag.tolist()):
            if c_ not in first:
                first[c_] = a_
        return first

    cache = {}

    def res(ci, age, cost, size_sol, lat=None):
        key = (ci, age, cost, round(size_sol, 4), lat)
        if key not in cache:
            cache[key] = trade_all(coins[ci], float(age), cost, size_sol, lat)
        return cache[key]

    # ============ 1. ATURAN ASLI
    print("\n################ 1. ATURAN ASLI @x_insider4 (tanpa optimasi, semua data)")
    sig = signals(EXACT_FILTER)
    sig_noA = signals(EXACT_FILTER[:3] + (0.0,) + EXACT_FILTER[4:])
    print(f"   Koin lolos semua filter: {len(sig):,} dari {n_all:,} ({len(sig) / max(1, n_all):.3%}); "
          f"tanpa Analyst: {len(sig_noA):,}")
    for cost in COSTS:
        for lat, latlab in ((None, "jeda 3-8 dtk"), (1.0, "jeda 1 dtk (bot cepat)")):
            print(f"\n   -- biaya {cost}, {latlab}")
            for cap in CAPS:
                su = float(np.median(ps))
                size = cap * FRAC / su
                for lab, sg in (("aturan asli", sig), ("tanpa Analyst", sig_noA)):
                    tr = []
                    for ci, age in sg.items():
                        r = res(ci, age, cost, size, lat)
                        if r is not None:
                            x, tout, te = r
                            c = coins[ci]
                            tr.append((c.t0 + te, float(x[EXACT_EXIT]), c.t0 + float(tout[EXACT_EXIT])))
                    print(summ(f"{lab:13s} maks 1 posisi", tr, cap, 1))
                    if cap == 200.0:
                        print(summ(f"{lab:13s} maks 5 posisi", tr, cap, 5))
    # perincian per hari, aturan asli, $200 ringan
    su = float(np.median(ps))
    tr_all = []
    for ci, age in sig.items():
        r = res(ci, age, "ringan", 200 * FRAC / su)
        if r is not None:
            tr_all.append((coins[ci].t0 + r[2], float(r[0][EXACT_EXIT]), coins[ci].t0 + float(r[1][EXACT_EXIT])))
    xs = np.array([x for _, x, _ in tr_all])
    if len(xs):
        print(f"\n   Semua sinyal aturan asli (tanpa batas posisi, $200 ringan): n={len(xs)}, rata {xs.mean():.3f}x, "
              f"median {np.median(xs):.3f}x, menang {np.mean(xs > 1):.0%}, rugi > 6% (stop jebol) {np.mean(xs < 0.94):.0%}, "
              f"rugi > 25% {np.mean(xs < 0.75):.0%}")
        days = {}
        for t, x, _ in tr_all:
            days.setdefault(time.strftime("%d/%m", time.gmtime(t)), []).append(x)
        print("   Per hari: " + " | ".join(f"{d} n={len(v)} {np.mean(v):.2f}x" for d, v in sorted(days.items())))

    # pembanding: beli semua koin (sampel) umur 60 dtk, cara jual sama
    smp = [c for c in coins if c.sample and 60 in c.snaps and c.kfrom <= 60 < c.kbad]
    tr_b = []
    for c in smp:
        r = res(c.i, 60, "ringan", 200 * FRAC / su)
        if r is not None:
            tr_b.append(float(r[0][EXACT_EXIT]))
    if tr_b:
        tb = np.array(tr_b)
        print(f"   Pembanding beli koin acak umur 60 dtk (sampel {len(tb):,}), cara jual sama: rata {tb.mean():.3f}x, "
              f"menang {np.mean(tb > 1):.0%}")

    # ============ 2. GABUNGAN
    print(f"\n################ 2. GABUNGAN METODE LAIN: {len(TOP10S) * len(VOLS) * len(RUGS) * len(ANALYST) * len(SMARTS) * len(MINAGES)} "
          f"filter x {len(EXITS)} cara jual = {len(TOP10S) * len(VOLS) * len(RUGS) * len(ANALYST) * len(SMARTS) * len(MINAGES) * len(EXITS):,} strategi")
    print("   Dipilih di A (biaya ringan, $200, rata hasil per trade, minimal 30 trade), diuji sekali di B.")
    size200 = 200 * FRAC / su
    rows = []
    t1 = time.time()
    for t10 in TOP10S:
        for vmin in VOLS:
            for rugk in RUGS:
                for amin in ANALYST:
                    for smin in SMARTS:
                        for mage in MINAGES:
                            f = (t10, vmin, rugk, amin, smin, mage)
                            sg = signals(f)
                            XA, XB = [], []
                            for ci, age in sg.items():
                                r = res(ci, age, "ringan", size200)
                                if r is None:
                                    continue
                                (XA if coins[ci].t0 < half else XB).append(r[0])
                            XA = np.array(XA) if XA else np.zeros((0, len(EXITS)))
                            XB = np.array(XB) if XB else np.zeros((0, len(EXITS)))
                            for k in range(len(EXITS)):
                                rows.append((f, k, len(XA), float(XA[:, k].mean()) if len(XA) else np.nan,
                                             len(XB), float(XB[:, k].mean()) if len(XB) else np.nan))
    print(f"   Semua strategi dihitung dalam {time.time() - t1:.0f} dtk ({len(cache):,} simulasi trade).")
    ok = [r for r in rows if r[2] >= 30 and r[4] >= 30]
    pa = sum(r[3] > 1 for r in ok)
    pb = sum(r[5] > 1 for r in ok)
    both = sum(r[3] > 1 and r[5] > 1 for r in ok)
    print(f"   Strategi dengan >= 30 trade di A dan B: {len(ok):,}. Untung (rata > 1) di A: {pa:,}, di B: {pb:,}, "
          f"di keduanya: {both:,}.")
    if len(ok) > 10:
        ra = np.argsort(np.argsort([r[3] for r in ok]))
        rb = np.argsort(np.argsort([r[5] for r in ok]))
        print(f"   Korelasi peringkat A vs B (Spearman): {np.corrcoef(ra, rb)[0, 1]:+.2f} (dekat 0 = hasil A tidak "
              f"meramalkan B)")
    best = sorted([r for r in rows if r[2] >= 30], key=lambda r: -r[3])[:10]

    def fdesc(f):
        t10, vmin, rugk, amin, smin, mage = f
        return (f"top10<={t10:.0%}" if t10 < 1 else "top10 bebas") + f", vol>=${vmin / 1000:.0f}k" + \
            (", buang dev-rug" if rugk else "") + (f", skor>={amin}" if amin else "") + \
            (f", smart>={smin}" if smin else "") + f", umur>={mage}s"

    print("\n   10 TERBAIK DI A -> diuji di B (modal $100 / $200 / $1000, maks 1 posisi):")
    for f, k, na, ma, nb, mb in best:
        print(f"\n   * {fdesc(f)} | {exit_name(k)}")
        print(f"     A: n={na} rata {ma:.3f}x  ->  B: n={nb} rata {mb:.3f}x")
        sg = signals(f)
        for cost in COSTS:
            for cap in CAPS:
                tr = []
                for ci, age in sg.items():
                    if coins[ci].t0 < half:
                        continue
                    r = res(ci, age, cost, cap * FRAC / su)
                    if r is not None:
                        tr.append((coins[ci].t0 + r[2], float(r[0][k]), coins[ci].t0 + float(r[1][k])))
                print(summ(f"B biaya {cost:9s}", tr, cap, 1))

    # yang terbaik di B (bukan pilihan sah, cuma info batas atas)
    top_b = sorted(ok, key=lambda r: -r[5])[:5]
    print("\n   (Info saja, dipilih SETELAH melihat B, bukan bukti) 5 terbaik di B:")
    for f, k, na, ma, nb, mb in top_b:
        print(f"     {fdesc(f)} | {exit_name(k)} | A {ma:.3f}x (n={na}) B {mb:.3f}x (n={nb})")
    print(f"\nSelesai {time.time() - t_start:.0f} dtk. Paper saja, tidak ada transaksi.")


if __name__ == "__main__":
    main()

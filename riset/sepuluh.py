"""Pemilih koin 10x: ciri koin yang nanti terbang, dan apakah bisa dipilih SAAT beli (8 Nov 2026).

Pertanyaan user: cari sendiri cara memilih koin yang naik sampai 10x, lihat ciri-cirinya sebelum naik,
tujuannya bot yang benar-benar untung.

Desain (ditulis SEBELUM melihat hasil):
  Data    : semua rekaman memescan (pump.fun, maks 14 hari terakhir), hanya kurva standar dicek kausal.
  Umur    : beli di umur 30 / 60 / 120 / 300 dtk, jeda isi acak 3-9 dtk. Fitur hanya dari data sebelum umur itu.
  Fitur   : 27 fitur snapshot+wallet (pemenang.py) ditambah fitur baru yang dihitung KAUSAL:
            - simbol: panjang, porsi huruf besar, angka, non-ascii
            - narasi tiruan: berapa koin bersimbol sama lahir 6 jam terakhir, puncak terbaik koin simbol sama
              yang rekamannya SUDAH selesai
            - riwayat dev: jumlah koin dev yang sudah selesai, puncak terbaik, berapa yang >=5x
            - wallet "pemburu ekor": pembeli awal koin ini yang di koin-koin SEBELUMNYA (sudah selesai) sering
              beli sebelum koin naik >=5x dari harga beli mereka
            - rezim pasar: koin lahir 60 menit terakhir, porsi koin selesai 6 jam terakhir yang sempat >=5x, jam
  Label   : puncak setelah beli (sampai rekaman selesai, maks 30 menit) >=5x dan >=10x dari harga isi.
  Model   : HistGradientBoosting per umur per label. Split waktu: latih 50% / validasi 20% / uji 30%.
            Null: label latih diacak, proses sama persis -> batas "kebetulan".
  Exit    : 8 exit (tahan, 5 menit, TP3/SL40, TP5/SL50, TP10/SL50, trailing 50% setelah 3x, jual separuh di 3x
            + trailing, trailing 40% setelah 2x). Isi stop/TP = min(level, harga di candle + jeda 3-9 dtk),
            satu candle dianggap turun dulu. Biaya 1,75% per sisi (fee bot 1,25% + priority fee).
  Pilih   : kombinasi (umur x label x ambang skor top 0,5/1/2/5/10% x exit) terbaik di VALIDASI (n>=30),
            ambang skor dikunci dari validasi, lalu diuji SEKALI di periode uji.
  Lulus   : n uji >=30, rata uji >1, rata uji tanpa koin terbaik >1. Plus simulasi $100/$200/$1000, 10%/trade.

Pakai: python3 riset/sepuluh.py --data data
"""
import argparse
import bisect
import heapq
import json
import math
import os
import random
import sys
import time
import zlib
from collections import defaultdict, deque

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep  # noqa: E402
import pemenang as pm  # noqa: E402

FI, ms = deep.FI, deep.ms
AGES = (30, 60, 120, 300)
LAT = (3.0, 9.0)
C1 = 0.0175
FLOOR = 27.0
EXITS = ["HOLD", "H5", "TP3SL40", "TP5SL50", "TP10SL50", "TR3", "HALF3", "TR2"]
EX = {
    "HOLD": dict(sl=None),
    "H5": dict(sl=None, T=300),
    "TP3SL40": dict(sl=0.40, tp=3.0),
    "TP5SL50": dict(sl=0.50, tp=5.0),
    "TP10SL50": dict(sl=0.50, tp=10.0),
    "TR3": dict(sl=0.50, arm=3.0, trail=0.50),
    "HALF3": dict(sl=0.50, half=3.0, arm=3.0, trail=0.50),
    "TR2": dict(sl=0.40, arm=2.0, trail=0.40),
}
NEW_F = ["sym_len", "sym_caps", "sym_digit", "sym_nonascii", "sym_lahir_6j", "sym_puncak_lalu",
         "dev_koin_lalu", "dev_puncak_lalu", "dev_5x_lalu",
         "w_dikenal", "w_pemburu", "w_rate_maks", "w_hit_total", "w_bot",
         "lahir_60m", "rezim_5x_6j"]
FEATS = pm.FEATS + NEW_F
TOPQ = (0.005, 0.01, 0.02, 0.05, 0.10)


class C:  # koin sementara untuk pm.features / deep.price_at
    __slots__ = ("i", "t0", "end", "m0", "cs", "starts", "ends", "snaps", "buys", "sells", "dev")


def rng(i, a, tag):
    return random.Random(zlib.crc32(f"{i}:{a}:{tag}".encode()))


def norm_sym(s):
    return "".join(ch for ch in str(s).upper() if ch.isalnum())[:12]


def sym_feats(s):
    s = str(s or "")
    n = max(1, len(s))
    return [len(s), sum(ch.isupper() for ch in s) / n, float(any(ch.isdigit() for ch in s)),
            float(any(ord(ch) > 127 for ch in s))]


def run_exit(c, te, p_in, ex, r):
    """Kembalikan (mult kotor, t_keluar)."""
    k = bisect.bisect_right(c.starts, te)
    T = ex.get("T")
    sl, tp, arm, trail, half = ex.get("sl"), ex.get("tp"), ex.get("arm"), ex.get("trail"), ex.get("half")
    peak, armed, sold, got = p_in, False, 0.0, 0.0
    for st, en, hi, lo, cl in c.cs[k:]:
        if T is not None and st >= te + T:
            break
        # 1) stop dulu (pesimis), level dari puncak SEBELUM candle ini
        lvl = None
        if armed and trail:
            lvl = peak * (1 - trail)
        elif sl:
            lvl = p_in * (1 - sl)
        if lvl is not None and lo <= lvl:
            tf = st + r.uniform(*LAT)
            fill = min(lvl, deep.price_at(c, tf))
            return (got + (1 - sold) * fill / p_in), tf
        peak = max(peak, hi)
        # 2) TP / separuh / arm
        if tp and hi >= p_in * tp:
            tf = st + r.uniform(*LAT)
            fill = min(p_in * tp, deep.price_at(c, tf))
            return (got + (1 - sold) * fill / p_in), tf
        if half and not sold and hi >= p_in * half:
            tf = st + r.uniform(*LAT)
            fill = min(p_in * half, deep.price_at(c, tf))
            got, sold = 0.5 * fill / p_in, 0.5
        if arm and hi >= p_in * arm:
            armed = True
    tx = min(te + T, c.end) if T is not None else c.end
    return got + (1 - sold) * deep.price_at(c, tx) / p_in, tx


def load(data_dir):
    """Satu lintasan: tiap koin -> baris ringkas per umur (fitur dasar + hasil exit) + data riwayat."""
    d = os.path.join(data_dir, "rec")
    coins, rows, n_all = [], [], 0
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                n_all += 1
                try:
                    r = json.loads(line)
                    c = C()
                    c.i = n_all
                    c.t0, c.end = float(r["t0"]), float(r["end"])
                    c.m0 = float(r.get("m0") or r["snaps"][0][1])
                    if c.m0 <= 0 or not r["c"]:
                        continue
                    c.cs = [(ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), float(x[1]), float(x[2]),
                             float(x[3])) for x in r["c"]]
                    c.starts = [x[0] for x in c.cs]
                    c.ends = [x[1] for x in c.cs]
                    c.snaps = {int(s[0]): s for s in r["snaps"]}
                    b, s = {}, {}
                    for age, w, isbuy, sol in r.get("w", []):
                        (b if isbuy else s).setdefault(w, []).append((float(age), float(sol)))
                    c.buys, c.sells = b, s
                    c.dev = r.get("dev") or ""
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                # kurva standar per snapshot (kausal: dipakai hanya snapshot <= umur beli)
                kf, kb, tb = math.inf, math.inf, math.inf
                for sn in r["snaps"]:
                    liq, mc, ag = float(sn[FI["liq_sol"]]), float(sn[1]), float(sn[0])
                    if mc < FLOOR or (float(sn[FI["inflow_sol"]]) == 0 and float(sn[FI["growth"]]) > 1.05):
                        tb = min(tb, ag)
                    if liq >= 79 or mc <= 0:
                        continue
                    kf = min(kf, ag)
                    if abs((30 + liq) ** 2 * 1e9 / mc / 3.219e10 - 1) > 0.08:
                        kb = min(kb, ag)
                for st, en, hi, lo, cl in c.cs:
                    if lo < FLOOR:
                        tb = min(tb, en)
                        break
                std = kf <= 30 and kb == math.inf and tb == math.inf     # untuk riwayat (koin lampau, boleh lihat semua)
                peak0 = max(x[2] for x in c.cs) / c.m0
                # pembeli awal: harga beli pertama -> puncak sesudahnya
                wl = []
                for w, bl in b.items():
                    if w == c.dev:
                        continue
                    t_b = min(t for t, _ in bl)
                    if t_b >= 300:
                        continue
                    pb = deep.price_at(c, t_b)
                    k = bisect.bisect_right(c.starts, t_b)
                    pk = max([x[2] for x in c.cs[k:]] + [pb])
                    wl.append((hash(w), t_b, pk / pb >= 5 if pb > 0 else False))
                ci = len(coins)
                wl = (np.array([x[0] for x in wl], dtype=np.int64), np.array([x[1] for x in wl], dtype=np.float32),
                      np.array([x[2] for x in wl], dtype=bool))
                coins.append((c.t0, c.t0 + c.end, norm_sym(r.get("s")), hash(c.dev) if c.dev else 0, peak0, std, wl))
                for a in AGES:
                    if not (kf <= a and kb > a and tb > a) or a not in c.snaps:
                        continue
                    rr = rng(c.i, a, "s10")
                    te = a + rr.uniform(*LAT)
                    if te >= c.end:
                        continue
                    p_in = deep.price_at(c, te)
                    if p_in <= 0:
                        continue
                    fv = pm.features(c, a)
                    if fv is None:
                        continue
                    k = bisect.bisect_right(c.starts, te)
                    pk = max([x[2] for x in c.cs[k:]] + [p_in]) / p_in
                    res = [run_exit(c, te, p_in, EX[e], rng(c.i, a, e)) for e in EXITS]
                    rows.append((ci, a, c.t0 + te, np.array(fv + sym_feats(r.get("s")), dtype=np.float32), pk, peak0,
                                 np.array([x[0] for x in res], dtype=np.float32),
                                 np.array([x[1] for x in res], dtype=np.float32), c.t0))
    return coins, rows, n_all


def history_feats(coins, rows):
    """Fitur riwayat kausal: hanya koin yang rekamannya selesai sebelum waktu fitur (t0 + umur)."""
    order = sorted(range(len(coins)), key=lambda i: coins[i][0])
    t0s = np.array([coins[i][0] for i in order])
    sym_t = defaultdict(list)
    for i in order:
        sym_t[coins[i][2]].append(coins[i][0])
    fin = sorted(range(len(coins)), key=lambda i: coins[i][1])
    q = sorted(range(len(rows)), key=lambda j: coins[rows[j][0]][0] + rows[j][1])
    wstat = {}          # wallet -> [n beli awal, n kena >=5x]
    dstat = {}          # dev -> [n, puncak maks, n >=5x]
    sstat = {}          # simbol -> puncak maks
    reg = deque()       # (t selesai, kena 5x)
    reg_hit = 0
    out = [None] * len(rows)
    p = 0
    for j in q:
        ci, a = rows[j][0], rows[j][1]
        t0, _, sym, dev, _, _, wl = coins[ci]
        tq = t0 + a
        while p < len(fin) and coins[fin[p]][1] < tq:
            x = coins[fin[p]]
            p += 1
            if not x[5]:
                continue
            hit5 = x[4] >= 5
            if x[3]:
                ds = dstat.setdefault(x[3], [0, 0.0, 0])
                ds[0] += 1
                ds[1] = max(ds[1], x[4])
                ds[2] += hit5
            if x[2]:
                sstat[x[2]] = max(sstat.get(x[2], 0.0), x[4])
            for w, tb, h in zip(*(v.tolist() for v in x[6])):
                st = wstat.setdefault(w, [0, 0])
                st[0] += 1
                st[1] += h
            reg.append((x[1], hit5))
            reg_hit += hit5
        while reg and reg[0][0] < tq - 6 * 3600:
            reg_hit -= reg.popleft()[1]
        ts = sym_t.get(sym, [])
        n_sym = bisect.bisect_left(ts, tq) - bisect.bisect_left(ts, t0 - 6 * 3600) - 1 if sym else math.nan
        sp = sstat.get(sym, math.nan) if sym else math.nan
        ds = dstat.get(dev) if dev else None
        known = hunt = bot = 0
        hit_tot, rmax = 0, math.nan
        for w, tb in zip(wl[0].tolist(), wl[1].tolist()):
            if tb >= a:
                continue
            st = wstat.get(w)
            if not st:
                continue
            known += st[0] >= 3
            bot += st[0] >= 20
            hit_tot += st[1]
            if st[0] >= 5:
                rt = st[1] / st[0]
                rmax = rt if math.isnan(rmax) else max(rmax, rt)
            hunt += st[1] >= 2 and st[1] / st[0] >= 0.2
        n60 = bisect.bisect_left(t0s, tq) - bisect.bisect_left(t0s, tq - 3600)
        out[j] = np.array([n_sym, sp, ds[0] if ds else 0, ds[1] if ds else math.nan, ds[2] if ds else 0,
                  known, hunt, rmax, hit_tot, bot, n60, reg_hit / len(reg) if reg else math.nan], dtype=np.float32)
    return out


def wil(w, n):
    return ms.wilson(w, n) if n else (0.0, 0.0)


def desc(x):
    if len(x) == 0:
        return "n=0"
    m = x.mean()
    srt = np.sort(x)
    nb = srt[:-1].mean() if len(x) > 1 else math.nan
    w = int((x > 1).sum())
    lo, hi = wil(w, len(x))
    return (f"n={len(x):,} rata {m:.3f}x tanpa-terbaik {nb:.3f}x median {np.median(x):.3f}x "
            f"untung {w / len(x):.1%} [{lo:.0%}-{hi:.0%}] terbaik {srt[-1]:.1f}x")


def bank(trades, cap, frac=0.10, max_stake=300.0):
    """trades: (t_in, t_out, mult bersih). 10% ekuitas per trade (maks $300: kurva pump.fun tipis), boleh bersamaan."""
    ev = []
    for k, (ti, to, m) in enumerate(trades):
        ev.append((ti, 1, k))
        ev.append((max(to, ti + 1e-3), 0, k))
    ev.sort()
    cash, open_, mdd, peak, n = cap, {}, 0.0, cap, 0
    for t, typ, k in ev:
        if typ == 1:
            eq = cash + sum(open_.values())
            st = min(cash, eq * frac, max_stake)
            if st < 0.5:
                continue
            cash -= st
            open_[k] = st
            n += 1
        elif k in open_:
            cash += open_.pop(k) * trades[k][2]
            eq = cash + sum(open_.values())
            peak = max(peak, eq)
            mdd = max(mdd, 1 - eq / peak if peak > 0 else 0)
    return cash + sum(open_.values()), mdd, n


def fit_pred(Xtr, ytr, Xs, seed=0):
    from sklearn.ensemble import HistGradientBoostingClassifier
    if ytr.sum() < 20:
        return [np.full(len(x), np.nan) for x in Xs]
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=200,
                                       l2_regularization=1.0, early_stopping=True, validation_fraction=0.15,
                                       random_state=seed)
    m.fit(Xtr, ytr)
    return [m.predict_proba(x)[:, 1] for x in Xs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--nulls", type=int, default=3)
    args = ap.parse_args()
    t_start = time.time()
    coins, rows, n_all = load(args.data)
    print(f"== {n_all:,} rekaman dibaca, {len(coins):,} koin valid, {len(rows):,} baris (koin x umur). "
          f"{time.time() - t_start:.0f} dtk")
    if not rows:
        return
    hf = history_feats(coins, rows)
    print(f"   fitur riwayat selesai, {time.time() - t_start:.0f} dtk")
    t_all = np.array([coins[r[0]][0] for r in rows])
    lo_t, hi_t = t_all.min(), t_all.max()
    cut1 = np.quantile(t_all, 0.5)
    cut2 = np.quantile(t_all, 0.7)
    f = lambda t: time.strftime('%d/%m %H:%M', time.gmtime(t))  # noqa: E731
    print(f"   Data {f(lo_t)} - {f(hi_t)} UTC. LATIH < {f(cut1)} <= VALIDASI < {f(cut2)} <= UJI")
    print(f"   Biaya {C1:.2%} per sisi, jeda 3-9 dtk, stop/TP isi = min(level, harga setelah jeda).")

    std_c = [x for x in coins if x[5]]
    p0 = np.array([x[4] for x in std_c])
    print(f"\n== Koin kurva standar dari LAHIR ({len(std_c):,}): puncak >=2x {np.mean(p0 >= 2):.1%}, "
          f">=5x {np.mean(p0 >= 5):.2%}, >=10x {np.mean(p0 >= 10):.2%}, >=50x {np.mean(p0 >= 50):.3%}")

    results = {}   # (a) -> dict
    for a in AGES:
        idx = [j for j, r in enumerate(rows) if r[1] == a]
        if len(idx) < 5000:
            print(f"\n== umur {a}: terlalu sedikit ({len(idx)})")
            continue
        X = np.array([np.concatenate([rows[j][3], hf[j]]) for j in idx], dtype=float)
        t = t_all[idx]
        tin = np.array([rows[j][2] for j in idx])
        pk = np.array([rows[j][4] for j in idx])
        pk0 = np.array([rows[j][5] for j in idx])
        G = np.array([rows[j][6] for j in idx]) * (1 - C1) ** 2
        TX = np.array([rows[j][7] for j in idx], dtype=float) + np.array([rows[j][8] for j in idx])[:, None]
        TR, VA, TE = t < cut1, (t >= cut1) & (t < cut2), t >= cut2
        print(f"\n\n######## UMUR {a} DTK: {len(idx):,} koin (latih {TR.sum():,} / val {VA.sum():,} / uji {TE.sum():,})")
        print(f"  Puncak setelah beli: >=2x {np.mean(pk >= 2):.1%}, >=5x {np.mean(pk >= 5):.2%}, "
              f">=10x {np.mean(pk >= 10):.2%}")
        print("  Beli SEMUA (patokan), periode UJI:")
        for e, nm in enumerate(EXITS):
            print(f"    {nm:9s} {desc(G[TE, e])}")

        # ---- ciri koin >=10x vs lainnya (dari harga beli), latih vs uji
        for lab, y in (("puncak >=10x dari harga beli", pk >= 10), ("puncak >=10x dari LAHIR", pk0 >= 10)):
            if y[TR].sum() < 30:
                continue
            print(f"\n  CIRI '{lab}' (latih {int(y[TR].sum())} koin vs {int((~y[TR]).sum()):,}; AUC latih -> uji):")
            lines = []
            for k, nm in enumerate(FEATS):
                x = X[:, k]
                a1 = pm.auc(x[TR], y[TR])
                a2 = pm.auc(x[TE], y[TE])
                if math.isnan(a1):
                    continue
                m1 = np.nanmedian(x[TR & y]) if (TR & y).any() else math.nan
                m0 = np.nanmedian(x[TR & ~y])
                lines.append((abs(a1 - 0.5), nm, a1, a2, m1, m0))
            lines.sort(reverse=True)
            for _, nm, a1, a2, m1, m0 in lines[:14]:
                print(f"    {pm.NAMA.get(nm, nm):32s} AUC {a1:.3f} -> {a2:.3f}   median terbang {m1:.4g} vs lain {m0:.4g}")

        # ---- model
        res = {}
        for lab, y in (("y5", pk >= 5), ("y10", pk >= 10)):
            pv, pt = fit_pred(X[TR], y[TR], [X[VA], X[TE]])
            if np.isnan(pv).all():
                continue
            av, at = pm.auc(pv, y[VA]), pm.auc(pt, y[TE])
            base = y[TE].mean()
            s = f"  MODEL {lab}: AUC val {av:.3f}, uji {at:.3f}; basis uji {base:.2%}"
            for qq in (0.01, 0.05):
                thr = np.quantile(pv, 1 - qq)
                sel = pt >= thr
                n, w = int(sel.sum()), int(y[TE][sel].sum())
                l1, h1 = wil(w, n)
                s += f" | top{qq:.0%}: {w}/{n} = {w / n if n else 0:.1%} [{l1:.1%}-{h1:.1%}]"
            print(s)
            # desil skor di uji
            qs = np.quantile(pt, np.linspace(0, 1, 11))
            print(f"    desil skor uji (rata HOLD / TR3 / TP5SL50, % >=5x):")
            for dd in range(9, -1, -1):
                m = (pt >= qs[dd]) & (pt <= qs[dd + 1]) if dd < 9 else pt >= qs[9]
                print(f"      D{dd + 1:2d}: n={m.sum():6,} {G[TE][m, 0].mean():.3f} / {G[TE][m, 5].mean():.3f} / "
                      f"{G[TE][m, 3].mean():.3f}  >=5x {np.mean(pk[TE][m] >= 5):.2%}")
            res[lab] = (pv, pt)
        nulls = []
        for ns in range(args.nulls):
            ys = (pk >= 5)[TR].copy()
            np.random.default_rng(100 + ns).shuffle(ys)
            pv, pt = fit_pred(X[TR], ys, [X[VA], X[TE]], seed=ns)
            nulls.append((pv, pt))
        results[a] = dict(res=res, nulls=nulls, G=G, TX=TX, tin=tin, VA=VA, TE=TE, pk=pk)
        print(f"  ({time.time() - t_start:.0f} dtk)")

    # ---- pilih di validasi, uji sekali
    def grid(get):
        out = []
        for a, R in results.items():
            for lab, (pv, pt) in get(R):
                for qq in TOPQ:
                    thr = np.quantile(pv, 1 - qq)
                    sv, st = pv >= thr, pt >= thr
                    for e, nm in enumerate(EXITS):
                        gv = R["G"][R["VA"], e][sv]
                        if len(gv) < 30:
                            continue
                        out.append((gv.mean(), a, lab, qq, nm, e, thr, st))
        out.sort(key=lambda x: -x[0])
        return out

    print("\n\n######## PILIH DI VALIDASI -> UJI SEKALI")
    g = grid(lambda R: R["res"].items())
    print(f"  {len(g)} kombinasi dengan n val >=30; untung di val: {sum(x[0] > 1 for x in g)}")
    print(f"  Untung di val DAN uji (info, bukan dasar pilih): "
          f"{sum(1 for x in g if x[0] > 1 and results[x[1]]['G'][results[x[1]]['TE'], x[5]][x[7]].mean() > 1)}")
    passed = 0
    for rank, (mv, a, lab, qq, nm, e, thr, st) in enumerate(g[:5]):
        R = results[a]
        gt = R["G"][R["TE"], e][st]
        tag = "UTAMA" if rank == 0 else f"cadangan {rank}"
        print(f"\n  [{tag}] umur {a}, model {lab}, top {qq:.1%}, exit {nm}: val rata {mv:.3f}x")
        print(f"     UJI: {desc(gt)}")
        ok = len(gt) >= 30 and gt.mean() > 1 and np.sort(gt)[:-1].mean() > 1
        passed += ok and rank == 0
        print(f"     -> {'LULUS' if ok else 'GAGAL'}")
        tr = sorted(zip(R["tin"][R["TE"]][st], R["TX"][R["TE"], e][st], gt))
        for cap in (100, 200, 1000):
            eq, mdd, n = bank(tr, cap)
            print(f"     ${cap} -> ${eq:,.2f} ({n} trade, MDD {mdd:.0%})")
    # null
    print("\n  NULL (label latih diacak, proses sama):")
    for ns in range(args.nulls):
        gn = grid(lambda R: [("y5", R["nulls"][ns])] if len(R["nulls"]) > ns else [])
        if not gn:
            continue
        mv, a, lab, qq, nm, e, thr, st = gn[0]
        R = results[a]
        gt = R["G"][R["TE"], e][st]
        print(f"    null {ns + 1}: val terbaik {mv:.3f}x (umur {a} top {qq:.1%} {nm}) -> uji {desc(gt)}; "
              f"untung di val {sum(x[0] > 1 for x in gn)}/{len(gn)}")
    print(f"\n== VONIS: {'ADA kandidat lulus (wajib uji maju)' if passed else 'TIDAK ADA yang lulus'}. "
          f"Data hanya {(hi_t - lo_t) / 86400:.1f} hari (rekaman memescan disimpan 14 hari); Jan-Okt 2026 tidak bisa diuji.")
    print(f"   selesai {time.time() - t_start:.0f} dtk")


if __name__ == "__main__":
    main()

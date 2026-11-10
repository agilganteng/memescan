"""Modul filter baru calon Bom v2. PAPER.

Praregistrasi: riset/spec-filter-baru-2026-11-10.md
sha256 e2cd46c009314e62ff9f77708ad3246913383a9e80617ec751200581fc0ec666

Ditulis sebelum hasil:
- SOLUSD = 86 tetap. mcap_usd = mcap_sol * 86. Bukan harga SOL tiap koin.
- Anti-honeypot (Jupiter, mint, freeze, Token-2022) TIDAK diuji. Field itu tidak ada di rekaman kurva.
- Proksi fresh, sebelum jalan: unique_buyers>=20 DAN holders<=8 DAN unique_buyers/max(holders,1)>=3.
- Bundle: tolak jika bundle>=5. Di perekam, bundle = jumlah pembeli non-dev pada 1 detik pertama, bukan persen.
- Dev sudah jual: dev_sold_any, atau dev_pct turun ke <=60% snapshot sebelumnya. Bukan angka 40% (tidak terekam).
- Pita likuiditas $25k hanya diagnostik. Di kurva, likuiditas hampir selalu di bawah itu.
- Picker: peringkat rata A, n_A>=30, rata A>1, maksimal 5. B diuji sekali pada kelima itu.
- C tidak memilih. t0 sesudah 10 Nov 07:17 UTC hanya konfirmasi, dan hanya jika cache lebih baru memuatnya.
- WR<55% dibekukan dari koin t0<potongan A. Tidak masuk peringkat A (angka A-nya bocor).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import amplify_b as ab  # noqa: E402
import grid_luas as gl  # noqa: E402

SOLUSD = 86.0
CUT1, CUT2, CLEAN = ab.CUT1, ab.CUT2, ab.CLEAN_AFTER
NMIN = 30
AGES = ((120, 120, False), (300, 300, False), (600, 600, False), (1800, 600, True))
BANDS = (("<10k", 0.0, 10_000.0), ("10-30k", 10_000.0, 30_000.0),
         ("30-60k", 30_000.0, 60_000.0), ("60-100k", 60_000.0, 100_000.0))
BAND_OF = {n: (lo, hi) for n, lo, hi in BANDS}
DELAYS = ("3-8", "1", "0.4")
EXITS = (
    dict(name="TP1.5 SL-8% 120s", kind=0, tp=1.5, sl=0.92, T=120.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="TP2 SL-8% 120s", kind=0, tp=2.0, sl=0.92, T=120.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="TP1.5 SL-30% 600s", kind=0, tp=1.5, sl=0.70, T=600.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="TP2 SL-30% 600s", kind=0, tp=2.0, sl=0.70, T=600.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="TP1.5 SL-50% 120s", kind=0, tp=1.5, sl=0.50, T=120.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="TP2 SL-50% 120s", kind=0, tp=2.0, sl=0.50, T=120.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="TP2 SL-30% 1800s", kind=0, tp=2.0, sl=0.70, T=1800.0, arm=0.0, trail=0.0, tp2=0.0, dev=False),
    dict(name="ikut dev jual atau SL-30% 1800s", kind=3, tp=1e9, sl=0.70, T=1800.0, arm=0.0, trail=0.0, tp2=0.0, dev=True),
)
PREV = {120: 60, 300: 180, 600: 300}
SNAP_AGES = (10, 20, 30, 45, 60, 90, 120, 180, 300, 600)


def load_whales(path):
    with open(path, newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
    rows = []
    for r in csv.DictReader(lines):
        pref = (r.get("rec_prefix10") or r["wallet"][:10]).strip()
        rows.append((r["wallet"].strip(), (r.get("label") or "").strip(), pref))
    from collections import Counter
    dup = sorted(k for k, v in Counter(p for _w, _l, p in rows).items() if v > 1)
    return rows, {p for _w, _l, p in rows}, dup


def period_of(t):
    if t > CLEAN:
        return 3
    if t < CUT1:
        return 0
    if t < CUT2:
        return 1
    return 2


def g(sn, name):
    return float(sn[gl.FI[name]])


def fresh_flag(sn):
    ub, ho = g(sn, "unique_buyers"), g(sn, "holders")
    return 1.0 if (ub >= 20.0 and ho <= 8.0 and ub / max(ho, 1.0) >= 3.0) else 0.0


def sold_flag(c, sn, snap, t_cut):
    if g(sn, "dev_sold_any") >= 1.0:
        return 1.0
    prev = PREV.get(snap)
    if prev is not None and prev in c.snaps:
        old = g(c.snaps[prev], "dev_pct")
        if old >= 0.02 and g(sn, "dev_pct") <= 0.6 * old:
            return 1.0
    limit = min(float(t_cut), 300.0)
    for ag, w, b, s in c.w:
        if (not b) and w == c.dev and s > 0 and ag <= limit:
            return 1.0
    return 0.0


def whale_n(c, prefixes, t_cut):
    limit = min(float(t_cut), 300.0)
    hit = set()
    for ag, w, b, _s in c.w:
        if b and ag <= limit and w in prefixes:
            hit.add(w)
    return float(len(hit))


def feat_of_snap(c, snap, prefixes, t_cut):
    sn = c.snaps.get(snap)
    if sn is None:
        return None
    return (
        float(sn[1]) * SOLUSD,
        g(sn, "top10"),
        g(sn, "dev_pct"),
        sold_flag(c, sn, snap, t_cut),
        g(sn, "creator_prev_rugs"),
        g(sn, "bundle"),
        g(sn, "growth"),
        g(sn, "drawdown"),
        fresh_flag(sn),
        whale_n(c, prefixes, t_cut),
        g(sn, "liq_sol") * SOLUSD,
    )


def dev_fol(c, te):
    for ag, w, b, s in c.w:
        if (not b) and w == c.dev and s > 0 and ag > te:
            return float(ag)
    return -1.0


def snap_before(c, te):
    best = None
    for a in SNAP_AGES:
        if a <= te and a in c.snaps:
            best = a
    return best


def p1_ok(f):
    return (f[1] <= 0.30 and f[2] <= 0.05 and f[3] == 0.0 and f[4] < 1.0 and f[5] < 5.0
            and f[6] < 2.0 and f[7] < 0.40 and f[8] == 0.0)


def build_block(coins, paths, prefixes, decision, snap, stale, delay):
    idx, feats, te_a, lx_a = [], [], [], []
    for i, c in enumerate(coins):
        if snap not in c.snaps or c.end <= decision + 0.4:
            continue
        f = feat_of_snap(c, snap, prefixes, decision)
        if f is None:
            continue
        lx = ab.lag_of(3, c.full_i, decision, delay)
        te = decision + lx
        idx.append(i)
        feats.append(f)
        te_a.append(te)
        lx_a.append(lx)
    if len(idx) < 30:
        F = np.asarray(feats, np.float64) if feats else np.zeros((0, 11), np.float64)
        return dict(idx=np.asarray(idx, np.int32), F=F, decision=decision, snap=snap, delay=delay,
                    stale=stale, short=True)
    n, e = len(idx), len(EXITS)
    X = np.full((n, e), np.nan, np.float64)
    tout = np.full((n, e), np.nan, np.float64)
    per = np.empty(n, np.int8)
    arrays = gl.exits_arrays(list(EXITS))
    for j, i in enumerate(idx):
        c, pa = coins[i], paths[i]
        te, lx = te_a[j], lx_a[j]
        per[j] = period_of(c.t0)
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(pa, te)
        if p_in <= 0:
            continue
        p1, p2, split, to = gl.sim_one(pa, te, lx, p_in, arrays, dev_fol(c, te))
        X[j] = gl.apply_costs(p_in, p1, p2, split)
        tout[j] = to
        if j and j % 20000 == 0:
            print(f"  sim D{decision} {delay} {j}/{n}", flush=True)
    return dict(idx=np.asarray(idx, np.int32), F=np.asarray(feats, np.float64), X=X, per=per,
                te=np.asarray(te_a, np.float64), lx=np.asarray(lx_a, np.float64), tout=tout,
                decision=decision, snap=snap, delay=delay, stale=stale,
                whale_stale=decision > 300)


def pack_masks(F):
    p0 = np.ones(F.shape[0], dtype=bool)
    p1 = ((F[:, 1] <= 0.30) & (F[:, 2] <= 0.05) & (F[:, 3] == 0) & (F[:, 4] < 1)
          & (F[:, 5] < 5) & (F[:, 6] < 2) & (F[:, 7] < 0.40) & (F[:, 8] == 0))
    p2 = ((F[:, 1] <= 0.35) & (F[:, 2] <= 0.10) & (F[:, 3] == 0) & (F[:, 4] < 1)
          & (F[:, 5] < 5) & (F[:, 6] < 2) & (F[:, 7] < 0.50))
    return (("P0", p0), ("P1", p1), ("P2", p2))


def band_masks(F):
    mcap = F[:, 0]
    return tuple((name, (mcap >= lo) & (mcap < hi)) for name, lo, hi in BANDS)


def mask_list(F):
    out = []
    bands, packs = band_masks(F), pack_masks(F)
    for bname, bm in bands:
        for pname, pm in packs:
            out.append((dict(family="G3", band=bname, pack=pname, kmin=0), bm & pm))
    p1 = dict(packs)["P1"]
    for kmin in (1, 2, 3):
        out.append((dict(family="G6-confirm", band=f"whale>={kmin}", pack="P1", kmin=kmin), p1 & (F[:, 9] >= kmin)))
    return out


def pass_count(M, X, per):
    """M (S, n) bool. Berapa pasangan (mask, exit) yang lolos A dan B."""
    if M.size == 0:
        return 0
    finite = np.isfinite(X)
    a = (per == 0)[:, None] & finite
    b = (per == 1)[:, None] & finite
    mf = M.astype(np.float64)
    nA = mf @ a.astype(np.float64)
    nB = mf @ b.astype(np.float64)
    Xa = np.where(a, X, 0.0)
    Xb = np.where(b, X, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mA = (mf @ Xa) / np.maximum(nA, 1.0)
        mB = (mf @ Xb) / np.maximum(nB, 1.0)
    cand = (nA >= NMIN) & (mA > 1.0) & (nB >= NMIN) & (mB > 1.0)
    if not np.any(cand):
        return 0
    cnt = 0
    ss, ks = np.nonzero(cand)
    for s, k in zip(ss.tolist(), ks.tolist()):
        xs = X[M[s] & b[:, k], k]
        if xs.size >= 2 and gl.nobest_of(xs) > 1.0:
            cnt += 1
    return cnt


def records_of(block):
    labeled = mask_list(block["F"])
    M = np.vstack([m for _lab, m in labeled])
    finite = np.isfinite(block["X"])
    a = (block["per"] == 0)[:, None] & finite
    b = (block["per"] == 1)[:, None] & finite
    mf = M.astype(np.float64)
    nA = mf @ a.astype(np.float64)
    nB = mf @ b.astype(np.float64)
    Xa = np.where(a, block["X"], 0.0)
    Xb = np.where(b, block["X"], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        mA = (mf @ Xa) / np.maximum(nA, 1.0)
        mB = (mf @ Xb) / np.maximum(nB, 1.0)
    recs = []
    for s, (lab, _m) in enumerate(labeled):
        for k, ex in enumerate(EXITS):
            na, nb = int(nA[s, k]), int(nB[s, k])
            recs.append(dict(
                family=lab["family"], band=lab["band"], pack=lab["pack"], kmin=lab["kmin"],
                bi=None, delay=block["delay"], age=block["decision"], snap=block["snap"],
                stale=block["stale"], whale_stale=block["whale_stale"], exit=ex["name"], ek=k,
                nA=na, meanA=float(mA[s, k]) if na else None,
                nB=nb, meanB=float(mB[s, k]) if nb else None,
                nobB=None, rankable=True,
            ))
    return recs, M


def fill_nob(block, recs, M, which):
    per_b = block["per"] == 1
    for s, k in which:
        m = M[s] & per_b & np.isfinite(block["X"][:, k])
        xs = block["X"][m, k]
        recs[s * len(EXITS) + k]["nobB"] = float(gl.nobest_of(xs)) if xs.size >= 2 else None


def stats_of(xs):
    xs = np.asarray(xs, np.float64)
    xs = xs[np.isfinite(xs)]
    n = int(xs.size)
    if n == 0:
        return dict(n=0, mean=None, median=None, win=None, wilson=[0.0, 0.0], nobest=None, pf=None, best=None)
    wins = int(np.sum(xs > 1.0))
    lo, hi = gl.wilson(wins, n)
    gains = float((xs[xs > 1.0] - 1.0).sum())
    losses = float((1.0 - xs[xs < 1.0]).sum())
    pf = (gains / losses) if losses > 0 else (None if gains == 0 else float("inf"))
    return dict(n=n, mean=float(xs.mean()), median=float(np.median(xs)), win=wins / n,
                wilson=[float(lo), float(hi)], nobest=float(gl.nobest_of(xs)) if n >= 2 else None,
                pf=pf, best=float(xs.max()))


def rows_from_block(block, coins, mask, k):
    m = mask & np.isfinite(block["X"][:, k])
    rows = []
    for j in np.flatnonzero(m):
        i = int(block["idx"][j])
        c = coins[i]
        rows.append(dict(i=i, t=float(c.t0 + block["te"][j]), tout=float(c.t0 + block["tout"][j, k]),
                         x=float(block["X"][j, k]), per=int(block["per"][j]),
                         te=float(block["te"][j]), lx=float(block["lx"][j])))
    return rows


def books_of(rows):
    out = {}
    for cap, frac, mp, key in (
        (200.0, 0.08, 1, "8% m1"), (200.0, 0.08, 5, "8% m5"),
        (200.0, 0.10, 1, "10% m1"), (200.0, 0.10, 5, "10% m5"),
        (100.0, 0.08, 1, "100 8% m1"), (100.0, 0.10, 1, "100 10% m1"),
        (1000.0, 0.08, 1, "1000 8% m1"), (1000.0, 0.10, 1, "1000 10% m1"),
    ):
        out[key] = ab.sim_book(rows, frac, mp, cap) if rows else None
    return out


def slices_of(rows):
    st = {}
    for p, lab in ((0, "A"), (1, "B"), (2, "C"), (3, "segar")):
        sub = [r for r in rows if r["per"] == p]
        s = stats_of([r["x"] for r in sub])
        s["books"] = books_of(sub)
        st[lab] = s
    return st


def mask_for(block, rec):
    F = block["F"]
    if rec["family"] == "G3":
        lo, hi = BAND_OF[rec["band"]]
        m = (F[:, 0] >= lo) & (F[:, 0] < hi)
        return m & dict(pack_masks(F))[rec["pack"]]
    return dict(pack_masks(F))["P1"] & (F[:, 9] >= rec["kmin"])


def vote_components(F, band, kmin):
    rug = (F[:, 1] <= 0.30) & (F[:, 2] <= 0.05) & (F[:, 3] == 0) & (F[:, 4] < 1) & (F[:, 5] < 5)
    latar = (F[:, 8] == 0) & (F[:, 3] == 0)
    if band in BAND_OF:
        lo, hi = BAND_OF[band]
        data = (F[:, 0] >= lo) & (F[:, 0] < hi) & (F[:, 6] < 2) & (F[:, 7] < 0.40)
    else:
        data = (F[:, 6] < 2) & (F[:, 7] < 0.40)
    whale = F[:, 9] >= max(int(kmin), 1)
    return rug, latar, data, whale


def vote_mask(F, band, kmin, mode):
    rug, latar, data, whale = vote_components(F, band, kmin)
    acc = rug.astype(np.int8) + latar.astype(np.int8) + data.astype(np.int8) + whale.astype(np.int8)
    if mode == "all4":
        return rug & latar & data & whale
    if mode == "ge3":
        return acc >= 3
    if mode == "rug+data":
        return rug & data
    if mode == "rug+latar":
        return rug & latar
    if mode == "rug+whale":
        return rug & whale
    raise KeyError(mode)


def sim_vote(coins, paths, block, mask, wait, xtol):
    rows = []
    decision = block["decision"]
    for j in np.flatnonzero(mask):
        i = int(block["idx"][j])
        c, pa = coins[i], paths[i]
        p0 = gl.price_at_py(pa, decision)
        p1 = gl.price_at_py(pa, decision + wait)
        if p0 <= 0 or p1 <= 0:
            continue
        if xtol is not None and abs(p1 / p0 - 1.0) > xtol:
            continue
        te = decision + wait + 1.0
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(pa, te)
        if p_in <= 0:
            continue
        x, to = ab.one_x(pa, te, 1.0, p_in, ab.BOM_EXIT)
        rows.append(dict(i=i, t=float(c.t0 + te), tout=float(c.t0 + to), x=float(x),
                         per=period_of(c.t0), te=float(te), lx=1.0))
    return rows


def wr_book(coins, prefixes):
    acc = {p: [0, 0] for p in prefixes}
    for c in coins:
        if c.t0 >= CUT1:
            continue
        per = {}
        for ag, w, b, s in c.w:
            if w not in prefixes:
                continue
            d = per.setdefault(w, [0.0, 0.0])
            if b:
                d[0] += s
            else:
                d[1] += s
        for w, (bs, ss) in per.items():
            if bs > 0 and ss > 0:
                acc[w][1] += 1
                acc[w][0] += int(ss > bs)
    return {w: ((wins / n) if n else None, n) for w, (wins, n) in acc.items()}


def wr_fail(book, w):
    wr, n = book.get(w, (None, 0))
    return bool(n >= 5 and wr is not None and wr < 0.55)


def build_copy(coins, paths, prefixes, book):
    """Copy saat beli whale pertama + P1 di snapshot <= waktu masuk. WR tidak ikut peringkat."""
    by = {d: [] for d in DELAYS}
    for i, c in enumerate(coins):
        hit = None
        for ag, w, b, _s in c.w:
            if b and w in prefixes:
                hit = (ag, w)
                break
        if hit is None:
            continue
        ag, w = hit
        for delay in DELAYS:
            lx = ab.lag_of(5, c.full_i, int(ag), delay)
            te = ag + lx
            if te >= c.end - 1:
                continue
            snap = snap_before(c, te)
            if snap is None:
                continue
            f = feat_of_snap(c, snap, prefixes, te)
            if f is None or not p1_ok(f):
                continue
            pa = paths[i]
            p_in = gl.price_at_py(pa, te)
            if p_in <= 0:
                continue
            p1, p2, split, to = gl.sim_one(pa, te, lx, p_in, gl.exits_arrays(list(EXITS)), dev_fol(c, te))
            xs = gl.apply_costs(p_in, p1, p2, split)
            by[delay].append((int(i), period_of(c.t0), float(te), float(lx), float(c.t0), xs, np.asarray(to, np.float64), wr_fail(book, w)))
        if i and i % 20000 == 0:
            print(f"  copy {i}", flush=True)
    cfgs, mats = [], {}
    for delay, items in by.items():
        if not items:
            mats[delay] = None
            continue
        n, e = len(items), len(EXITS)
        X = np.vstack([it[5] for it in items])
        per = np.array([it[1] for it in items], np.int8)
        fail = np.array([it[7] for it in items], dtype=bool)
        mats[delay] = (X, per, ~fail)
        for mode, mask in (("semua", np.ones(n, dtype=bool)), ("WR", ~fail)):
            for k, ex in enumerate(EXITS):
                xa = X[mask & (per == 0), k]
                xb = X[mask & (per == 1), k]
                sa, sb = stats_of(xa), stats_of(xb)
                cfgs.append(dict(
                    family="G6-copy", band=mode, pack="P1", kmin=0, delay=delay, age=0, snap=0,
                    stale=False, whale_stale=False, exit=ex["name"], ek=k, bi=None,
                    nA=sa["n"], meanA=sa["mean"], nB=sb["n"], meanB=sb["mean"], nobB=sb["nobest"],
                    rankable=mode == "semua", items=items, mode_mask=mask,
                ))
    return cfgs, mats


def copy_pass(mats):
    cnt = 0
    for delay in DELAYS:
        got = mats.get(delay)
        if not got:
            continue
        X, per, _keep = got
        M = np.ones((1, X.shape[0]), dtype=bool)
        cnt += pass_count(M, X, per)
    return cnt


def g5_rows(coins, paths):
    ex = dict(name="TP2 SL-50% 120s", kind=0, tp=2.0, sl=0.50, T=120.0, arm=0.0, trail=0.0, tp2=0.0)
    thr = (30 + 0.92 * 85) ** 2 / gl.K_CURVE
    rows = []
    for i, c in enumerate(coins):
        pa = paths[i]
        hi = pa["bar_hi"]
        if hi.size == 0 or float(hi.max()) < thr:
            continue
        j = int(np.argmax(hi >= thr))
        if hi[j] < thr:
            continue
        th = float(pa["bar_t"][j])
        lx = ab.lag_of(4, c.full_i, 92, "3-8")
        te = th + lx
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(pa, te)
        if p_in <= 0:
            continue
        x, to = ab.one_x(pa, te, lx, p_in, ex)
        rows.append(dict(i=i, t=c.t0 + te, tout=c.t0 + to, x=x, per=period_of(c.t0), te=te, lx=lx))
    return rows


def rule_hour():
    return dict(ab.RULE_B, name="(b)+jam 12-16 UTC", delay="0.4",
                conds=list(ab.RULE_B["conds"]) + [(11, "<=", 0.35), (15, ">=", 12.0), (15, "<", 16.0)],
                exit=dict(kind=0, tp=5.0, sl=0.7, T=1800.0, arm=0.0, trail=0.0, tp2=0.0, w1=1.0, w2=0.0,
                          name="TP5 SL0.7 1800s"))


def fmt_x(x):
    if x is None or (isinstance(x, float) and (x != x or x == float("inf"))):
        return "—" if x != float("inf") else "tak-hingga"
    return f"{float(x):.3f}".replace(".", ",") + "x"


def fmt_p(x):
    if x is None:
        return "—"
    return f"{100 * float(x):.1f}%".replace(".", ",")


def fmt_money(bk):
    if not bk:
        return "—"
    return f"${bk['end']:.0f} / DD {fmt_p(bk['max_dd'])}"


def cell(st):
    if not st or not st.get("n"):
        return "0 | — | — | — | — | — | — | —"
    w = st["wilson"]
    b = st.get("books") or {}
    return (f"{st['n']} | {fmt_x(st['mean'])} | {fmt_p(st['win'])} [{fmt_p(w[0])}–{fmt_p(w[1])}] | "
            f"{fmt_x(st['nobest'])} | {fmt_money(b.get('8% m1'))} | {fmt_money(b.get('8% m5'))} | "
            f"{fmt_money(b.get('10% m1'))} | {fmt_money(b.get('10% m5'))}")


def add_slice_rows(L, name, st):
    L.append(f"| {name} | | | | | | | | | |")
    for lab in ("A", "B", "C", "segar"):
        L.append(f"| | {lab} | {cell(st.get(lab) or {})} |")


def describe(rec):
    stale = " fitur basi 10 menit" if rec.get("stale") else ""
    wstale = " whale hanya 5 menit pertama" if rec.get("whale_stale") else ""
    return (f"{rec['family']} umur {rec['age']}s snap {rec['snap']}{stale}{wstale} "
            f"jeda {rec['delay']} {rec['band']} paket {rec['pack']} jual {rec['exit']}")


def agent_of(rec):
    if rec["family"].startswith("G6"):
        return "whale", "konfirmasi atau copy prefix daftar publik"
    if rec["pack"] == "P0":
        return "data", "pita mcap pada umur keputusan"
    return "data", "pita mcap plus gerbang rug/latar (top10, dev, bundle, fresh, growth, drawdown)"


VOTE_MODES = ("all4", "ge3", "rug+data", "rug+latar", "rug+whale")
VOTE_WAIT = (1.0, 2.0, 3.0)
VOTE_XTOL = ((0.10, "10%"), (0.15, "15%"), (0.25, "25%"), (None, "tanpa batas"))
MODE_LAB = {
    "all4": "4/4 narasi-SKIP (=5/5 jika narasi diasumsikan ACC)",
    "ge3": "≥3/4 narasi-ACC",
    "rug+data": "rug+data, bukan 4/5",
    "rug+latar": "rug+latar, bukan 4/5",
    "rug+whale": "rug+whale, bukan 4/5",
}


def vote_settings():
    return [(w, xt, lab) for w in VOTE_WAIT for xt, lab in VOTE_XTOL]


def vote_labeled(F):
    out = []
    for bname, _lo, _hi in BANDS:
        for mode in VOTE_MODES:
            out.append(((bname, mode), vote_mask(F, bname, 1, mode)))
    return out


def precompute_vote(coins, paths, block):
    """Hasil masuk suara. Jeda eksekusi 1 dtk sesudah tunggu, jual jaga Bom. Bukan jeda 3–8."""
    settings = vote_settings()
    n, ncol = len(block["idx"]), len(settings)
    X = np.full((n, ncol), np.nan, np.float64)
    tout = np.full((n, ncol), np.nan, np.float64)
    te = np.full((n, ncol), np.nan, np.float64)
    decision = float(block["decision"])
    for j, ii in enumerate(block["idx"]):
        i = int(ii)
        c, pa = coins[i], paths[i]
        p0 = gl.price_at_py(pa, decision)
        if p0 <= 0:
            continue
        for col, (wait, xtol, _lab) in enumerate(settings):
            p1 = gl.price_at_py(pa, decision + wait)
            if p1 <= 0:
                continue
            if xtol is not None and abs(p1 / p0 - 1.0) > xtol:
                continue
            t_e = decision + wait + 1.0
            if t_e >= c.end - 1:
                continue
            p_in = gl.price_at_py(pa, t_e)
            if p_in <= 0:
                continue
            x, to = ab.one_x(pa, t_e, 1.0, p_in, ab.BOM_EXIT)
            X[j, col] = x
            tout[j, col] = to
            te[j, col] = t_e
        if j and j % 20000 == 0:
            print(f"  suara D{int(decision)} {j}/{n}", flush=True)
    return settings, X, tout, te


def rows_vote(block, coins, mask, col, te, tout, X):
    rows = []
    m = mask & np.isfinite(X[:, col])
    for j in np.flatnonzero(m):
        i = int(block["idx"][j])
        c = coins[i]
        rows.append(dict(i=i, t=float(c.t0 + te[j, col]), tout=float(c.t0 + tout[j, col]),
                         x=float(X[j, col]), per=int(block["per"][j]), te=float(te[j, col]), lx=1.0))
    return rows


def run_locked_votes(coins, paths, blocks, nulls_n):
    """Paket suara yang dikunci, pada setiap umur yang datanya cukup. Bukan picker."""
    rows_out = []
    real = 0
    k = 0
    nulls = [0] * nulls_n
    rng = np.random.default_rng(200)
    chosen = [b for b in blocks if b["delay"] == "3-8" and not b.get("short")]
    for block in chosen:
        print(f"suara terkunci umur {block['decision']}", flush=True)
        settings, X, tout, te = precompute_vote(coins, paths, block)
        labeled = vote_labeled(block["F"])
        M = np.vstack([m for _lab, m in labeled])
        k += M.shape[0] * X.shape[1]
        got = pass_count(M, X, block["per"])
        real += got
        per = block["per"]
        for s in range(nulls_n):
            perm = rng.permutation(block["F"].shape[0])
            Ms = np.vstack([m for _lab, m in vote_labeled(block["F"][perm])])
            nulls[s] += pass_count(Ms, X, per)
        seen_ok = 0
        for (band, mode), mask in labeled:
            for col, (wait, xtol, xlab) in enumerate(settings):
                finite = np.isfinite(X[:, col])
                sa = stats_of(X[mask & (per == 0) & finite, col])
                sb = stats_of(X[mask & (per == 1) & finite, col])
                ok = bool(sa["n"] >= NMIN and (sa["mean"] or 0) > 1 and sb["n"] >= NMIN
                          and (sb["mean"] or 0) > 1 and (sb["nobest"] or 0) > 1)
                seen_ok += int(ok)
                compare = (band == "10-30k" and mode in ("all4", "ge3") and wait == 2.0
                           and xlab in ("15%", "tanpa batas"))
                st = None
                p = None
                if compare or ok:
                    traded = rows_vote(block, coins, mask, col, te, tout, X)
                    st = slices_of(traded)
                    if ok:
                        xs = np.array([r["x"] for r in traded if r["per"] == 1], np.float64)
                        if xs.size >= 5:
                            p, B = gl.boot_p(xs, B=200000, seed=1)
                            if p == 0:
                                p = 1.0 / B
                name = (f"suara {MODE_LAB[mode]}, umur {block['decision']}s, mcap {band}, "
                        f"tunggu {wait:.0f}s, pita {xlab}")
                rows_out.append(dict(name=name, age=block["decision"], band=band, mode=mode, wait=wait,
                                     xlab=xlab, nA=sa["n"], meanA=sa["mean"], nB=sb["n"], meanB=sb["mean"],
                                     nobB=sb["nobest"], ok=ok, compare=compare, st=st, p=p,
                                     stale=block["stale"]))
        if seen_ok != got:
            print(f"  peringatan hitung suara {seen_ok} vs {got}", flush=True)
            real += seen_ok - got
    return dict(rows=rows_out, real=real, nulls=nulls, k=k)


def self_test(wallet_path):
    rows, prefs, dups = load_whales(wallet_path)
    assert len(rows) == 99, len(rows)
    assert len(prefs) == 99, len(prefs)
    assert dups == []
    assert all(len(p) == 10 for _w, _l, p in rows)
    X = np.ones((100, 2), np.float64)
    X[:50] = 1.3
    X[50:] = 1.2
    per = np.array([0] * 50 + [1] * 50, np.int8)
    assert pass_count(np.ones((1, 100), dtype=bool), X, per) == 2
    X[50:, 1] = 0.5
    assert pass_count(np.ones((1, 100), dtype=bool), X, per) == 1
    block = dict(per=np.array([0, 1, 1], np.int8), X=np.array([[1.2, 0.8], [1.1, 0.7], [0.9, 1.4]], np.float64))
    recs = [dict(nobB=None) for _ in range(2)]
    fill_nob(block, recs, np.ones((1, 3), dtype=bool), [(0, 0), (0, 1)])
    assert recs[0]["nobB"] is not None and recs[1]["nobB"] is not None
    F = np.zeros(11)
    F[0], F[1], F[2], F[6], F[7] = 20000, 0.2, 0.04, 1.5, 0.2
    assert p1_ok(tuple(F))
    F[6] = 2.0
    assert not p1_ok(tuple(F))
    F[6] = 1.2
    F[5] = 5
    assert not p1_ok(tuple(F))
    assert period_of(CUT1 - 1) == 0 and period_of(CUT1) == 1 and period_of(CUT2) == 2
    assert period_of(CLEAN + 1) == 3
    gl._need_numba()
    pa = {
        "bar_t": np.array([2.0]), "bar_hi": np.array([10.0]), "bar_lo": np.array([1.0]),
        "bar_tick": np.array([0], np.int8), "tick_t": np.array([0.0]), "tick_px": np.array([10.0]),
        "anchor": 10.0, "cov": 100.0, "cs_start": np.array([0.0]), "cs_close": np.array([10.0]),
        "m0": 10.0, "end": 30.0,
    }
    ex = [dict(kind=0, tp=100.0, sl=0.5, T=50.0, arm=0.0, trail=0.0, tp2=0.0, name="t")]
    p1, _p2, _s, _t = gl.sim_one(pa, 0.5, 0.0, 10.0, gl.exits_arrays(ex), -1.0)
    assert abs(float(p1[0]) - 3.6) < 1e-6, float(p1[0])
    print(f"self-test OK whale {len(rows)} prefix {len(prefs)} tabrakan {dups or 'tidak ada'} SOLUSD={SOLUSD}", flush=True)
    return dups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--wallets", default="riset/wallet-whale-x-2026-11-10.csv")
    ap.add_argument("--out", default="riset/riset-filter-baru-2026-11-10.md")
    ap.add_argument("--null", type=int, default=20)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    print(f"SOLUSD={SOLUSD} ditulis sebelum hasil. Anti-honeypot tidak diuji.", flush=True)
    print("Proksi fresh: unique_buyers>=20 dan holders<=8 dan unique/holders>=3.", flush=True)
    print("Bundle tolak jika jumlah pembeli non-dev pada detik pertama >= 5.", flush=True)
    dups = self_test(a.wallets)
    if a.self_test:
        return
    t0 = time.time()
    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    print(f"sha skrip {sha}", flush=True)
    print(f"cache={os.environ.get('CACHE_MATCHED_KEY', '')}", flush=True)
    whales, prefixes, dups = load_whales(a.wallets)
    gl._need_numba()
    coins, meta = gl.load_coins(a.data)
    for i, c in enumerate(coins):
        c.i = i
        c.full_i = i
    seen = set()
    coins_hit = 0
    for c in coins:
        hit = False
        for _ag, w, b, _s in c.w:
            if b and w in prefixes:
                seen.add(w)
                hit = True
        coins_hit += int(hit)
    print(f"prefix daftar yang muncul di tape {len(seen)}/{len(prefixes)}; koin dengan >=1 beli {coins_hit}", flush=True)
    print("jalur harga...", flush=True)
    paths = []
    for i, c in enumerate(coins):
        paths.append(gl.extract_path(c))
        if i and i % 5000 == 0:
            print(f"  jalur {i}", flush=True)
    blocks, shorts = [], []
    for decision, snap, stale in AGES:
        for delay in DELAYS:
            print(f"G3/G6 D{decision} snap {snap} jeda {delay} basi={stale}", flush=True)
            block = build_block(coins, paths, prefixes, decision, snap, stale, delay)
            if block is None:
                print("  terlalu sedikit", flush=True)
                continue
            if block.get("short"):
                shorts.append(block)
                print(f"  n {len(block['idx'])} di bawah 30, tidak masuk pencarian", flush=True)
                continue
            blocks.append(block)
            print(f"  n {len(block['idx'])}", flush=True)
    print("buku WR dibekukan dari t0 < potongan A", flush=True)
    book = wr_book(coins, prefixes)
    known = sum(1 for _wr, n in book.values() if n >= 5)
    print(f"prefix dengan n>=5 di A: {known}", flush=True)
    print("copy whale + P1", flush=True)
    copy_cfgs, copy_mats = build_copy(coins, paths, prefixes, book)
    print("null dan hitung lulus...", flush=True)
    rng = np.random.default_rng(100)
    nulls = [0] * a.null
    real = 0
    all_recs = []
    for bi, block in enumerate(blocks):
        labeled = mask_list(block["F"])
        M = np.vstack([m for _lab, m in labeled])
        real += pass_count(M, block["X"], block["per"])
        recs, Mrec = records_of(block)
        for r in recs:
            r["bi"] = bi
        need = [(i // len(EXITS), i % len(EXITS)) for i, r in enumerate(recs) if r["nB"] >= 2]
        fill_nob(block, recs, Mrec, need)
        for r in recs:
            r["pass_b"] = bool(r["nA"] >= NMIN and (r["meanA"] or 0) > 1 and r["nB"] >= NMIN
                               and (r["meanB"] or 0) > 1 and (r["nobB"] or 0) > 1)
        all_recs.extend(recs)
        for s in range(a.null):
            perm = rng.permutation(block["F"].shape[0])
            Ms = np.vstack([m for _lab, m in mask_list(block["F"][perm])])
            nulls[s] += pass_count(Ms, block["X"], block["per"])
            print(f"  null {s} blok {bi} kumulatif {nulls[s]}", flush=True)
        del M, Mrec
    real += copy_pass(copy_mats)
    for s in range(a.null):
        for delay in DELAYS:
            got = copy_mats.get(delay)
            if not got:
                continue
            X, per, _keep = got
            perm = rng.permutation(X.shape[0])
            nulls[s] += pass_count(np.ones((1, X.shape[0]), dtype=bool), X[perm], per)
    all_recs.extend(copy_cfgs)
    k = len(all_recs)
    # WR tidak masuk k pencarian: buang dari all_recs setelah copy_pass? copy_cfgs includes WR.
    # copy_pass hanya mode semua (satu baris mask). k di bawah dihitung ulang tanpa WR.
    search = [r for r in all_recs if r["rankable"]]
    k = len(search)
    ranked = [r for r in search if r["nA"] >= NMIN and (r["meanA"] or 0) > 1]
    ranked.sort(key=lambda r: r["meanA"], reverse=True)
    finals, seen_sig = [], set()
    for r in ranked:
        sig = (r["family"], r["age"], r["delay"], r["band"], r["pack"])
        if sig in seen_sig:
            continue
        seen_sig.add(sig)
        finals.append(r)
        if len(finals) >= 5:
            break
    for r in finals:
        r["pass_b"] = bool(r["nB"] >= NMIN and (r["meanB"] or 0) > 1 and (r["nobB"] or 0) > 1)
    print("baseline Bom, mom120, aturan (b), jam 12-16", flush=True)
    ann = ab.annotate(coins, (120, 180))
    bases = {}
    base_rows = {}
    for name, rule in (
        ("Bom v1 (c)", ab.RULE_C),
        ("mom120 (a)", ab.RULE_A),
        ("aturan (b)", ab.RULE_B),
        ("finalis lama: (b) + jam 12-16 UTC", rule_hour()),
    ):
        print(" ", name, flush=True)
        rows = ab.sim_rule(coins, paths, ann, rule)
        for r in rows:
            r["per"] = period_of(coins[r["i"]].t0)
        base_rows[name] = rows
        bases[name] = slices_of(rows)
    print("kontrol G5", flush=True)
    g5 = slices_of(g5_rows(coins, paths))
    print("rincian finalis, Bom+modul, suara", flush=True)
    detailed = []
    for rec in finals:
        if rec["family"] == "G6-copy":
            rows = []
            items, mask = rec["items"], rec["mode_mask"]
            for j, it in enumerate(items):
                if not mask[j]:
                    continue
                i, per, te, lx, t0c, xs, to, _fail = it
                rows.append(dict(i=i, t=t0c + te, tout=t0c + float(to[rec["ek"]]), x=float(xs[rec["ek"]]),
                                 per=per, te=te, lx=lx))
        else:
            block = blocks[rec["bi"]]
            rows = rows_from_block(block, coins, mask_for(block, rec), rec["ek"])
        own = slices_of(rows)
        plus = slices_of(ab.combine_and(base_rows["Bom v1 (c)"], rows, coins, paths, ab.BOM_EXIT))
        xs_b = np.array([r["x"] for r in rows if r["per"] == 1], np.float64)
        p, B = gl.boot_p(xs_b, B=200000, seed=1) if xs_b.size >= 5 else (None, 0)
        if p == 0:
            p = 1.0 / B if B else None
        rec["p"] = p
        rec["own"] = own
        rec["plus"] = plus
        rec["rows_n"] = len(rows)
        detailed.append(rec)
    g3_show = []
    for age in (120, 300, 600, 1800):
        cand = [r for r in search if r["family"] == "G3" and r["age"] == age and r["delay"] == "3-8"
                and r["nA"] >= NMIN and r["meanA"] is not None]
        if not cand:
            cand = [r for r in search if r["family"] == "G3" and r["age"] == age
                    and r["nA"] >= NMIN and r["meanA"] is not None]
        if not cand:
            continue
        cand.sort(key=lambda r: r["meanA"], reverse=True)
        best = cand[0]
        if "own" not in best:
            if best["family"] == "G6-copy":
                continue
            block = blocks[best["bi"]]
            grows = rows_from_block(block, coins, mask_for(block, best), best["ek"])
            best["own"] = slices_of(grows)
            best["plus"] = slices_of(ab.combine_and(base_rows["Bom v1 (c)"], grows, coins, paths, ab.BOM_EXIT))
            best["pass_b"] = bool(best["nB"] >= NMIN and (best["meanB"] or 0) > 1 and (best["nobB"] or 0) > 1)
        g3_show.append(best)
    print("suara terkunci, bukan picker", flush=True)
    vote_pack = run_locked_votes(coins, paths, blocks, a.null)
    votes = vote_pack["rows"]
    # diagnostik likuiditas dan pita, dari blok jeda 3-8 supaya tidak ganda
    diag = []
    for block in list(blocks) + list(shorts):
        if block["delay"] != "3-8":
            continue
        F = block["F"]
        n = len(F)
        n25 = int(np.sum(F[:, 10] >= 25000))
        diag.append((block["decision"], block["stale"], n, n25, float(F[:, 0].max()) if n else 0,
                     {name: int(np.sum((F[:, 0] >= lo) & (F[:, 0] < hi))) for name, lo, hi in BANDS},
                     bool(block.get("short"))))
    n_fresh = sum(1 for c in coins if c.t0 > CLEAN)
    thr = 0.05 / k if k else None
    nmax = max(nulls) if nulls else 0
    official = [r for r in detailed if r["pass_b"]]
    cleared = [r for r in official if r.get("p") is not None and thr and r["p"] < thr]
    beat = real > nmax
    fresh_ok = any((r["own"]["segar"]["n"] >= NMIN and (r["own"]["segar"]["mean"] or 0) > 1
                    and (r["own"]["segar"]["nobest"] or 0) > 1) for r in cleared)
    vk, vreal, vnull = vote_pack["k"], vote_pack["real"], vote_pack["nulls"]
    vnmax = max(vnull) if vnull else 0
    vthr = 0.05 / vk if vk else None
    vpass = [v for v in votes if v["ok"]]
    vcleared = [v for v in vpass if v.get("p") is not None and vthr and v["p"] < vthr]
    vbeat = vreal > vnmax
    vote_note = (f"Suara terkunci {vreal} lulus dari {vk}, null maks {vnmax}, Bonferroni {vthr}.")
    vfresh = any((v.get("st") or {}).get("segar", {}).get("n", 0) >= NMIN
                 and (((v.get("st") or {}).get("segar") or {}).get("mean") or 0) > 1
                 and (((v.get("st") or {}).get("segar") or {}).get("nobest") or 0) > 1 for v in vcleared)
    vote_bar = bool(vcleared and vbeat)
    if cleared and beat and fresh_ok:
        line1 = "LAYAK sebagai kandidat paper saja, bukan live. " + vote_note
    elif vote_bar and vfresh:
        line1 = ("LAYAK sebagai kandidat paper saja, bukan live. Grid pencarian tidak lolos, "
                 "tetapi paket suara terkunci lolos B, null, Bonferroni, dan data segar. " + vote_note)
    elif (cleared and beat and n_fresh == 0) or (vote_bar and n_fresh == 0):
        line1 = ("BELUM LAYAK. Ada yang lolos B, null, dan Bonferroni, tetapi tidak ada koin dengan t0 sesudah "
                 "10 Nov 07:17 UTC. Konfirmasi bersih ditunda. Ini bukan LAYAK. " + vote_note)
    elif not detailed:
        line1 = (f"TIDAK LAYAK. Tidak ada konfigurasi dengan n_A≥30 dan rata A>1. "
                 f"Kombinasi {k}. Lulus A+B {real}. Null maks {nmax}. {vote_note} "
                 f"C tercemar dan tidak memilih. Tanpa lolos B, vonis tidak boleh LAYAK.")
    elif not official:
        line1 = (f"TIDAK LAYAK. Yang lolos syarat A tidak lolos B (n_B≥30, rata B>1, B tanpa koin terbaik >1). "
                 f"Kombinasi {k}. Lulus A+B di seluruh grid {real}, null maks {nmax}. {vote_note} "
                 f"Tanpa lolos B, vonis tidak boleh LAYAK.")
    elif not beat:
        line1 = (f"TIDAK LAYAK. Ada {len(official)} dari yang lolos A yang juga lolos B, tetapi jumlah lulus {real} "
                 f"tidak di atas null maks {nmax}. {vote_note}")
    elif not cleared:
        line1 = (f"TIDAK LAYAK. {len(official)} lolos B dan jumlah lulus di atas null, "
                 f"tetapi tidak ada p bootstrap di bawah Bonferroni {thr:.3g}. {vote_note} C tercemar.")
    elif not fresh_ok:
        line1 = ("TIDAK LAYAK. Lolos A+B dan koreksi, tetapi koin sesudah 10 Nov 07:17 UTC tidak mengkonfirmasi "
                 "(butuh n≥30, rata>1, tanpa koin terbaik >1). " + vote_note)
    else:
        line1 = "LAYAK sebagai kandidat paper saja, bukan live. " + vote_note
    L = [line1, "",
         "# Modul filter baru calon Bom v2, 10 Nov 2026, PAPER", "",
         "Satu bot: tim agen Bom. Modul di bawah calon tugas agen, bukan bot kedua.",
         "Anti-honeypot tidak di-backtest dan tidak diklaim lulus. Di kurva pump.fun jual dilayani program, dan rekaman tidak punya mint, freeze, Token-2022, atau kutipan Jupiter.",
         "Narasi X tidak diukur. Narasi-SKIP berarti butuh 4/4 agen lain. Narasi-ACC berarti butuh minimal 3/4. Angka 5/5 sama dengan 4/4, karena narasi hanya bisa diasumsikan setuju. Kalau narasi tidak menjawab, 5/5 tidak pernah kena.",
         f"SOLUSD={SOLUSD:.0f} dikunci sebelum hasil. mcap_usd = mcap_sol × {SOLUSD:.0f}.",
         f"sha spek e2cd46c009314e62ff9f77708ad3246913383a9e80617ec751200581fc0ec666. sha skrip {sha}.",
         f"Cache `{os.environ.get('CACHE_MATCHED_KEY') or '—'}`. Koin standar {meta.get('n_std')} baris {meta.get('n_lines')}. "
         f"t0 {meta.get('t_min')} .. {meta.get('t_max')}. Koin segar (t0 > 10 Nov 07:17 UTC) {n_fresh}.",
         f"Daftar whale {len(whales)} alamat, prefix unik {len(prefixes)}, tabrakan prefix {dups or 'tidak ada'}. "
         f"Yang muncul di tape GitHub {len(seen)}/{len(prefixes)}, pada {coins_hit} koin. "
         f"Buku WR beku dari A: {known} prefix dengan minimal 5 koin selesai.",
         "",
         "## Perbandingan",
         "",
         "A dan B untuk menilai. C sudah pernah dilihat (tercemar) dan tidak memilih parameter. "
         "Segar hanya diisi jika cache memuat koin lahir sesudah 10 Nov 07:17 UTC.",
         "Saldo adalah akhir dari $200, plus penurunan maksimum. Ukuran 8% atau 10%, maks 1 atau 5 posisi.",
         "",
         "| Strategi | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8%m1 / DD | 8%m5 / DD | 10%m1 / DD | 10%m5 / DD |",
         "|---|---|---:|---:|---|---:|---|---|---|---|"]
    for name, st in bases.items():
        add_slice_rows(L, name, st)
    add_slice_rows(L, "G5 kontrol kurva ≥92%, TP2, SL-50%, 120 dtk, jeda 3–8", g5)
    if detailed:
        add_slice_rows(L, "Peringkat A #1: " + describe(detailed[0]), detailed[0]["own"])
        add_slice_rows(L, "Bom v1 DAN peringkat A #1, waktu lebih akhir, jual jaga Bom", detailed[0]["plus"])
    else:
        L.append("| Peringkat A | | tidak ada dengan n_A≥30 dan rata A>1 | | | | | | | |")
    for rec in g3_show:
        tag = "lolos B" if rec.get("pass_b") else "tidak lolos B"
        add_slice_rows(L, f"G3 terbaik umur {rec['age']}s jeda 3–8 menurut A ({tag}): " + describe(rec), rec["own"])
        add_slice_rows(L, f"Bom v1 DAN G3 umur {rec['age']}s, jual jaga Bom", rec["plus"])
    for v in votes:
        if v["compare"] and v.get("st"):
            add_slice_rows(L, v["name"], v["st"])
    L += ["",
          "Bom sendiri ada di baris pertama. Bom+modul memakai masuk yang lebih lambat di antara sinyal Bom dan sinyal modul, lalu jual TP3 SL0,5 600 dtk.",
          "Suara terkunci, bukan hasil pilih-pilih: rug lulus jika top10≤30%, dev≤5%, dev belum jual, belum pernah rug, bundle<5. "
          "Latar lulus jika bukan proksi fresh dan dev belum jual. Data lulus jika mcap di pita itu, growth<2, drawdown<40%. "
          "Whale lulus jika minimal satu prefix daftar sudah beli di jendela yang terekam. "
          "4/4 adalah narasi-SKIP. ≥3/4 adalah narasi-ACC. 5/5 sama dengan 4/4 karena narasi hanya diasumsikan setuju. "
          "Harga pertama di umur keputusan. Setelah tunggu, masuk hanya jika harga masih di dalam pita, plus jeda eksekusi 1 dtk. Jual suara = jaga Bom.",
          "Baris suara di tabel ini dikunci sebelumnya: mcap 10–30k, tunggu 2 dtk, pita 15% dan tanpa batas. Tabel di bawah memuat semua pita dan semua tunggu.",
          "",
          "## Pencarian terkunci",
          "",
          f"- Konfigurasi yang masuk null dan Bonferroni: {k}. Bukan grid 68 juta. Konfigurasi WR<55% tidak masuk angka ini dan tidak masuk peringkat.",
          f"- Lulus A+B (n≥30, rata>1, B tanpa terbaik >1): {real}.",
          f"- Null 20×: {', '.join(str(x) for x in nulls)}. Maks {nmax}.",
          f"- Bonferroni 0,05/{k} = {thr}.",
          "- Umur 2/5/10 menit memakai snapshotnya sendiri. Umur 30 menit memakai fitur snapshot 10 menit dan dilabeli basi. Harga masuk tetap di detik ke-1800 plus jeda.",
          "- Keputusan di umur T hanya pada koin yang rekamannya masih hidup sampai T. Koin yang sudah mati tidak masuk. Itu syarat 'masih ada', bukan sampel semua listing.",
          "- Whale di keputusan 10 dan 30 menit hanya melihat beli dalam 5 menit pertama (rekaman wallet berhenti di situ).",
          "",
          "### Diagnostik, bukan gerbang",
          ""]
    for decision, stale, n, n25, mx, counts, short in diag:
        L.append(f"- Umur {decision}s{' (fitur basi)' if stale else ''}{' (tidak disimulasikan, n<30)' if short else ''}: "
                 f"koin {n}, mcap maks {mx:.0f} USD, liq≥$25k {n25}. Pita {counts}.")
    L.append("- liq≥$25k hampir tidak ada di kurva. Tidak dipakai memilih.")
    L += ["", "### Yang lolos syarat A (n≥30 dan rata A>1)", ""]
    if not detailed:
        L.append("Tidak ada. Tidak ada yang naik ke uji B sebagai finalis.")
    for i, rec in enumerate(detailed, 1):
        agent, task = agent_of(rec)
        L.append(f"{i}. Agen {agent}. {task}.")
        L.append(f"   - {describe(rec)}")
        for lab in ("A", "B", "C", "segar"):
            s = rec["own"][lab]
            L.append(f"   - {lab}: n={s['n']} rata {fmt_x(s['mean'])} median {fmt_x(s['median'])} "
                     f"menang {fmt_p(s['win'])} Wilson {fmt_p(s['wilson'][0])}–{fmt_p(s['wilson'][1])} "
                     f"tanpa terbaik {fmt_x(s['nobest'])} PF {s['pf']}")
        L.append(f"   - Lolos B: {'ya' if rec['pass_b'] else 'tidak'}. p bootstrap B {rec.get('p')}.")
        bb = rec["own"]["B"]["books"]
        if bb.get("100 8% m1"):
            L.append(f"   - B $100 8%m1 {fmt_money(bb['100 8% m1'])}; $100 10%m1 {fmt_money(bb['100 10% m1'])}; "
                     f"$1000 8%m1 {fmt_money(bb['1000 8% m1'])}; $1000 10%m1 {fmt_money(bb['1000 10% m1'])}.")
        pb = rec["plus"]["B"]
        L.append(f"   - Bom+modul di B: n={pb['n']} rata {fmt_x(pb['mean'])} tanpa terbaik {fmt_x(pb['nobest'])} "
                 f"saldo 8%m1 {fmt_money(pb['books'].get('8% m1'))}.")
    L += ["", "### G3 terbaik tiap umur, jeda 3–8, menurut A", "",
          "Ini diagnostik keluarga mcap. Bukan pemenang kalau rata A tidak di atas 1 atau B gagal.", ""]
    if not g3_show:
        L.append("Tidak ada G3 dengan n_A≥30.")
    for rec in g3_show:
        L.append(f"- {describe(rec)}")
        for lab in ("A", "B"):
            s = rec["own"][lab]
            L.append(f"  - {lab}: n={s['n']} rata {fmt_x(s['mean'])} tanpa terbaik {fmt_x(s['nobest'])} "
                     f"menang {fmt_p(s['win'])}")
        L.append(f"  - Lolos B: {'ya' if rec.get('pass_b') else 'tidak'}.")
    shown = [v for v in votes if v["nA"] or v["nB"]]
    hidden = len(votes) - len(shown)
    L += ["", "## Suara tim, paket terkunci", "",
          f"Bukan picker. {vote_note} Null: {', '.join(str(x) for x in vnull)}.",
          "Jual = jaga Bom (TP3 SL0,5 600 dtk). Eksekusi = umur keputusan + tunggu + 1 dtk.",
          "Baris dengan n_A dan n_B nol tidak dicetak." if hidden else "",
          "",
          "| Suara | n_A | Rata A | n_B | Rata B | Tanpa terbaik B | Lolos B |",
          "|---|---:|---:|---:|---:|---:|---|"]
    for v in shown:
        L.append(f"| {v['name']} | {v['nA']} | {fmt_x(v['meanA'])} | {v['nB']} | {fmt_x(v['meanB'])} | "
                 f"{fmt_x(v['nobB'])} | {'ya' if v['ok'] else 'tidak'} |")
    if not votes:
        L.append("| umur 30 menit atau semua umur di bawah n 30, suara tidak disimulasikan | | | | | | |")
    L += ["",
          f"Baris n=0 yang disembunyikan: {hidden}.",
          "Baris rug+data, rug+latar, dan rug+whale bukan suara 4/5. Dua agen yang lain tidak menjawab, jadi abstain dihitung SKIP dan 4/5 tidak pernah cukup. Angkanya tetap dilaporkan karena paket itu dikunci.",
          "Umur 30 menit masuk suara hanya jika ada minimal 30 koin yang rekamannya masih hidup sampai detik itu.",
          "",
          "## WR daftar whale",
          "",
          "Ambang 55% dan minimal 5 koin dikunci. Buku hanya dari koin t0 sebelum 2 Nov 17:43 UTC. "
          "Kalau n<5, gerbang abstain (tidak menggagalkan). Angka A tidak dipakai memilih karena buku A mencakup koin A yang lain.",
          ""]
    wr_rows = [r for r in copy_cfgs if r["band"] == "WR"]
    wr_rows.sort(key=lambda r: r["meanB"] if r["meanB"] is not None else -1, reverse=True)
    if not wr_rows:
        L.append("Tidak ada trade copy yang lolos P1.")
    else:
        L.append("| Jeda | Jual | n_A | Rata A | n_B | Rata B | Tanpa terbaik B |")
        L.append("|---|---|---:|---:|---:|---:|---:|")
        for r in wr_rows:
            L.append(f"| {r['delay']} | {r['exit']} | {r['nA']} | {fmt_x(r['meanA'])} | {r['nB']} | {fmt_x(r['meanB'])} | {fmt_x(r['nobB'])} |")
    L += ["",
          "## Batas",
          "",
          "- Anti-honeypot, mint, freeze, Token-2022, rute Jupiter, LP lock, funding hop, narasi X: tidak diuji.",
          "- Prefix 10 huruf bisa menabrak wallet lain. Tabrakan di daftar sendiri disebut di atas. Tabrakan dengan wallet di luar daftar tidak kelihatan.",
          "- Trade wallet setelah umur 5 menit tidak terekam. Maks 150 baris per koin.",
          "- Fitur 30 menit basi dari menit ke-10. Umur 60 menit dan 1–3 hari tidak ada di rekaman ini.",
          "- C tidak memilih. Tanpa tape sesudah 10 Nov 07:17 UTC tidak ada konfirmasi bersih, jadi hasil tidak disebut LAYAK.",
          f"- Waktu {time.time() - t0:.0f} dtk.",
          "",
          "Paper saja.",
          ""]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write("\n".join(L))
    print(line1, flush=True)
    print("tulis", a.out, flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        dest = "riset/riset-filter-baru-2026-11-10.md"
        argv = sys.argv
        if "--out" in argv:
            dest = argv[argv.index("--out") + 1]
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w") as f:
            f.write("GAGAL. Skrip berhenti sebelum ada hasil yang boleh dipakai.\n\n```\n" + traceback.format_exc() + "```\n")
        raise

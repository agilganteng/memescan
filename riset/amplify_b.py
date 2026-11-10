"""Perlebar tepi tipis aturan (b) sebagai MODUL agen Bom, bukan bot kedua. PAPER.

Arsitektur cuma satu: tim agen Bom (rug, narasi, latar/dev, data, whale) lalu keputusan lalu jaga.
Yang dicari di sini calon tugas untuk salah satu agen.

JUJUR, dikunci sebelum hasil:
- Setel HANYA di A+B. Potongan waktu SAMA dengan grid penuh:
  A: t0 < 1793641429.3 (2 Nov 2026 17:43 UTC)
  B: sampai 1793897700.2 (5 Nov 2026 16:55 UTC)
- C (sampai 10 Nov 2026 07:17 UTC) sudah pernah dilihat: TERCEMAR, hanya dilaporkan.
- Data t0 sesudah 1794295050.1 = konfirmasi bersih, hanya untuk finalis yang sudah dikunci.
- Peringkat menurut rata A (n_A>=30). Lolos B: n_B>=30, rata B>1, B tanpa koin terbaik >1.
- Null 20x mengacak fitur. Koreksi Bonferroni 0,05/jumlah kombinasi pada uji B.
- Biaya: fee 1,25%/sisi, slip 2%/sisi, priority 0,0005 SOL, ukuran 0,1 SOL, stop candle x0,72.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import grid_luas as gl  # noqa: E402

try:
    from numba import njit
except ImportError:
    njit = None

CUT1 = 1793641429.3
CUT2 = 1793897700.2
CLEAN_AFTER = 1794295050.1
NMIN = 30
DELAYS = ("0.4", "1", "2", "5", "3-8", "8-12", "10-15", "20-30")
AGES = (45, 60, 90, 120, 150, 180, 240, 300)
SNAP_OF = {45: 45, 60: 60, 90: 90, 120: 120, 150: 120, 180: 180, 240: 180, 300: 300}
PREV = {30: 10, 45: 30, 60: 30, 90: 60, 120: 60, 180: 120, 300: 180}
BOM_EXIT = dict(kind=0, tp=3.0, sl=0.5, T=600.0, arm=0.0, trail=0.0, tp2=0.0, w1=1.0, w2=0.0, name="TP3 SL0.5 600s")
BASE_EXIT = dict(kind=2, tp=2.0, sl=0.7, T=600.0, arm=0.0, trail=0.0, tp2=5.0, w1=0.5, w2=0.5,
                 name="parsial 50% 2x sisa TP5 SL0.7 600s")


def lag_of(kind, i, D, which):
    if which in ("0.4", "1", "3-8"):
        return gl.lag(kind, i, D, which)
    if which in ("2", "5"):
        return float(which)
    lo, hi = {"8-12": (8.0, 12.0), "10-15": (10.0, 15.0), "20-30": (20.0, 30.0)}[which]
    h = (int(i) * 1000003 + int(D) * 9176 + int(kind) * 13 + int(lo * 10)) & 0xFFFFFFFF
    return lo + (h % 10000) / 10000.0 * (hi - lo)


def period_of(t):
    if t > CLEAN_AFTER:
        return 3
    if t < CUT1:
        return 0
    if t < CUT2:
        return 1
    return 2


def cart(*axes):
    out = [("", [])]
    for axis in axes:
        nxt = []
        for lab, conds in out:
            for frag, extra in axis:
                nxt.append(((lab + " " + frag).strip(), conds + list(extra)))
        out = nxt
    return out


def all_specs():
    growth = [("growth>=2", [(9, ">=", 2.0)]), ("growth>=3", [(9, ">=", 3.0)]), ("growth>=5", [(9, ">=", 5.0)]),
              ("growth 3-6", [(9, ">=", 3.0), (9, "<", 6.0)]), ("growth bebas", [])]
    bsr = [("beli>=0.65", [(10, ">=", 0.65)]), ("beli>=0.8", [(10, ">=", 0.8)]), ("beli bebas", [])]
    dd = [("dd<=0.15", [(11, "<=", 0.15)]), ("dd<=0.35", [(11, "<=", 0.35)]), ("dd bebas", [])]
    vol = [("vol>=1", [(12, ">=", 1.0)]), ("vol>=3", [(12, ">=", 3.0)]), ("vol>=8", [(12, ">=", 8.0)]), ("vol bebas", [])]
    rate = [("laju>=0.5", [(13, ">=", 0.5)]), ("laju>=1.5", [(13, ">=", 1.5)]), ("laju bebas", [])]
    top = [("top10<=0.25", [(1, "<=", 0.25)]), ("top10<=0.35", [(1, "<=", 0.35)]), ("top10 bebas", [])]
    core = cart(growth, bsr, dd, vol, rate, top)
    g2 = [("growth>=3", [(9, ">=", 3.0)]), ("growth>=2", [(9, ">=", 2.0)]), ("growth 3-6", [(9, ">=", 3.0), (9, "<", 6.0)])]
    b2 = [("beli>=0.65", [(10, ">=", 0.65)]), ("beli>=0.8", [(10, ">=", 0.8)])]
    v2 = [("vol>=3", [(12, ">=", 3.0)]), ("vol>=8", [(12, ">=", 8.0)])]
    r2 = [("laju>=1.5", [(13, ">=", 1.5)]), ("laju>=0.5", [(13, ">=", 0.5)])]
    d3 = [("dd<=0.15", [(11, "<=", 0.15)]), ("dd<=0.35", [(11, "<=", 0.35)]), ("dd bebas", [])]
    t2 = [("top10<=0.35", [(1, "<=", 0.35)]), ("top10 bebas", [])]
    sm = [("smart bebas", []), ("smart>=1", [(7, ">=", 1.0)]), ("copy>=1", [(14, ">=", 1.0)])]
    dv = [("dev bebas", []), ("dev belum jual", [(5, "==", 0.0)])]
    td = [("jam bebas", []), ("jam 0-8", [(15, "<", 8.0)]), ("jam 8-16", [(15, ">=", 8.0), (15, "<", 16.0)]),
          ("jam 16-24", [(15, ">=", 16.0)])]
    ctx = cart(g2, b2, v2, r2, d3, t2, sm, dv, td)
    base = [("growth>=3 beli>=0.65 vol>=3 laju>=1.5",
             [(9, ">=", 3.0), (10, ">=", 0.65), (12, ">=", 3.0), (13, ">=", 1.5)])]
    holders = [("holder bebas", []), ("holder>=15", [(3, ">=", 15.0)]), ("holder>=40", [(3, ">=", 40.0)])]
    buyers = [("buyer bebas", []), ("buyer>=20", [(2, ">=", 20.0)]), ("buyer>=50", [(2, ">=", 50.0)])]
    mcap = [("mcap bebas", []), ("mcap<45", [(0, "<", 45.0)]), ("mcap 45-120", [(0, ">=", 45.0), (0, "<", 120.0)])]
    liq = [("liq bebas", []), ("liq>=8", [(4, ">=", 8.0)])]
    tod4 = [("jam bebas", [])] + [(f"jam {h}-{h+4}", [(15, ">=", float(h)), (15, "<", float(h + 4))]) for h in range(0, 24, 4)]
    thin = cart(base, holders, buyers, mcap, liq, tod4, d3, t2)
    seen, out = set(), []
    for lab, conds in core + ctx + thin:
        if lab in seen:
            continue
        seen.add(lab)
        out.append((lab, conds))
    return out


def std_exits():
    ex = []
    for tp in (1.5, 2.0, 3.0, 5.0, 10.0):
        for sl in (0.5, 0.6, 0.7, 0.8):
            for T in (120.0, 600.0, 1800.0):
                ex.append(dict(kind=0, tp=tp, sl=sl, T=T, arm=0.0, trail=0.0, tp2=0.0, w1=1.0, w2=0.0,
                               name=f"TP{tp:g} SL{sl:g} {T:.0f}s"))
    for arm in (0.5, 1.0):
        for tr in (0.20, 0.30, 0.40):
            for T in (600.0, 1800.0):
                ex.append(dict(kind=1, tp=1e9, sl=0.7, T=T, arm=arm, trail=tr, tp2=0.0, w1=1.0, w2=0.0,
                               name=f"trail +{arm:.0%} lebar {tr:.0%} SL0.7 {T:.0f}s"))
    for tp1 in (1.5, 2.0):
        for tp2 in (3.0, 5.0, 10.0):
            for sl in (0.6, 0.7):
                for T in (300.0, 600.0, 1800.0):
                    ex.append(dict(kind=2, tp=tp1, sl=sl, T=T, arm=0.0, trail=0.0, tp2=tp2, w1=0.5, w2=0.5,
                                   name=f"parsial 50% {tp1:g}x sisa TP{tp2:g} SL{sl:g} {T:.0f}s"))
    return ex


def leg_exits():
    """Tangga 30/30/40 dan moonbag. kind 4 = tangga target, kind 5 = 70% lalu trail sisa."""
    ex = []
    for sl in (0.6, 0.7):
        for T in (600.0, 1800.0):
            ex.append(dict(kind=4, tp=1.5, tp2=3.0, tp3=10.0, sl=sl, T=T, trail=0.0, w1=0.30, w2=0.30,
                           name=f"tangga 30% 1.5x 30% 3x sisa TP10 SL{sl:g} {T:.0f}s"))
            ex.append(dict(kind=4, tp=2.0, tp2=5.0, tp3=10.0, sl=sl, T=T, trail=0.0, w1=0.30, w2=0.30,
                           name=f"tangga 30% 2x 30% 5x sisa TP10 SL{sl:g} {T:.0f}s"))
    for tr in (0.20, 0.30, 0.40):
        ex.append(dict(kind=5, tp=2.0, tp2=0.0, tp3=0.0, sl=0.7, T=1800.0, trail=tr, w1=0.70, w2=0.0,
                       name=f"moonbag 70% di 2x sisa trail {tr:.0%} SL0.7 1800s"))
        ex.append(dict(kind=5, tp=3.0, tp2=0.0, tp3=0.0, sl=0.7, T=1800.0, trail=tr, w1=0.70, w2=0.0,
                       name=f"moonbag 70% di 3x sisa trail {tr:.0%} SL0.7 1800s"))
    return ex


if njit is not None:
    @njit(cache=True)
    def _legs(bar_t, bar_hi, bar_lo, bar_tick, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0, end_t,
              te, lx, p_in, tp, tp2, tp3, slv, T, trail, w1, w2, kind):
        n = tp.shape[0]
        p1 = np.zeros(n)
        p2 = np.zeros(n)
        p3 = np.zeros(n)
        fw1 = np.zeros(n)
        fw2 = np.zeros(n)
        fw3 = np.zeros(n)
        tout = np.zeros(n)
        alive = np.ones(n, np.int8)
        leg = np.zeros(n, np.int8)
        peak = np.full(n, p_in)
        armed = np.zeros(n, np.int8)
        nbar = bar_t.shape[0]
        i0 = np.searchsorted(bar_t, te, side="right") if nbar else 0

        def px_at(t):
            return gl._price_at(t, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)

        for i in range(i0, nbar):
            t = bar_t[i]
            hi = bar_hi[i]
            lo = bar_lo[i]
            tick = bar_tick[i]
            any_alive = 0
            for k in range(n):
                if alive[k] == 0:
                    continue
                any_alive = 1
                if t >= te + T[k]:
                    px = px_at(te + T[k] + lx)
                    rem = 1.0 - fw1[k] - fw2[k]
                    p3[k] = px
                    fw3[k] = rem
                    tout[k] = te + T[k] + lx
                    alive[k] = 0
                    continue
                sl_px = p_in * slv[k] if slv[k] > 0 else -1.0
                if kind[k] == 5 and leg[k] >= 1 and armed[k] == 1:
                    trp = peak[k] * (1.0 - trail[k])
                    if trp > sl_px:
                        sl_px = trp
                if sl_px > 0 and lo <= sl_px:
                    if tick == 1:
                        px = px_at(t + lx)
                        if px > sl_px:
                            px = sl_px
                    else:
                        px = sl_px * 0.72
                    rem = 1.0 - fw1[k] - fw2[k]
                    p3[k] = px
                    fw3[k] = rem
                    tout[k] = t + lx
                    alive[k] = 0
                    continue
                if leg[k] == 0 and hi >= p_in * tp[k]:
                    level = p_in * tp[k]
                    px = px_at(t + lx) if tick == 1 else level
                    p1[k] = px
                    fw1[k] = w1[k]
                    leg[k] = 1
                    tout[k] = t + lx
                if alive[k] == 1 and kind[k] == 4 and leg[k] == 1 and hi >= p_in * tp2[k]:
                    level = p_in * tp2[k]
                    px = px_at(t + lx) if tick == 1 else level
                    p2[k] = px
                    fw2[k] = w2[k]
                    leg[k] = 2
                    tout[k] = t + lx
                if alive[k] == 1 and kind[k] == 4 and leg[k] == 2 and hi >= p_in * tp3[k]:
                    level = p_in * tp3[k]
                    px = px_at(t + lx) if tick == 1 else level
                    p3[k] = px
                    fw3[k] = 1.0 - fw1[k] - fw2[k]
                    tout[k] = t + lx
                    alive[k] = 0
                if alive[k] == 1:
                    if hi > peak[k]:
                        peak[k] = hi
                    if kind[k] == 5 and leg[k] >= 1 and peak[k] >= p_in * tp[k]:
                        armed[k] = 1
            if any_alive == 0:
                break
        for k in range(n):
            if alive[k] == 0:
                continue
            px = px_at(end_t)
            p3[k] = px
            fw3[k] = 1.0 - fw1[k] - fw2[k]
            tout[k] = end_t
        return p1, p2, p3, fw1, fw2, fw3, tout
else:
    def _legs(*_a, **_k):
        raise SystemExit("Butuh numba")


def multi_cost(p_in, prices, weights):
    vs_in = np.sqrt(gl.K_CURVE * max(p_in, 1e-9))
    e = p_in * (1.0 + gl.SIZE / vs_in) / ((1.0 - gl.FEE) * (1.0 - gl.SLIP))
    s = 0.0
    n_sell = 0
    for p, w in zip(prices, weights):
        if w <= 1e-8:
            continue
        n_sell += 1
        vs = np.sqrt(gl.K_CURVE * max(p, 1e-9))
        s += w * p * (1.0 - gl.FEE) * (1.0 - gl.SLIP) / (1.0 + (gl.SIZE * w) / vs)
    return max(0.0, s / e - (1 + n_sell) * gl.PRIO / gl.SIZE)


def one_x(pa, te, lx, p_in, exit_):
    if exit_["kind"] in (4, 5):
        arrs = [np.array([exit_[k]], np.float64) for k in ("tp", "tp2", "tp3", "sl", "T", "trail", "w1", "w2")]
        kind = np.array([exit_["kind"]], np.int8)
        p1, p2, p3, fw1, fw2, fw3, tout = _legs(
            pa["bar_t"], pa["bar_hi"], pa["bar_lo"], pa["bar_tick"], pa["tick_t"], pa["tick_px"],
            pa["anchor"], pa["cov"], pa["cs_start"], pa["cs_close"], pa["m0"], pa["end"],
            float(te), float(lx), float(p_in), arrs[0], arrs[1], arrs[2], arrs[3], arrs[4], arrs[5],
            arrs[6], arrs[7], kind)
        x = multi_cost(p_in, (float(p1[0]), float(p2[0]), float(p3[0])), (float(fw1[0]), float(fw2[0]), float(fw3[0])))
        return float(x), float(tout[0])
    p1, p2, split, tout = gl.sim_one(pa, te, lx, p_in, gl.exits_arrays([exit_]), -1.0)
    return float(gl.apply_costs(p_in, p1, p2, split)[0]), float(tout[0])


def batch_x(pa, te, lx, p_in, std, legs):
    cols = []
    touts = []
    if std:
        p1, p2, split, tout = gl.sim_one(pa, te, lx, p_in, gl.exits_arrays(std), -1.0)
        cols.append(gl.apply_costs(p_in, p1, p2, split))
        touts.append(tout)
    if legs:
        tp = np.array([e["tp"] for e in legs])
        tp2 = np.array([e.get("tp2", 0.0) for e in legs])
        tp3 = np.array([e.get("tp3", 0.0) for e in legs])
        slv = np.array([e["sl"] for e in legs])
        T = np.array([e["T"] for e in legs])
        trail = np.array([e.get("trail", 0.0) for e in legs])
        w1 = np.array([e["w1"] for e in legs])
        w2 = np.array([e["w2"] for e in legs])
        kind = np.array([e["kind"] for e in legs], np.int8)
        p1, p2, p3, fw1, fw2, fw3, tout = _legs(
            pa["bar_t"], pa["bar_hi"], pa["bar_lo"], pa["bar_tick"], pa["tick_t"], pa["tick_px"],
            pa["anchor"], pa["cov"], pa["cs_start"], pa["cs_close"], pa["m0"], pa["end"],
            float(te), float(lx), float(p_in), tp, tp2, tp3, slv, T, trail, w1, w2, kind)
        xs = np.empty(len(legs), np.float32)
        for k in range(len(legs)):
            xs[k] = multi_cost(p_in, (p1[k], p2[k], p3[k]), (fw1[k], fw2[k], fw3[k]))
        cols.append(xs)
        touts.append(tout)
    return np.concatenate(cols), np.concatenate(touts)


def annotate(coins, ages):
    """smart / dev jual / copy baru, kausal, untuk umur snapshot yang dipakai."""
    done = []
    for c in coins:
        per = {}
        for ag, w, b, s in c.w:
            d = per.setdefault(w, [0.0, 0.0, None, None])
            if b:
                d[0] += s
                if d[2] is None:
                    d[2] = ag
            else:
                d[1] += s
                if d[2] is not None and d[3] is None:
                    d[3] = ag
        for w, (bs, ss, fb, fs) in per.items():
            if bs > 0 and ss > 0:
                hold = (fs - fb) if (fs is not None and fb is not None) else 999.0
                done.append((c.t0 + c.cov, w, 1.0 if ss > bs else 0.0, ss - bs, float(hold)))
    done.sort(key=lambda z: z[0])
    hist, ptr = {}, 0
    out = []

    def advance(to_t):
        nonlocal ptr
        while ptr < len(done) and done[ptr][0] <= to_t:
            t, w, win, pnl, hold = done[ptr]
            hist.setdefault(w, []).append((t, win, pnl, hold))
            ptr += 1

    for c in coins:
        sold, buys = [], []
        for ag, w, b, s in c.w:
            advance(c.t0 + ag)
            if (not b) and w == c.dev and s > 0:
                sold.append(ag)
            if not b:
                continue
            h = hist.get(w) or ()
            is_smart = False
            if len(h) >= gl.SMART_N:
                wr = sum(z[1] for z in h) / len(h)
                pnl = sum(z[2] for z in h)
                is_smart = wr >= gl.SMART_WR and pnl > 0
            buys.append((ag, w, is_smart))
        info = {}
        for D in ages:
            dev = 1.0 if any(a <= D for a in sold) else 0.0
            smart = float(len({w for a, w, sm in buys if a <= D and sm}))
            recent = float(len({w for a, w, sm in buys if sm and D - 30.0 < a <= D}))
            info[D] = (dev, smart, recent)
        info["buys"] = buys
        info["sold"] = sold
        out.append(info)
    print(f"anotasi {len(coins)} koin", flush=True)
    return out


def feat_of(c, snap, info):
    sn = c.snaps.get(snap)
    if sn is None or info is None or snap not in info:
        return None
    dev_sold, smart, copy_r = info[snap]

    def g(name):
        return float(sn[gl.FI[name]])

    prev = PREV.get(snap)
    vol = g("inflow_sol")
    if prev is not None and prev in c.snaps:
        vol = vol - float(c.snaps[prev][gl.FI["inflow_sol"]])
    hour = float((int(c.t0) % 86400) // 3600)
    return np.array([
        float(sn[1]), g("top10"), g("unique_buyers"), g("holders"), g("liq_sol"),
        float(dev_sold), float(c.devbuy), float(smart), g("creator_prev_rugs"), g("growth"),
        g("buy_sell_ratio"), g("drawdown"), float(vol), g("buyer_rate"), float(copy_r), hour,
    ], np.float64)


def conds_ok(row, conds):
    for col, op, val in conds:
        x = row[col]
        if op == ">=" and not x >= val:
            return False
        if op == "<=" and not x <= val:
            return False
        if op == "<" and not x < val:
            return False
        if op == ">" and not x > val:
            return False
        if op == "==" and not x == val:
            return False
    return True


def mask_of(F, conds):
    m = np.ones(F.shape[0], dtype=bool)
    for col, op, val in conds:
        x = F[:, col]
        if op == ">=":
            m &= x >= val
        elif op == "<=":
            m &= x <= val
        elif op == "<":
            m &= x < val
        elif op == ">":
            m &= x > val
        elif op == "==":
            m &= x == val
    return m


def slice_mean(x, sel):
    xs = x[sel]
    n = int(xs.size)
    if n == 0:
        return n, float("nan")
    return n, float(xs.mean())


def nobest(xs):
    if xs.size < 2:
        return float("nan")
    return float((xs.sum() - xs.max()) / (xs.size - 1))


def count_pass(X, M, per):
    """Lolos = n_A,n_B>=30, rata A>1, rata B>1, B tanpa terbaik >1. C tidak ikut."""
    a = per == 0
    b = per == 1
    if not np.any(a) or not np.any(b):
        return 0
    Ma, Mb = M[:, a], M[:, b]
    nA = Ma.sum(1)
    nB = Mb.sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mA = (Ma @ X[a]) / nA[:, None]
        mB = (Mb @ X[b]) / nB[:, None]
    cand = (nA >= NMIN)[:, None] & (mA > 1) & (nB >= NMIN)[:, None] & (mB > 1)
    cnt = 0
    if not np.any(cand):
        return 0
    Xb = X[b]
    for k in np.flatnonzero(np.any(cand, axis=0)):
        fs = np.flatnonzero(cand[:, k])
        xs = Xb[:, k].astype(np.float64)
        mk = Mb[fs]
        sums = mk @ xs
        ns = mk.sum(1).astype(np.float64)
        order = np.argsort(-xs)
        first = np.argmax(mk[:, order], axis=1)
        mx = xs[order][first]
        nob = (sums - mx) / np.maximum(ns - 1.0, 1.0)
        cnt += int(np.sum((ns >= NMIN) & (nob > 1)))
    return cnt


def push_heap(heap, key, rec, limit):
    rec = dict(rec)
    rec["key"] = key
    heap.append(rec)
    heap.sort(key=lambda r: r["key"], reverse=True)
    if len(heap) > limit:
        del heap[limit:]


def scan(F, X, per, specs, exits, meta_row):
    """Kembalikan (lulus, heap_A, heap_lolos) untuk satu kelompok masuk."""
    heap_a, heap_p = [], []
    total = 0
    n_pass = 0
    step = 400
    for s0 in range(0, len(specs), step):
        chunk = specs[s0:s0 + step]
        M = np.vstack([mask_of(F, c) for _lab, c in chunk])
        a, b = per == 0, per == 1
        nA = M[:, a].sum(1)
        nB = M[:, b].sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            mA = (M[:, a] @ X[a]) / np.maximum(nA[:, None], 1)
            mB = (M[:, b] @ X[b]) / np.maximum(nB[:, None], 1)
        mA = np.where(nA[:, None] > 0, mA, np.nan)
        mB = np.where(nB[:, None] > 0, mB, np.nan)
        cand = (nA >= NMIN)[:, None] & (mA > 1) & (nB >= NMIN)[:, None] & (mB > 1)
        nob = np.full(mB.shape, np.nan)
        if np.any(cand):
            Xb = X[b]
            Mb = M[:, b]
            for k in np.flatnonzero(np.any(cand, axis=0)):
                fs = np.flatnonzero(cand[:, k])
                xs = Xb[:, k].astype(np.float64)
                mk = Mb[fs]
                sums = mk @ xs
                ns = mk.sum(1).astype(np.float64)
                order = np.argsort(-xs)
                first = np.argmax(mk[:, order], axis=1)
                mx = xs[order][first]
                nob[fs, k] = (sums - mx) / np.maximum(ns - 1.0, 1.0)
        for fi, (lab, conds) in enumerate(chunk):
            for k in range(X.shape[1]):
                total += 1
                ok = (nA[fi] >= NMIN and mA[fi, k] == mA[fi, k] and nB[fi] >= NMIN
                      and mB[fi, k] > 1 and nob[fi, k] == nob[fi, k] and nob[fi, k] > 1)
                if ok:
                    n_pass += 1
                if not (nA[fi] >= NMIN and mA[fi, k] == mA[fi, k]):
                    continue
                rec = dict(meta_row)
                rec.update(filt=lab, conds=conds, exit=exits[k], nA=int(nA[fi]), meanA=float(mA[fi, k]),
                           nB=int(nB[fi]), meanB=float(mB[fi, k]) if mB[fi, k] == mB[fi, k] else None,
                           nobestB=float(nob[fi, k]) if nob[fi, k] == nob[fi, k] else None)
                push_heap(heap_a, rec["meanA"], rec, 30)
                if (nB[fi] >= NMIN and mB[fi, k] > 1 and nob[fi, k] == nob[fi, k] and nob[fi, k] > 1):
                    rec2 = dict(rec)
                    rec2["pass_b"] = True
                    push_heap(heap_p, rec2["meanA"], rec2, 30)
    return total, n_pass, heap_a, heap_p


def ab_count(F, X, per, specs):
    tot = 0
    for s0 in range(0, len(specs), 400):
        chunk = specs[s0:s0 + 400]
        M = np.vstack([mask_of(F, c) for _lab, c in chunk])
        tot += count_pass(X, M, per)
    return tot


def build_entry_matrix(coins, paths, ann, decision, snap, delay, kind, exits, mode="snap", dip=0.0):
    std = [e for e in exits if e["kind"] in (0, 1, 2)]
    legs = [e for e in exits if e["kind"] in (4, 5)]
    # kompilasi
    if coins:
        gl.sim_one(paths[0], 0.0, 0.4, max(paths[0]["anchor"], 1.0), gl.exits_arrays(std[:1] or exits[:1]), -1.0)
        if legs:
            one_x(paths[0], 1.0, 0.4, max(paths[0]["anchor"], 1.0), legs[0])
    F, X, P, idx = [], [], [], []
    for i, c in enumerate(coins):
        if period_of(c.t0) > 1:
            continue
        fr = feat_of(c, snap, ann[i])
        if fr is None:
            continue
        lx = lag_of(kind, c.full_i, decision if mode == "snap" else snap, delay)
        if mode == "snap":
            te = decision + lx
        else:
            te = dip_time(paths[i], snap, dip)
            if te is None:
                continue
            te = te + lx
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(paths[i], te)
        if p_in <= 0:
            continue
        xs, _to = batch_x(paths[i], te, lx, p_in, std, legs)
        F.append(fr)
        X.append(xs)
        P.append(period_of(c.t0))
        idx.append(i)
        if i and i % 20000 == 0:
            print(f"  sim {mode} D{decision} {delay} {i}", flush=True)
    if len(F) < 30:
        return None
    order = std + legs
    return (np.asarray(F, np.float64), np.asarray(X, np.float32), np.asarray(P, np.int8), order)


def dip_time(pa, D, dip):
    """Waktu bar pertama sesudah D+5 dtk saat harga jatuh `dip` dari puncak sesudah D."""
    t = pa["bar_t"]
    hi = pa["bar_hi"]
    lo = pa["bar_lo"]
    if t.size == 0:
        return None
    i0 = int(np.searchsorted(t, D + 5.0, side="left"))
    peak = -1.0
    for i in range(i0, t.size):
        if hi[i] > peak:
            peak = hi[i]
        if peak > 0 and lo[i] <= peak * (1.0 - dip):
            return float(t[i])
    return None


def load_ready(data, need_all=False):
    gl._need_numba()
    coins, meta = gl.load_coins(data)
    for i, c in enumerate(coins):
        c.i = i
        c.full_i = i
    if not need_all:
        coins = [c for c in coins if c.t0 < CUT2]
        for i, c in enumerate(coins):
            c.i = i
    print("jalur harga...", flush=True)
    paths = []
    for i, c in enumerate(coins):
        paths.append(gl.extract_path(c))
        if i and i % 5000 == 0:
            print(f"  jalur {i}", flush=True)
    ann = annotate(coins, (2.0, 30, 45, 60, 90, 120, 180, 300))
    meta = dict(meta)
    meta["cache_key"] = os.environ.get("CACHE_MATCHED_KEY") or ""
    meta["n_used"] = len(coins)
    return coins, paths, ann, meta


def run_search(data, ages, out, nulls, reentry=False):
    t0 = time.time()
    coins, paths, ann, meta = load_ready(data, need_all=False)
    specs = all_specs()
    exits = std_exits() + leg_exits()
    print(f"filter {len(specs)} keluar {len(exits)} umur {ages} reentry={reentry}", flush=True)
    delays = ("1", "3-8") if reentry else DELAYS
    dips = (0.10, 0.20, 0.35) if reentry else (0.0,)
    total = 0
    passed_n = 0
    null = [0] * nulls
    heap_a, heap_p = [], []
    for age in ages:
        snap = SNAP_OF.get(age, age) if not reentry else age
        if snap not in PREV and snap not in (45, 60, 90, 120, 180, 300):
            continue
        for delay in delays:
            for dip in dips:
                label = f"{'reentry' if reentry else 'snap'} D{age} jeda {delay}" + (f" dip {dip:.0%}" if reentry else "")
                print(label, flush=True)
                built = build_entry_matrix(coins, paths, ann, age if not reentry else snap, snap, delay, 3, exits,
                                            "reentry" if reentry else "snap", dip)
                if built is None:
                    print("  terlalu sedikit", flush=True)
                    continue
                F, X, per, order = built
                meta_row = dict(mode="reentry" if reentry else "snap", age=age, snap=snap, delay=delay,
                                dip=dip, kind=3)
                ncom, npass, ha, hp = scan(F, X, per, specs, order, meta_row)
                total += ncom
                passed_n += npass
                for rec in ha:
                    push_heap(heap_a, rec["meanA"], rec, 30)
                for rec in hp:
                    push_heap(heap_p, rec["meanA"], rec, 30)
                for s in range(nulls):
                    rng = np.random.default_rng(100 + s)
                    null[s] += ab_count(F[rng.permutation(F.shape[0])], X, per, specs)
                    print(f"  null {s} kumulatif {null[s]}", flush=True)
                del F, X
                print(f"  kombinasi kelompok {ncom} total {total}", flush=True)
    slim_a = [_pub(r) for r in heap_a]
    slim_p = [_pub(r) for r in heap_p]
    os.makedirs(out, exist_ok=True)
    doc = dict(meta=meta, combos=total, real_pass=passed_n, null=null,
               top_a=slim_a, passed=slim_p, secs=time.time() - t0, reentry=reentry, ages=list(ages))
    path = os.path.join(out, "amplify_part.json")
    with open(path, "w") as f:
        json.dump(doc, f, indent=1, default=float)
    print(f"tulis {path} kombinasi {total} detik {doc['secs']:.0f}", flush=True)


def _pub(r):
    d = dict(r)
    d.pop("key", None)
    d["conds"] = [list(c) for c in r["conds"]]
    d["exit"] = {k: (float(v) if isinstance(v, (float, int)) and not isinstance(v, bool) else v) for k, v in r["exit"].items()}
    return d


def rule_snap(name, age, delay, conds, exit_, kind=3):
    return dict(name=name, mode="snap", age=age, snap=SNAP_OF.get(age, age), delay=delay, kind=kind,
                dip=0.0, conds=conds, exit=exit_, filt=name)


RULE_A = rule_snap("(a) mom120 jeda 1", 120, "1", [(9, ">=", 3.0), (11, "<=", 0.35), (1, "<=", 0.35)], BASE_EXIT)
RULE_B = rule_snap("(b) momentum 120 jeda 3-8", 120, "3-8",
                   [(9, ">=", 3.0), (10, ">=", 0.65), (12, ">=", 3.0), (13, ">=", 1.5)], BASE_EXIT)
RULE_C = rule_snap("(c) Bom D180", 180, "1",
                   [(5, "==", 0.0), (1, "<=", 0.40), (2, ">=", 40.0), (4, ">=", 8.0), (7, ">=", 1.0),
                    (6, "<", 0.5), (8, "==", 0.0)], BOM_EXIT, kind=2)
FAM_MOM = rule_snap("keluarga data D30", 30, "0.4",
                    [(9, ">=", 3.0), (11, "<=", 0.15), (13, ">=", 1.5), (1, "<=", 0.35)],
                    dict(kind=0, tp=3.0, sl=0.5, T=120.0, arm=0.0, trail=0.0, tp2=0.0, w1=1.0, w2=0.0,
                         name="TP3 SL0.5 120s"))
FAM_BOM = rule_snap("keluarga Bom D60", 60, "0.4",
                    [(5, "==", 0.0), (4, ">=", 8.0), (6, ">=", 0.5), (6, "<", 2.0), (8, "==", 0.0)],
                    dict(kind=0, tp=1e9, sl=0.0, T=1800.0, arm=0.0, trail=0.0, tp2=0.0, w1=1.0, w2=0.0,
                         name="tahan sampai habis"), kind=2)


def sim_rule(coins, paths, ann, rule):
    rows = []
    for i, c in enumerate(coins):
        if rule["mode"] == "sniper":
            if not c.w or not (0.5 <= c.devbuy < 2.0):
                continue
            lx = 0.4
            te = c.w[0][0] + lx
        elif rule["mode"] == "grad":
            pa = paths[i]
            hi = pa["bar_hi"]
            thr = (30 + 0.85 * 85) ** 2 / gl.K_CURVE
            if hi.size == 0 or float(hi.max()) < thr:
                continue
            j = int(np.argmax(hi >= thr))
            if hi[j] < thr:
                continue
            th = float(pa["bar_t"][j])
            if th < 900:
                continue
            lx = 0.4
            te = th + lx
        elif rule["mode"] == "copy":
            continue
        else:
            fr = feat_of(c, rule["snap"], ann[i])
            if fr is None or not conds_ok(fr, rule["conds"]):
                continue
            lx = lag_of(rule["kind"], c.full_i, rule["age"], rule["delay"])
            if rule["mode"] == "reentry":
                te0 = dip_time(paths[i], rule["snap"], rule.get("dip") or 0.2)
                if te0 is None:
                    continue
                te = te0 + lx
            else:
                te = rule["age"] + lx
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(paths[i], te)
        if p_in <= 0:
            continue
        x, to = one_x(paths[i], te, lx, p_in, rule["exit"])
        rows.append(dict(i=i, t=c.t0 + te, tout=c.t0 + to, x=x, per=period_of(c.t0), te=te, lx=lx))
    return rows


def sim_copy(coins, paths):
    for i, c in enumerate(coins):
        c.i = i
    events = gl.prepare(coins)
    exit_ = dict(kind=0, tp=1e9, sl=0.7, T=60.0, arm=0.0, trail=0.0, tp2=0.0, w1=1.0, w2=0.0, name="tanpa TP SL0.7 60s")
    seen, rows = set(), []
    for ev_i, ev in enumerate(events):
        ci, ag, tabs, _fol, sv = ev
        n, wr, pnl, hold = sv[4], sv[5], sv[6], sv[7]
        if ci in seen or not (n >= 20 and wr >= 0.8 and pnl > 0 and 60 < hold < 999):
            continue
        seen.add(ci)
        c = coins[ci]
        lx = gl.lag(5, ci, ev_i % 997, "3-8")
        te = ag + lx
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(paths[ci], te)
        if p_in <= 0:
            continue
        x, to = one_x(paths[ci], te, lx, p_in, exit_)
        rows.append(dict(i=ci, t=c.t0 + te, tout=c.t0 + to, x=x, per=period_of(c.t0), te=te, lx=lx))
    return rows


def resim(coins, paths, trades, exit_):
    out = []
    for tr in trades:
        c, pa = coins[tr["i"]], paths[tr["i"]]
        p_in = gl.price_at_py(pa, tr["te"])
        if p_in <= 0:
            continue
        x, to = one_x(pa, tr["te"], tr["lx"], p_in, exit_)
        out.append(dict(tr, x=x, tout=c.t0 + to))
    return out


def combine_or(lists):
    best = {}
    for rows in lists:
        for t in rows:
            old = best.get(t["i"])
            if old is None or t["t"] < old["t"]:
                best[t["i"]] = t
    return list(best.values())


def combine_and(a, b, coins, paths, exit_):
    bb = {t["i"]: t for t in b}
    out = []
    for ta in a:
        tb = bb.get(ta["i"])
        if tb is None:
            continue
        later = ta if ta["t"] >= tb["t"] else tb
        c, pa = coins[later["i"]], paths[later["i"]]
        p_in = gl.price_at_py(pa, later["te"])
        if p_in <= 0:
            continue
        x, to = one_x(pa, later["te"], later["lx"], p_in, exit_)
        out.append(dict(later, x=x, tout=c.t0 + to))
    return out


def sim_book(trades, frac, maxpos, cap=200.0):
    eq, open_, peak, max_dd, n, wins, ruined = cap, [], cap, 0.0, 0, 0, False
    for t, x, tout in sorted((tr["t"], tr["x"], tr["tout"]) for tr in trades):
        still = []
        for te, st, xx in open_:
            if te <= t:
                eq += st * xx
            else:
                still.append((te, st, xx))
        open_ = still
        tot = eq + sum(s for _te, s, _x in open_)
        peak = max(peak, tot)
        if peak > 0:
            max_dd = max(max_dd, 1.0 - tot / peak)
        if tot < 40:
            ruined = True
        if len(open_) >= maxpos or tot < 1:
            continue
        st = min(eq, tot * frac)
        if st <= 0.05:
            continue
        eq -= st
        open_.append((tout, st, x))
        n += 1
        wins += int(x > 1)
    tot = eq + sum(s * xx for _te, s, xx in open_)
    peak = max(peak, tot)
    if peak > 0:
        max_dd = max(max_dd, 1.0 - tot / peak)
    if tot < 40:
        ruined = True
    return dict(end=float(tot), n_exec=int(n), wins=int(wins), max_dd=float(max_dd), ruined=bool(ruined))


def pack_slice(rows, per):
    xs = np.array([r["x"] for r in rows if r["per"] == per], np.float64)
    n = int(xs.size)
    base = dict(n=n, mean=None, win=None, wilson=[0.0, 0.0], nobest=None, books={})
    if n == 0:
        return base
    wins = int(np.sum(xs > 1))
    lo, hi = gl.wilson(wins, n)
    sub = [r for r in rows if r["per"] == per]
    books = {}
    for frac, mp in ((0.08, 1), (0.08, 5), (0.10, 1), (0.10, 5)):
        books[f"{int(frac*100)}% maks{mp}"] = sim_book(sub, frac, mp)
    base.update(mean=float(xs.mean()), win=wins / n, wilson=[float(lo), float(hi)], nobest=float(gl.nobest_of(xs)), books=books)
    return base


def classify(spec):
    lab = spec.get("filt") or spec.get("name") or ""
    exit_name = (spec.get("exit") or {}).get("name", "")
    if spec.get("mode") == "reentry":
        return "data", "masuk setelah penurunan dari puncak", "gerbang"
    if "copy>=" in lab or "smart>=" in lab:
        return "whale", "sinyal wallet pintar atau copy sebelum keputusan", "gerbang"
    if "devbuy" in lab:
        return "latar", "ukuran beli dev", "gerbang"
    if "jam " in lab:
        return "data", "filter jam lahir UTC", "gerbang"
    is_b = all(s in lab for s in ("growth>=3", "beli>=0.65", "vol>=3", "laju>=1.5")) and "dd bebas" in lab and "top10 bebas" in lab
    if is_b and exit_name != BASE_EXIT["name"]:
        return "jaga", "cara jual lain pada sinyal momentum (b)", "jaga"
    if spec.get("age", 999) <= 60 or spec.get("delay") in ("0.4", "1", "2"):
        return "data", "jalur masuk cepat", "cepat"
    if any(s in lab for s in ("dd<=", "top10<=", "holder", "dev belum", "rug")):
        return "rug", "filter konsentrasi, drawdown, atau dev sudah jual", "gerbang"
    return "data", "gerbang momentum", "gerbang"


def kelly_f(xs):
    xs = np.asarray(xs, np.float64)
    if xs.size < 5:
        return 0.05
    best, bestf = -1e9, 0.05
    for f in np.linspace(0.02, 0.40, 20):
        g = np.log(np.maximum(1e-9, 1.0 + f * (xs - 1.0))).mean()
        if g > best:
            best, bestf = float(g), float(f)
    return bestf


def ruin_p(trades, frac, maxpos, B=200):
    if len(trades) < 5:
        return None
    rng = np.random.default_rng(1)
    bad = 0
    idx = np.arange(len(trades))
    for _ in range(B):
        take = [trades[i] for i in rng.choice(idx, size=len(trades), replace=True)]
        if sim_book(take, frac, maxpos)["ruined"]:
            bad += 1
    return bad / B


def fmt_x(x):
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"{x:.3f}".replace(".", ",") + "x"


def fmt_pct(x):
    if x is None:
        return "—"
    return f"{100*x:.1f}%".replace(".", ",")


def fmt_money(book):
    if not book:
        return "—"
    return f"${book['end']:.0f} / DD {fmt_pct(book['max_dd'])}"


def table_rows(name, slices):
    lines = [f"| {name} | | | | | | | | | |"]
    for lab in ("A", "B", "C", "segar"):
        d = slices.get(lab) or {}
        if not d or not d.get("n"):
            lines.append(f"| | {lab} | 0 | — | — | — | — | — | — | — |")
            continue
        w = d.get("wilson") or [0, 0]
        b = d.get("books") or {}
        lines.append(
            f"| | {lab} | {d['n']} | {fmt_x(d.get('mean'))} | {fmt_pct(d.get('win'))} [{fmt_pct(w[0])}–{fmt_pct(w[1])}] | "
            f"{fmt_x(d.get('nobest'))} | {fmt_money(b.get('8% maks1'))} | {fmt_money(b.get('8% maks5'))} | "
            f"{fmt_money(b.get('10% maks1'))} | {fmt_money(b.get('10% maks5'))} |"
        )
    return lines


def slices_of(rows):
    return {lab: pack_slice(rows, p) for lab, p in (("A", 0), ("B", 1), ("C", 2), ("segar", 3))}


VOTE_BUDGET = 2.0  # detik. Agen yang belum bisa menjawab dihitung SKIP.


def agent_votes(c, path, info, t_cut):
    """Empat proksi dengan data sampai t_cut. Agen yang belum punya data = SKIP. Narasi tidak di sini."""
    info = info or {}
    sold = info.get("sold") or []
    buys_all = info.get("buys") or []
    dev_sold = any(a <= t_cut for a in sold)
    smart = float(len({w for a, w, sm in buys_all if sm and a <= t_cut}))
    trades = [w for w in c.w if w[0] <= t_cut]
    buys = [w for w in trades if w[2]]
    sells = [w for w in trades if not w[2]]
    devbuy = sum(s for ag, w, b, s in trades if b and w == c.dev and ag <= 1.0)
    # Belum ada trade sama sekali: agen belum menjawab.
    if not trades:
        return dict(rug=False, latar=False, data=False, whale=False)
    latar = bool(0 < devbuy < 2.0 and not dev_sold)
    buy_sol = sum(s for _a, _w, _b, s in buys)
    by = {}
    for _a, w, _b, s in buys:
        if w != c.dev:
            by[w] = by.get(w, 0.0) + s
    max_share = (max(by.values()) / buy_sol) if by and buy_sol > 0 else 1.0
    uniq = len({w for _a, w, _b, _s in buys if w != c.dev})
    rug = bool((not dev_sold) and uniq >= 3 and max_share <= 0.5 and len(trades) >= 2)
    p0 = gl.price_at_py(path, 0.4)
    pT = gl.price_at_py(path, t_cut)
    growth = (pT / p0) if p0 and p0 > 0 else 0.0
    bsr = len(buys) / max(1, len(buys) + len(sells))
    data = bool(growth >= 1.5 and bsr >= 0.65 and len(buys) >= 2)
    whale = bool(smart >= 1)
    return dict(rug=rug, latar=latar, data=data, whale=whale)


def sim_votes(coins, paths, ann, mode, wait, x_tol):
    """Tunggu `wait` detik untuk agen yang lambat (terutama narasi), lalu cek harga.

    Harga pertama di detik ke-2. Suara ditutup di detik 2+wait. Masuk hanya jika harga
    masih dalam ±x_tol dari harga pertama (None = tanpa batas), plus jeda eksekusi 1 dtk.
    mode skip: narasi SKIP, butuh 4/4. acc: narasi ACC, butuh >=3/4.
    uni: keempat proksi ACC dan narasi diasumsikan ACC (5/5).
    """
    rows = []
    lx = 1.0
    t0 = VOTE_BUDGET
    t1 = VOTE_BUDGET + float(wait)
    for i, c in enumerate(coins):
        flags = agent_votes(c, paths[i], ann[i], t1)
        n = sum(bool(v) for v in flags.values())
        if mode == "acc":
            ok = n >= 3
        else:
            ok = n >= 4
        if not ok:
            continue
        p_first = gl.price_at_py(paths[i], t0)
        p_now = gl.price_at_py(paths[i], t1)
        if p_first <= 0 or p_now <= 0:
            continue
        if x_tol is not None and abs(p_now / p_first - 1.0) > x_tol:
            continue
        te = t1 + lx
        if te >= c.end - 1:
            continue
        p_in = gl.price_at_py(paths[i], te)
        if p_in <= 0:
            continue
        x, to = one_x(paths[i], te, lx, p_in, BOM_EXIT)
        rows.append(dict(i=i, t=c.t0 + te, tout=c.t0 + to, x=x, per=period_of(c.t0), te=te, lx=lx))
    return rows


def run_portfolios(data, finalists):
    coins, paths, ann, meta = load_ready(data, need_all=True)
    book = {}
    for key, rule in (("a", RULE_A), ("b", RULE_B), ("c", RULE_C), ("mom", FAM_MOM), ("bom60", FAM_BOM)):
        print("sim", key, flush=True)
        book[key] = sim_rule(coins, paths, ann, rule)
    print("sim sniper, grad, copy", flush=True)
    sniper = sim_rule(coins, paths, ann, dict(mode="sniper", exit=dict(kind=0, tp=1.5, sl=0.9, T=30.0, arm=0, trail=0, tp2=0, w1=1, w2=0, name="TP1.5 SL0.9 30s")))
    grad = sim_rule(coins, paths, ann, dict(mode="grad", exit=dict(kind=1, tp=1e9, sl=0.7, T=1800.0, arm=0.5, trail=0.20, tp2=0, w1=1, w2=0, name="trail +50% lebar 20% SL0.7 1800s")))
    copy = sim_copy(coins, paths)
    print("sim suara agen", flush=True)
    votes = {}
    for wait in (1.0, 2.0, 3.0):
        for x_tol, xlab in ((0.10, "10%"), (0.15, "15%"), (0.25, "25%"), (None, "tanpa batas")):
            votes[(wait, xlab, "skip")] = sim_votes(coins, paths, ann, "skip", wait, x_tol)
            votes[(wait, xlab, "acc")] = sim_votes(coins, paths, ann, "acc", wait, x_tol)
            votes[(wait, xlab, "uni")] = sim_votes(coins, paths, ann, "uni", wait, x_tol)
            print(f"  tunggu {wait:.0f}s pita {xlab} n {len(votes[(wait, xlab, 'skip')])}/"
                  f"{len(votes[(wait, xlab, 'acc')])}/{len(votes[(wait, xlab, 'uni')])}", flush=True)
    ports = {
        "(1) Bom saja": book["c"],
        "(2) mom120 (a) saja, modul data": book["a"],
        "(3) aturan (b) saja, modul data": book["b"],
        "(4) Bom ATAU mom120": combine_or([book["c"], book["a"]]),
        "(5) Bom DAN mom120, waktu lebih akhir": combine_and(book["c"], book["a"], coins, paths, BOM_EXIT),
        "(6) OR modul keluarga": combine_or([book["mom"], book["bom60"], sniper, grad, copy]),
    }
    mods = []
    for spec in finalists:
        agent, task, how = classify(spec)
        print("sim finalis", spec.get("filt", "")[:60], flush=True)
        own = sim_rule(coins, paths, ann, spec)
        xs_b = np.array([r["x"] for r in own if r["per"] == 1], np.float64)
        spec["p_upper"] = boot_upper(xs_b)
        if how == "jaga":
            plus = resim(coins, paths, book["c"], spec["exit"])
        elif how == "cepat":
            plus = combine_or([book["c"], own])
        else:
            plus = combine_and(book["c"], own, coins, paths, BOM_EXIT)
        mods.append(dict(agent=agent, task=task, how=how, spec=spec, own=slices_of(own), plus=slices_of(plus)))
    if finalists:
        ports["(7) finalis amplifikasi terbaik"] = sim_rule(coins, paths, ann, finalists[0])
    else:
        ports["(7) finalis amplifikasi terbaik"] = []
    for wait in (1.0, 2.0, 3.0):
        for xlab in ("10%", "15%", "25%", "tanpa batas"):
            ports[f"(8) suara 4/4 narasi-SKIP, tunggu {wait:.0f}s, pita {xlab}"] = votes[(wait, xlab, "skip")]
            ports[f"(9) suara ≥3/4 narasi-ACC, tunggu {wait:.0f}s, pita {xlab}"] = votes[(wait, xlab, "acc")]
            ports[f"(10) suara 5/5 narasi-ACC, tunggu {wait:.0f}s, pita {xlab}"] = votes[(wait, xlab, "uni")]
    return dict(meta=meta, ports={k: slices_of(v) for k, v in ports.items()}, modules=mods,
                n_fresh=sum(1 for c in coins if c.t0 > CLEAN_AFTER))


def opening(merged, ports):
    nulls = merged["null"]
    nmax = max(nulls) if nulls else 0
    nmean = sum(nulls) / len(nulls) if nulls else 0
    finals = merged["finalists"]
    k = merged["k"]
    thr = 0.05 / k if k else None
    cleared = [f for f in finals if f.get("p_upper") is not None and thr and f["p_upper"] < thr]
    fresh_n = ports.get("n_fresh") or 0
    fresh_ok = False
    if fresh_n and ports.get("modules"):
        fresh_ok = any((m["own"].get("segar") or {}).get("n", 0) >= NMIN
                       and ((m["own"]["segar"].get("mean") or 0) > 1)
                       and ((m["own"]["segar"].get("nobest") or 0) > 1) for m in ports["modules"])
    if not finals:
        line = (f"TIDAK LAYAK. Tidak ada modul yang lolos B (n_B≥30, rata B>1, B tanpa koin terbaik >1). "
                f"Kombinasi {k}, lulus A+B {merged['real_pass']}, null rata {nmean:.2f} maks {nmax}. "
                f"C tercemar dan bukan dasar memilih.")
    elif not (merged["real_pass"] > nmax):
        line = (f"TIDAK LAYAK. Ada {len(finals)} calon yang lolos B, tetapi jumlah lulus {merged['real_pass']} "
                f"tidak di atas null maks {nmax}. Koreksi Bonferroni {thr}.")
    elif not cleared:
        line = (f"TIDAK LAYAK DIPAKAI. {len(finals)} modul lolos B dan jumlah lulus di atas null, "
                f"tetapi tidak ada yang p-nya di bawah Bonferroni {thr:.3g}. C tercemar.")
    elif not fresh_n:
        line = ("BELUM TERKONFIRMASI. Ada modul yang lolos A+B dan koreksi, tetapi belum ada koin perekam "
                "sesudah 10 Nov 07:17 UTC untuk uji bersih.")
    elif not fresh_ok:
        line = "TIDAK LAYAK. Lolos A+B dan koreksi, tetapi data segar sesudah 10 Nov 07:17 UTC tidak mengkonfirmasi."
    else:
        line = "KANDIDAT PAPER saja. Modul lolos A+B, null, koreksi, dan data segar. Bukan untuk live."
    return line


def render(merged, pack):
    L = [opening(merged, pack), "",
         "# Amplifikasi tepi aturan (b) sebagai modul Bom, 10 Nov 2026, PAPER", "",
         "Cuma ada satu arsitektur: tim agen Bom. Strategi lain di bawah ini calon tugas agen, bukan bot kedua.",
         "Narasi X tidak ada di data perekam, jadi aturan Bom di backtest tidak punya cek narasi.",
         "",
         "## Perbandingan portofolio",
         "",
         "A dan B dipakai untuk menilai. C sudah pernah dilihat (tercemar). Segar = koin lahir sesudah 10 Nov 07:17 UTC, kalau ada.",
         "Angka $ adalah saldo akhir dari $200, plus penurunan maksimum (DD) di jalur itu.",
         "Suara: lima agen, masuk kalau minimal 4 ACC. Agen yang terlambat tidak langsung SKIP: ditunggu 1, 2, atau 3 detik di atas cek pertama (detik ke-2), terutama untuk narasi.",
         "Setelah suara cukup, harga dicek lagi. Masuk hanya kalau harga masih dalam ±10%, ±15%, ±25%, atau tanpa batas, dari harga cek pertama. Kalau sudah pump atau dump melewati pita, SKIP. Lalu jeda eksekusi 1 detik. Jual tetap jaga Bom.",
         "Narasi tidak bisa diuji. Narasi-SKIP berarti butuh 4/4 proksi. Narasi-ACC berarti butuh minimal 3/4. Baris 5/5 sama dengan 4/4 karena narasi hanya bisa diasumsikan ACC, tidak diukur. Kalau narasi tidak menjawab sama sekali, 5/5 tidak pernah terjadi.",
         "Proksi sampai waktu tunggu selesai: rug = dev belum jual, pembeli unik selain dev ≥3, beli terbesar ≤50%. Latar = beli dev 0–2 SOL dan belum jual. Data = harga ≥1,5x dari detik 0,4 dan rasio beli ≥65%. Whale = ada wallet pintar yang sudah beli.",
         "",
         "| Portofolio | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8% maks1 / DD | 8% maks5 / DD | 10% maks1 / DD | 10% maks5 / DD |",
         "|---|---|---:|---:|---|---:|---|---|---|---|"]
    for name, sl in pack["ports"].items():
        L += table_rows(name, sl)
    L += ["", "### Bom saja lawan Bom + modul", ""]
    L += ["| Modul | Agen | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8% maks1 / DD | 8% maks5 / DD | 10% maks1 / DD | 10% maks5 / DD |",
          "|---|---|---|---:|---:|---|---:|---|---|---|---|"]
    L += table_rows("Bom saja", pack["ports"]["(1) Bom saja"])
    for m in pack["modules"]:
        spec = m["spec"]
        title = f"Bom+{m['agent']}: {spec.get('filt','')[:80]} | {spec.get('exit',{}).get('name','')}"
        L.append(f"| {title} | {m['agent']}: {m['task']} ({m['how']}) | | | | | | | | | |")
        L += table_rows("", m["plus"])
    L += ["",
          "Gerbang (data, whale, rug, latar): koin harus lolos Bom dan modul, masuk di waktu yang lebih lambat, jual tetap jaga Bom (TP3 SL0,5 600 dtk).",
          "Jalur cepat: Bom ATAU modul, masuk di sinyal pertama, masing-masing pakai cara jualnya sendiri.",
          "Jaga: masuk tetap sinyal Bom, cara jual diganti milik modul.",
          "",
          "## Modul kandidat untuk Bom v2", ""]
    if not pack["modules"]:
        L.append("Tidak ada finalis yang lolos B. Tidak ada modul yang dikunci.")
    for i, m in enumerate(pack["modules"], 1):
        s = m["spec"]
        L.append(f"### {i}. Agen {m['agent']}")
        L.append(f"- Tugas: {m['task']}.")
        L.append(f"- Sinyal: {s.get('mode')} umur {s.get('age')} jeda {s.get('delay')} dip {s.get('dip')}.")
        L.append(f"- Filter: {s.get('filt')}.")
        L.append(f"- Jual: {s.get('exit',{}).get('name')}.")
        L.append(f"- A n={s.get('nA')} rata {fmt_x(s.get('meanA'))}; B n={s.get('nB')} rata {fmt_x(s.get('meanB'))} tanpa terbaik {fmt_x(s.get('nobestB'))}.")
        if s.get("p_upper") is not None:
            L.append(f"- p bootstrap B (batas atas) {s['p_upper']:.4g}. Ambang Bonferroni {merged['thr']:.4g}.")
        L.append("- Hasil Bom+modul ada di tabel atas. C tercemar.")
        seg = (m["own"].get("segar") or {})
        if seg.get("n"):
            L.append(f"- Data segar: n={seg['n']} rata {fmt_x(seg.get('mean'))} tanpa terbaik {fmt_x(seg.get('nobest'))}.")
        else:
            L.append("- Data segar: belum ada koin sesudah 10 Nov 07:17 UTC.")
        L.append("")
    L += ["## Pencarian",
          f"- Kombinasi {merged['k']}. Lulus A+B {merged['real_pass']}.",
          f"- Null 20x: {', '.join(str(int(x)) for x in merged['null'])}.",
          f"- Cache: `{pack['meta'].get('cache_key') or '—'}`; koin dimuat {pack['meta'].get('n_std')}; segar {pack['n_fresh']}.",
          "- Ukuran posisi di tabel adalah 8% dan 10% saldo, majemuk, maks 1 dan 5. Kelly dihitung dari trade A saja, lalu dicek di B, tidak dipakai memilih modul.",
          ""]
    if pack["modules"]:
        spec = pack["modules"][0]["spec"]
        own = pack["modules"][0]["own"]
        xs_note = own.get("A") or {}
        L.append(f"Kelly finalis pertama (dari rata log di A) dilaporkan di JSON. DD ada di kolom saldo.")
        L.append("")
    L += ["## Yang ditolak di A (gagal B atau bukan 5 teratas)", ""]
    for r in merged.get("top_a", [])[:8]:
        L.append(f"- {r.get('mode')} D{r.get('age')} jeda {r.get('delay')} {r.get('filt')} | {r.get('exit',{}).get('name')} "
                 f"A {fmt_x(r.get('meanA'))} (n={r.get('nA')}) B {fmt_x(r.get('meanB'))} (n={r.get('nB')})")
    L += ["", "Paper saja. Jangan dipakai live.", ""]
    return "\n".join(L)


def boot_upper(xs, B=4000):
    xs = np.asarray(xs, np.float64)
    if xs.size < 5:
        return None
    rng = np.random.default_rng(1)
    # batch kecil
    bad = 0
    left = B
    while left:
        b = min(200, left)
        idx = rng.integers(0, xs.size, size=(b, xs.size))
        bad += int(np.sum(xs[idx].mean(1) <= 1.0))
        left -= b
    p = bad / B
    return p if p > 0 else 1.0 / B


def merge_parts(docs):
    k = sum(int(d["combos"]) for d in docs)
    real = sum(int(d["real_pass"]) for d in docs)
    null = None
    top_a, passed = [], []
    for d in docs:
        n = d.get("null") or []
        if null is None:
            null = [0] * len(n)
        for i, v in enumerate(n):
            null[i] += int(v)
        top_a.extend(d.get("top_a") or [])
        passed.extend(d.get("passed") or [])
    passed.sort(key=lambda r: r.get("meanA") or -1, reverse=True)
    finals, seen = [], set()
    for r in passed:
        sig = (r.get("mode"), r.get("age"), r.get("delay"), r.get("dip"), r.get("filt"), (r.get("exit") or {}).get("name"))
        if sig in seen:
            continue
        seen.add(sig)
        r["pass_b"] = True
        finals.append(r)
        if len(finals) >= 5:
            break
    top_a.sort(key=lambda r: r.get("meanA") or -1, reverse=True)
    return dict(k=k, real_pass=real, null=null or [], finalists=finals, top_a=top_a[:12],
                thr=(0.05 / k) if k else None)


def attach_p(coins, paths, ann, finals):
    for spec in finals:
        rows = sim_rule(coins, paths, ann, spec)
        xs = np.array([r["x"] for r in rows if r["per"] == 1], np.float64)
        spec["p_upper"] = boot_upper(xs)
    return finals


def run_report(data, parts_root, dest):
    docs = []
    for dirpath, _d, files in os.walk(parts_root):
        for fn in files:
            if fn == "amplify_part.json":
                with open(os.path.join(dirpath, fn)) as f:
                    docs.append(json.load(f))
    if not docs:
        raise SystemExit("tidak ada amplify_part.json")
    merged = merge_parts(docs)
    print(f"gabung {len(docs)} bagian, kombinasi {merged['k']}, finalis {len(merged['finalists'])}", flush=True)
    pack = run_portfolios(data, merged["finalists"])
    text = render(merged, pack)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w") as f:
        f.write(text)
    print(text, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("search", "reentry", "report", "self-test"), default="search")
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="out")
    ap.add_argument("--ages", default="120")
    ap.add_argument("--null", type=int, default=20)
    ap.add_argument("--parts", default="hasil")
    ap.add_argument("--report", default="riset/riset-amplify-b-2026-11-10.md")
    a = ap.parse_args(argv)
    if a.mode == "self-test":
        self_test()
        return
    if a.mode == "report":
        run_report(a.data, a.parts, a.report)
        return
    ages = tuple(int(x) for x in a.ages.split(",") if x.strip())
    run_search(a.data, ages, a.out, a.null, reentry=(a.mode == "reentry"))


def self_test():
    gl._need_numba()
    assert abs(gl.lag(3, 5, 120, "3-8") - lag_of(3, 5, 120, "3-8")) < 1e-12
    specs = all_specs()
    assert any("growth>=3" in lab and "beli>=0.65" in lab and "vol>=3" in lab for lab, _c in specs)
    # portofolio OR/AND pada trade palsu
    coins = [type("C", (), {"t0": 0, "end": 100})() for _ in range(2)]
    # tanpa path: uji combine_or saja
    a = [dict(i=0, t=10, tout=20, x=1.2, per=0, te=10, lx=1)]
    b = [dict(i=0, t=12, tout=30, x=0.8, per=0, te=12, lx=1), dict(i=1, t=5, tout=8, x=1.5, per=0, te=5, lx=0.4)]
    orr = combine_or([a, b])
    assert {t["i"]: t["t"] for t in orr}[0] == 10 and {t["i"]: t["t"] for t in orr}[1] == 5
    book = sim_book([dict(t=1, x=1.2, tout=2), dict(t=3, x=0.5, tout=4)], 0.10, 1)
    assert book["end"] < 200 and book["max_dd"] > 0
    agent, _task, how = classify(dict(mode="snap", age=120, delay="3-8", filt="growth>=3 beli>=0.65 vol>=3 laju>=1.5 dd bebas top10 bebas",
                                      exit=dict(name="TP2 SL0.7 600s")))
    assert agent == "jaga" and how == "jaga"
    print("self-test OK", len(specs), "filter", len(std_exits()) + len(leg_exits()), "exit")


if __name__ == "__main__":
    main()


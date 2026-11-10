"""Pencarian luas strategi pump.fun. PAPER. Ditulis sebelum hasil (praregistrasi).

DATA: rekaman memescan rec-*.jsonl di cache Actions. Trade didedupe karena RPC publik
mengirim transaksi yang sama dua kali, sementara perekam GitHub TIDAK menyimpan signature.
Kunci dedupe (pengganti signature): wallet 10 huruf + sisi + SOL (3 angka penting) + umur
selisih <= 0,3 detik (di bawah 1 slot). Trade 0,4 detik atau lebih tetap dihitung dua.
Kurva tidak standar dibuang (aturan yang sama dengan riset/bevan.py).

BIAYA: fee 1,25%/sisi, slippage 2%/sisi, priority 0,0005 SOL, ukuran 0,1 SOL, dampak kurva.
Stop dari candle diisi di level stop x 0,72. Stop/TP dari tick diisi di harga setelah jeda
yang sama. Di dalam satu candle: batas waktu, lalu ikut-jual, lalu stop, baru TP.
Parsial 50%: dua jual, priority dihitung 3 transaksi, dampak kurva pakai setengah ukuran.

JEDA: 0,4 dtk / 1 dtk / 3–8 dtk (angka 3–8 deterministik per koin dari hash, seragam).

KELUARGA (seleksi hanya di A; ini daftar yang diuji, bukan hasil):
  Sniper: masuk setelah trade pertama. Filter dev-buy SOL.
  Bom: keputusan di umur 30/60/180/300 dtk. Filter dev jual, top10, pembeli unik, mcap,
    likuiditas, holder, dev-buy, jumlah wallet "pintar", pembuat pernah rug (hanya yang
    terekam perekam). Wallet pintar = kausal, >=5 koin selesai sebelum belinya, menang
    >=60%, total untung >0.
  Momentum: umur 10/30/60/120/300. Growth, rasio beli, drawdown, lonjakan inflow sejak
    snapshot sebelumnya, kecepatan pembeli, top10.
  Graduation: mcap pertama kali menyentuh 50/70/85/92/98% kurva. Umur sinyal.
  Copy: statistik wallet kausal (min koin, winrate, untung>0, hold, jendela 6 jam).
    1 entri per koin (beli pertama yang lolos).

KELUAR: TP/SL/waktu, trailing, parsial 50%, tahan sampai rekaman habis, ikut jual (copy).

PROTOKOL: urut t0, A 50% / B 20% / C 30%. Pilih 5 cara teratas menurut rata A (n_A>=30),
buang cara jual yang trade-nya identik di A. B>1 baru diuji sekali di C.
LULUS ekonomi: n_C>=30, rata A,B,C >1, C tanpa koin terbaik >1.
NULL: 20x acak baris fitur, hitung jumlah lulus. Lulus harus lebih banyak dari null.
KOREKSI: finalis C wajib p bootstrap satu sisi < 0,05/jumlah kombinasi.
Top 10 menurut C tanpa koin terbaik dilaporkan walau gagal, dan TIDAK dipakai memilih.

Pakai: python3 riset/grid_luas.py --data data --sample 30000 --out riset
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import traceback

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import kol  # noqa: E402
import memescan as ms  # noqa: E402

try:
    from numba import njit
except ImportError:
    njit = None

FEE, SLIP, PRIO, SIZE, STOPFILL = 0.0125, 0.02, 0.0005, 0.1, 0.72
K_CURVE = 30.0 * 1.073e9 / 1e9
DELAYS = ("0.4", "1", "3-8")
AGES_BOM = (30, 60, 180, 300)
AGES_MOM = (10, 30, 60, 120, 300)
GRAD_PC = (50, 70, 85, 92, 98)
SMART_N, SMART_WR = 5, 0.60
PREV_SNAP = {10: None, 30: 10, 60: 30, 120: 60, 180: 120, 300: 180}
FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}
N_FEAT = 14


def lag(kind, i, D, which):
    if which == "0.4":
        return 0.4
    if which == "1":
        return 1.0
    h = (int(i) * 1000003 + int(D) * 9176 + int(kind) * 13) & 0xFFFFFFFF
    return 3.0 + (h % 10000) / 10000.0 * 5.0


def dedupe_trades(w, gap=0.3):
    last = {}
    out = []
    n = 0
    for row in w:
        ag, wallet, side, sol = float(row[0]), str(row[1]), int(row[2]), float(row[3])
        key = (wallet, side, sol)
        prev = last.get(key)
        if prev is not None and abs(ag - prev) <= gap:
            n += 1
            continue
        last[key] = ag
        out.append((ag, wallet, side, sol))
    out.sort(key=lambda r: r[0])
    return out, n


class Coin:
    __slots__ = ("t0", "end", "m0", "cs", "starts", "w", "cov", "dev", "snaps",
                 "devbuy", "dev_sold", "smart", "i", "full_i")


def _std(cs, snaps):
    tb = math.inf
    for _s, end, _hi, lo, _cl in cs:
        if lo < kol.FLOOR_MCAP:
            tb = min(tb, end)
    for s in snaps:
        if float(s[1]) < kol.FLOOR_MCAP:
            tb = min(tb, float(s[0]))
    kb = kf = ib = math.inf
    for sn in snaps:
        liq, mc, ag = float(sn[FI["liq_sol"]]), float(sn[1]), float(sn[0])
        if sn[FI["inflow_sol"]] == 0 and sn[FI["growth"]] > 1.05:
            ib = min(ib, ag)
        if liq >= 79 or mc <= 0:
            continue
        kf = min(kf, ag)
        if abs((30 + liq) ** 2 * 1e9 / mc / 3.219e10 - 1) > 0.08:
            kb = min(kb, ag)
    return min(kb, ib) == math.inf and tb == math.inf and kf < math.inf


def load_coins(data_dir):
    d = os.path.join(data_dir, "rec")
    if not os.path.isdir(d):
        raise SystemExit(f"Tidak ada folder rekaman: {d}")
    meta = dict(n_lines=0, n_with_w=0, n_std=0, n_dup_rows=0, n_coins_dup=0,
                t_min=None, t_max=None)
    coins = []
    files = sorted(fn for fn in os.listdir(d) if fn.startswith("rec-") and fn.endswith(".jsonl"))
    if not files:
        raise SystemExit(f"Tidak ada rec-*.jsonl di {d}")
    for fn in files:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                meta["n_lines"] += 1
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                t0 = float(r.get("t0") or 0)
                if meta["t_min"] is None or t0 < meta["t_min"]:
                    meta["t_min"] = t0
                if meta["t_max"] is None or t0 > meta["t_max"]:
                    meta["t_max"] = t0
                raw_w = r.get("w") or []
                if not raw_w or not r.get("c"):
                    continue
                meta["n_with_w"] += 1
                w, nd = dedupe_trades(raw_w)
                meta["n_dup_rows"] += nd
                if nd:
                    meta["n_coins_dup"] += 1
                if not w:
                    continue
                cs = []
                for x in r["c"]:
                    b = int(x[0])
                    cs.append((ms.rec_bucket_start(b), ms.rec_bucket_end(b),
                               float(x[1]), float(x[2]), float(x[3])))
                if not cs:
                    continue
                m0 = float(r.get("m0") or r["snaps"][0][1])
                if m0 <= 0 or not _std(cs, r.get("snaps") or []):
                    continue
                c = Coin()
                c.t0, c.end, c.m0 = t0, float(r["end"]), m0
                c.cs, c.starts, c.w = cs, [x[0] for x in cs], w
                c.dev = r.get("dev") or ""
                raw_n = len(raw_w)
                # cov mengikuti jumlah MENTAH (perekam berhenti di 150 baris, termasuk duplikat)
                c.cov = float(raw_w[-1][0]) if raw_n >= ms.REC_W_MAX else min(ms.REC_W_AGE, c.end)
                t_first = w[0][0]
                c.devbuy = sum(s for ag, wallet, b, s in w
                               if b and wallet == c.dev and ag <= t_first + 0.2)
                c.snaps = {int(s[0]): s for s in (r.get("snaps") or [])}
                c.dev_sold = {}
                c.smart = {}
                c.i = 0
                coins.append(c)
                meta["n_std"] += 1
        print(f"muat {fn}: std {meta['n_std']} / baris {meta['n_lines']}", flush=True)
    coins.sort(key=lambda c: c.t0)
    meta["files"] = files
    return coins, meta


def sample_index(n, k):
    """Indeks sampel merata. k<=0 atau k>=n berarti semua. Sama dengan lari 30.000 kemarin."""
    if k <= 0 or n <= k:
        return np.arange(n)
    return np.unique(np.round(np.linspace(0, n - 1, k)).astype(int))


def take_sample(coins, n):
    idx = sample_index(len(coins), n)
    if len(idx) == len(coins):
        return coins
    return [coins[int(i)] for i in idx]


def extract_path(c):
    p = kol.Path(c, 0)
    bt, bh, bl, bx = [], [], [], []
    for t, _cl, hi, lo in p.points(-1.0):
        bt.append(float(t))
        bh.append(float(hi))
        bl.append(float(lo))
        bx.append(1 if hi == lo else 0)
    return {
        "bar_t": np.asarray(bt, np.float64),
        "bar_hi": np.asarray(bh, np.float64),
        "bar_lo": np.asarray(bl, np.float64),
        "bar_tick": np.asarray(bx, np.int8),
        "tick_t": np.asarray([float(a) for a, _ in p.tt], np.float64),
        "tick_px": np.asarray(list(p.tp), np.float64),
        "anchor": float(p.anchor),
        "cov": float(c.cov),
        "cs_start": np.asarray([float(x[0]) for x in c.cs], np.float64),
        "cs_close": np.asarray([float(x[4]) for x in c.cs], np.float64),
        "m0": float(c.m0),
        "end": float(c.end),
    }


def _summ(hh, window, now):
    if window:
        hh = [x for x in hh if x[0] >= now - window]
    if not hh:
        return (0.0, 0.0, 0.0, 999.0)
    n = len(hh)
    return (float(n), sum(x[1] for x in hh) / n, sum(x[2] for x in hh),
            float(np.median([x[3] for x in hh])))


def prepare(coins):
    """Isi devbuy / dev_sold / smart, dan kembalikan event copy (kausal)."""
    done = []
    for c in coins:
        per = {}
        if c.w:
            t_first = c.w[0][0]
            db = 0.0
            for ag, w, b, s in c.w:
                if b and w == c.dev and ag <= t_first + 0.2:
                    db += s
            c.devbuy = db
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
    done.sort(key=lambda x: x[0])
    hist = {}
    ptr = 0
    events = []

    def advance(to_t):
        nonlocal ptr
        while ptr < len(done) and done[ptr][0] <= to_t:
            t, w, win, pnl, hold = done[ptr]
            hist.setdefault(w, []).append((t, win, pnl, hold))
            ptr += 1

    for c in coins:
        sold = []
        buys = []
        seen = set()
        for ag, w, b, s in c.w:
            advance(c.t0 + ag)
            if (not b) and w == c.dev and s > 0:
                sold.append(ag)
            if not b:
                continue
            h = hist.get(w) or ()
            n = len(h)
            is_smart = False
            if n >= SMART_N:
                wr = sum(x[1] for x in h) / n
                pnl = sum(x[2] for x in h)
                is_smart = wr >= SMART_WR and pnl > 0
            buys.append((ag, w, is_smart))
            if w in seen or n < SMART_N:
                continue
            seen.add(w)
            fol = -1.0
            for a2, w2, b2, _s2 in c.w:
                if w2 == w and not b2 and a2 > ag:
                    fol = float(a2)
                    break
            sv = _summ(h, None, c.t0 + ag) + _summ(h, 6 * 3600.0, c.t0 + ag)
            events.append((c.i, float(ag), c.t0 + ag, fol, sv))
        for D in (10, 30, 60, 120, 180, 300):
            c.dev_sold[D] = 1.0 if any(a <= D for a in sold) else 0.0
            c.smart[D] = float(len({w for a, w, sm in buys if a <= D and sm}))
    print(f"siap: event copy ber-riwayat >=5: {len(events)}", flush=True)
    return events


def feat_row(c, D):
    sn = c.snaps.get(D)
    if sn is None:
        return None

    def g(name):
        return float(sn[FI[name]])

    prev = PREV_SNAP.get(D)
    vol = g("inflow_sol")
    if prev is not None and prev in c.snaps:
        vol = vol - float(c.snaps[prev][FI["inflow_sol"]])
    return np.array([
        float(sn[1]), g("top10"), g("unique_buyers"), g("holders"), g("liq_sol"),
        float(c.dev_sold.get(D, 0.0)), float(c.devbuy), float(c.smart.get(D, 0.0)),
        g("creator_prev_rugs"), g("growth"), g("buy_sell_ratio"), g("drawdown"),
        float(vol), g("buyer_rate"),
    ], np.float64)


def make_exits(with_follow=False):
    ex = []
    for tp in (1.5, 2.0, 3.0):
        for sl in (0.5, 0.7, 0.9):
            for T in (30, 120, 600):
                ex.append(dict(kind=0, tp=tp, sl=sl, T=T, arm=0.0, trail=0.0, tp2=0.0,
                               name=f"TP{tp:g} SL{sl:g} {T}s"))
    for arm in (0.5, 1.0):
        for tr in (0.20, 0.35):
            for T in (300, 1800):
                ex.append(dict(kind=1, tp=1e9, sl=0.7, T=T, arm=arm, trail=tr, tp2=0.0,
                               name=f"trail +{arm:.0%} lebar {tr:.0%} SL0.7 {T}s"))
    for tp1 in (1.5, 2.0):
        for tp2 in (3.0, 5.0):
            ex.append(dict(kind=2, tp=tp1, sl=0.7, T=600, arm=0.0, trail=0.0, tp2=tp2,
                           name=f"parsial 50% {tp1:g}x sisa TP{tp2:g} SL0.7 600s"))
    ex.append(dict(kind=0, tp=1e9, sl=0.0, T=1800, arm=0.0, trail=0.0, tp2=0.0,
                   name="tahan sampai habis"))
    for T in (60, 300):
        ex.append(dict(kind=0, tp=1e9, sl=0.7, T=T, arm=0.0, trail=0.0, tp2=0.0,
                       name=f"tanpa TP SL0.7 {T}s"))
    if with_follow:
        for sl in (0.0, 0.5, 0.7):
            ex.append(dict(kind=3, tp=1e9, sl=sl, T=1800, arm=0.0, trail=0.0, tp2=0.0,
                           name=f"ikut jual SL{sl:g}"))
    return ex


def exits_arrays(exits):
    return (
        np.array([e["tp"] for e in exits], np.float64),
        np.array([e["sl"] for e in exits], np.float64),
        np.array([e["T"] for e in exits], np.float64),
        np.array([e["kind"] for e in exits], np.int8),
        np.array([e["arm"] for e in exits], np.float64),
        np.array([e["trail"] for e in exits], np.float64),
        np.array([e["tp2"] for e in exits], np.float64),
    )


def _need_numba():
    if njit is None:
        raise SystemExit("Butuh numba: pip install numba")


if njit is not None:
    @njit(cache=True)
    def _price_at(t, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0):
        if t <= cov:
            n = tick_t.shape[0]
            if n == 0:
                return anchor
            k = np.searchsorted(tick_t, t, side="right") - 1
            if k >= 0:
                return tick_px[k]
            return anchor
        n = cs_start.shape[0]
        if n == 0:
            return m0
        k = np.searchsorted(cs_start, t, side="right") - 1
        if k >= 0:
            return cs_close[k]
        return m0

    @njit(cache=True)
    def _sim(bar_t, bar_hi, bar_lo, bar_tick, tick_t, tick_px, anchor, cov,
             cs_start, cs_close, m0, end_t, te, lx, p_in, fol,
             tp, sl, T, kind, arm, trail, tp2):
        n = tp.shape[0]
        p1 = np.empty(n, np.float64)
        p2 = np.empty(n, np.float64)
        tout = np.empty(n, np.float64)
        split = np.zeros(n, np.int8)
        alive = np.ones(n, np.int8)
        half = np.zeros(n, np.int8)
        peak = np.full(n, p_in)
        armed = np.zeros(n, np.int8)
        nbar = bar_t.shape[0]
        i0 = np.searchsorted(bar_t, te, side="right") if nbar else 0
        for i in range(i0, nbar):
            t = bar_t[i]
            hi = bar_hi[i]
            lo = bar_lo[i]
            tick = bar_tick[i]
            any_alive = False
            for k in range(n):
                if alive[k] == 0:
                    continue
                any_alive = True
                tl = te + T[k]
                if t >= tl:
                    px = _price_at(tl + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                    if half[k] == 1:
                        p2[k] = px
                        split[k] = 1
                    else:
                        p1[k] = px
                        p2[k] = px
                    tout[k] = tl + lx
                    alive[k] = 0
                    continue
                if kind[k] == 3 and fol >= 0.0 and t >= fol:
                    px = _price_at(fol + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                    p1[k] = px
                    p2[k] = px
                    tout[k] = fol + lx
                    alive[k] = 0
                    continue
                slv = sl[k]
                sl_px = p_in * slv if slv > 0.0 else -1.0
                if kind[k] == 1 and armed[k] == 1:
                    tr_px = peak[k] * (1.0 - trail[k])
                    if tr_px > sl_px:
                        sl_px = tr_px
                if sl_px > 0.0 and lo <= sl_px:
                    if tick == 1:
                        px = _price_at(t + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                        if px > sl_px:
                            px = sl_px
                    else:
                        px = sl_px * 0.72
                    if half[k] == 1:
                        p2[k] = px
                        split[k] = 1
                    else:
                        p1[k] = px
                        p2[k] = px
                    tout[k] = t + lx
                    alive[k] = 0
                    continue
                kk = kind[k]
                if kk == 2:
                    tp1 = p_in * tp[k]
                    tp2v = p_in * tp2[k]
                    if half[k] == 0 and hi >= tp1:
                        if tick == 1:
                            px = _price_at(t + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                        else:
                            px = tp1
                        p1[k] = px
                        half[k] = 1
                        tout[k] = t + lx
                        if hi >= tp2v:
                            if tick == 1:
                                p2[k] = px
                            else:
                                p2[k] = tp2v
                            split[k] = 1
                            alive[k] = 0
                    elif half[k] == 1 and hi >= tp2v:
                        if tick == 1:
                            p2[k] = _price_at(t + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                        else:
                            p2[k] = tp2v
                        split[k] = 1
                        tout[k] = t + lx
                        alive[k] = 0
                elif kk == 0 and tp[k] < 1e8 and hi >= p_in * tp[k]:
                    level = p_in * tp[k]
                    if tick == 1:
                        px = _price_at(t + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                    else:
                        px = level
                    p1[k] = px
                    p2[k] = px
                    tout[k] = t + lx
                    alive[k] = 0
                if alive[k] == 1:
                    if hi > peak[k]:
                        peak[k] = hi
                    if kk == 1 and peak[k] >= p_in * (1.0 + arm[k]):
                        armed[k] = 1
            if not any_alive:
                break
        for k in range(n):
            if alive[k] == 0:
                continue
            if kind[k] == 3 and fol >= 0.0 and fol < end_t and fol > te:
                px = _price_at(fol + lx, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
                p1[k] = px
                p2[k] = px
                tout[k] = fol + lx
                continue
            px = _price_at(end_t, tick_t, tick_px, anchor, cov, cs_start, cs_close, m0)
            if half[k] == 1:
                p2[k] = px
                split[k] = 1
            else:
                p1[k] = px
                p2[k] = px
            tout[k] = end_t
        return p1, p2, split, tout
else:
    def _price_at(*_a, **_k):
        raise SystemExit("Butuh numba")

    def _sim(*_a, **_k):
        raise SystemExit("Butuh numba")


def price_at_py(pa, t):
    return float(_price_at(float(t), pa["tick_t"], pa["tick_px"], pa["anchor"], pa["cov"],
                           pa["cs_start"], pa["cs_close"], pa["m0"]))


def apply_costs(p_in, p1, p2, split):
    p1 = np.asarray(p1, np.float64)
    p2 = np.asarray(p2, np.float64)
    split = np.asarray(split)
    out = np.empty(p1.shape[0], np.float32)
    vs_in = math.sqrt(K_CURVE * max(p_in, 1e-9))
    e = p_in * (1.0 + SIZE / vs_in) / ((1.0 - FEE) * (1.0 - SLIP))

    def proc(p, sz):
        vs = np.sqrt(K_CURVE * np.maximum(p, 1e-9))
        return p * (1.0 - FEE) * (1.0 - SLIP) / (1.0 + sz / vs)

    normal = split == 0
    if np.any(normal):
        out[normal] = np.maximum(0.0, proc(p1[normal], SIZE) / e - 2.0 * PRIO / SIZE)
    part = ~normal
    if np.any(part):
        s = 0.5 * proc(p1[part], SIZE / 2.0) + 0.5 * proc(p2[part], SIZE / 2.0)
        out[part] = np.maximum(0.0, s / e - 3.0 * PRIO / SIZE)
    return out


def sim_one(pa, te, lx, p_in, arrays, fol):
    tp, sl, T, kind, arm, trail, tp2 = arrays
    return _sim(pa["bar_t"], pa["bar_hi"], pa["bar_lo"], pa["bar_tick"],
                pa["tick_t"], pa["tick_px"], pa["anchor"], pa["cov"],
                pa["cs_start"], pa["cs_close"], pa["m0"], pa["end"],
                float(te), float(lx), float(p_in), float(fol),
                tp, sl, T, kind, arm, trail, tp2)


class Group:
    def __init__(self, family, name, F, X, per, tin, tout, specs, exits, copy=False, ci=None):
        self.family = family
        self.name = name
        self.F = np.asarray(F, np.float64)
        self.X = np.asarray(X, np.float32)
        self.per = np.asarray(per, np.int8)
        self.tin = np.asarray(tin, np.float64)
        self.tout = np.asarray(tout, np.float64)
        self.specs = specs
        self.exits = exits
        self.copy = copy
        self.ci = None if ci is None else np.asarray(ci, np.int32)


def _axis_mask(F, conds):
    m = np.ones(F.shape[0], dtype=bool)
    for col, op, val in conds:
        x = F[:, col]
        if op == ">=":
            m &= x >= val
        elif op == "<=":
            m &= x <= val
        elif op == ">":
            m &= x > val
        elif op == "<":
            m &= x < val
        elif op == "==":
            m &= x == val
    return m


def masks_from(F, specs):
    M = np.empty((len(specs), F.shape[0]), dtype=bool)
    for i, (_lab, conds) in enumerate(specs):
        M[i] = _axis_mask(F, conds)
    return M


def first_per_coin(mask, ci, tin):
    out = np.zeros(mask.shape[0], dtype=bool)
    if not np.any(mask):
        return out
    order = np.argsort(tin, kind="mergesort")
    seen = set()
    for i in order:
        if mask[i] and int(ci[i]) not in seen:
            seen.add(int(ci[i]))
            out[i] = True
    return out


def apply_copy_masks(M, g):
    if not g.copy:
        return M
    out = np.empty_like(M)
    for i in range(M.shape[0]):
        out[i] = first_per_coin(M[i], g.ci, g.tin)
    return out


def period_stats(X, M, per):
    nF, E = M.shape[0], X.shape[1]
    ns = np.zeros((nF, 3), np.float64)
    means = np.full((nF, 3, E), np.nan)
    for s in range(3):
        sel = per == s
        if not np.any(sel):
            continue
        ms = M[:, sel]
        ns[:, s] = ms.sum(1)
        with np.errstate(invalid="ignore", divide="ignore"):
            means[:, s, :] = (ms @ X[sel].astype(np.float64)) / ns[:, s, None]
    return ns, means


def count_pass(X, M, per, nmin=30):
    ns, means = period_stats(X, M, per)
    cand = ((ns[:, 2] >= nmin)[:, None] & (means[:, 0, :] > 1) & (means[:, 1, :] > 1) & (means[:, 2, :] > 1))
    cnt = 0
    if not np.any(cand):
        return cnt, ns, means
    selC = per == 2
    xsC = X[selC]
    for k in np.flatnonzero(np.any(cand, axis=0)):
        fs = np.flatnonzero(cand[:, k])
        xs = xsC[:, k].astype(np.float64)
        mk = M[fs][:, selC]
        sums = mk @ xs
        n = mk.sum(1)
        order = np.argsort(-xs)
        first = np.argmax(mk[:, order], axis=1)
        mx = xs[order][first]
        nob = (sums - mx) / np.maximum(n - 1.0, 1.0)
        cnt += int(np.sum((n >= nmin) & (nob > 1)))
    return cnt, ns, means


def cartesian(axes):
    out = [("", [])]
    for axis in axes:
        nxt = []
        for lab, conds in out:
            for frag, extra in axis:
                nxt.append(((lab + " " + frag).strip(), conds + extra))
        out = nxt
    return out


def bom_specs():
    return cartesian([
        [("dev belum jual", [(5, "==", 0.0)]), ("dev jual bebas", [])],
        [("top10<=25%", [(1, "<=", 0.25)]), ("top10<=40%", [(1, "<=", 0.40)]), ("top10 bebas", [])],
        [("buyer>=15", [(2, ">=", 15)]), ("buyer>=40", [(2, ">=", 40)]), ("buyer bebas", [])],
        [("mcap<45", [(0, "<", 45)]), ("mcap 45-120", [(0, ">=", 45), (0, "<", 120)]), ("mcap bebas", [])],
        [("liq>=8", [(4, ">=", 8)]), ("liq bebas", [])],
        [("smart>=1", [(7, ">=", 1)]), ("smart bebas", [])],
        [("devbuy<0.5", [(6, "<", 0.5)]), ("devbuy 0.5-2", [(6, ">=", 0.5), (6, "<", 2)]),
         ("devbuy>=2", [(6, ">=", 2)]), ("devbuy bebas", [])],
        [("holder>=25", [(3, ">=", 25)]), ("holder bebas", [])],
        [("rug pembuat 0", [(8, "==", 0.0)]), ("rug bebas", [])],
    ])


def mom_specs():
    return cartesian([
        [("growth>=1.5", [(9, ">=", 1.5)]), ("growth>=2", [(9, ">=", 2)]),
         ("growth>=3", [(9, ">=", 3)]), ("growth bebas", [])],
        [("beli>=65%", [(10, ">=", 0.65)]), ("beli>=80%", [(10, ">=", 0.80)]), ("beli bebas", [])],
        [("dd<=15%", [(11, "<=", 0.15)]), ("dd<=35%", [(11, "<=", 0.35)]), ("dd bebas", [])],
        [("vol>=3", [(12, ">=", 3)]), ("vol>=8", [(12, ">=", 8)]), ("vol bebas", [])],
        [("laju>=0.5", [(13, ">=", 0.5)]), ("laju>=1.5", [(13, ">=", 1.5)]), ("laju bebas", [])],
        [("top10<=35%", [(1, "<=", 0.35)]), ("top10 bebas", [])],
    ])


def sniper_specs():
    return [
        ("devbuy semua", []),
        ("devbuy<0.5", [(0, "<", 0.5)]),
        ("devbuy 0.5-2", [(0, ">=", 0.5), (0, "<", 2.0)]),
        ("devbuy>=2", [(0, ">=", 2.0)]),
        ("devbuy>=0.5", [(0, ">=", 0.5)]),
    ]


def age_specs():
    return [
        ("umur semua", []),
        ("umur <5m", [(0, "<", 300)]),
        ("umur 5-15m", [(0, ">=", 300), (0, "<", 900)]),
        ("umur >15m", [(0, ">=", 900)]),
    ]


def copy_specs():
    specs = []
    for mn in (5, 10, 20):
        for wr in (0.50, 0.65, 0.80):
            for hold in ("semua", "<=60", ">60"):
                for wd, off in (("semua", 0), ("6j", 4)):
                    conds = [(off, ">=", mn), (off + 1, ">=", wr), (off + 2, ">", 0.0)]
                    if hold == "<=60":
                        conds.append((off + 3, "<=", 60))
                    elif hold == ">60":
                        conds += [(off + 3, ">", 60), (off + 3, "<", 999)]
                    specs.append((f"copy min{mn} wr>={wr:g} hold {hold} jendela {wd}", conds))
    return specs


def _pack(family, name, F, X, per, tin, tout, specs, exits, copy=False, ci=None):
    if len(F) < 5:
        print(f"{name}: hanya {len(F)} baris, dilewati", flush=True)
        return None
    g = Group(family, name, F, X, per, tin, tout, specs, exits, copy, ci)
    print(f"{name}: n={g.F.shape[0]} filter {len(specs)} keluar {len(exits)} "
          f"A/B/C {(g.per == 0).sum()}/{(g.per == 1).sum()}/{(g.per == 2).sum()}", flush=True)
    return g


def build_groups(coins, paths, per, events, exits, families=None):
    _need_numba()
    want = set(families) if families else {"Sniper", "Bom", "Momentum", "Graduation", "Copy"}
    # kompilasi sekali
    dummy = paths[0]
    sim_one(dummy, 0.0, 0.4, max(dummy["anchor"], 1.0), exits_arrays(exits), -1.0)
    print("numba siap", flush=True)
    groups = []
    base_arr = exits_arrays(exits)
    specs_b, specs_m, specs_s = bom_specs(), mom_specs(), sniper_specs()
    print(f"filter Bom {len(specs_b)} Momentum {len(specs_m)} Sniper {len(specs_s)}", flush=True)

    def add(g):
        if g is not None:
            groups.append(g)

    if "Sniper" in want:
        _build_sniper(coins, paths, per, exits, base_arr, specs_s, add)
    if "Bom" in want:
        _build_bom(coins, paths, per, exits, base_arr, specs_b, add)
    if "Momentum" in want:
        _build_mom(coins, paths, per, exits, base_arr, specs_m, add)
    if "Graduation" in want:
        _build_grad(coins, paths, per, exits, base_arr, add)
    if "Copy" in want:
        _build_copy(coins, paths, per, events, dummy, add)
    return groups


def _build_sniper(coins, paths, per, exits, base_arr, specs_s, add):
    for L in DELAYS:
        F, X, P, tin, tout = [], [], [], [], []
        for i, c in enumerate(coins):
            if i and i % 10000 == 0:
                print(f"  sniper {L} {i}", flush=True)
            if not c.w:
                continue
            lx = lag(1, i, 0, L)
            te = c.w[0][0] + lx
            if te >= c.end - 1:
                continue
            p_in = price_at_py(paths[i], te)
            if p_in <= 0:
                continue
            p1, p2, split, to = sim_one(paths[i], te, lx, p_in, base_arr, -1.0)
            F.append([c.devbuy])
            X.append(apply_costs(p_in, p1, p2, split))
            P.append(per[i])
            tin.append(c.t0 + te)
            tout.append(c.t0 + to)
        add(_pack("Sniper", f"Sniper dev-buy jeda {L}", F, X, P, tin, tout, specs_s, exits))


def _build_bom(coins, paths, per, exits, base_arr, specs_b, add):
    for D in AGES_BOM:
        for L in DELAYS:
            F, X, P, tin, tout = [], [], [], [], []
            for i, c in enumerate(coins):
                if i and i % 10000 == 0:
                    print(f"  bom D{D} {L} {i}", flush=True)
                fr = feat_row(c, D)
                if fr is None:
                    continue
                lx = lag(2, i, D, L)
                te = D + lx
                if te >= c.end - 1:
                    continue
                p_in = price_at_py(paths[i], te)
                if p_in <= 0:
                    continue
                p1, p2, split, to = sim_one(paths[i], te, lx, p_in, base_arr, -1.0)
                F.append(fr)
                X.append(apply_costs(p_in, p1, p2, split))
                P.append(per[i])
                tin.append(c.t0 + te)
                tout.append(c.t0 + to)
            add(_pack("Bom", f"Bom D{D} jeda {L}", F, X, P, tin, tout, specs_b, exits))


def _build_mom(coins, paths, per, exits, base_arr, specs_m, add):
    for D in AGES_MOM:
        for L in DELAYS:
            F, X, P, tin, tout = [], [], [], [], []
            for i, c in enumerate(coins):
                if i and i % 10000 == 0:
                    print(f"  momentum D{D} {L} {i}", flush=True)
                fr = feat_row(c, D)
                if fr is None:
                    continue
                lx = lag(3, i, D, L)
                te = D + lx
                if te >= c.end - 1:
                    continue
                p_in = price_at_py(paths[i], te)
                if p_in <= 0:
                    continue
                p1, p2, split, to = sim_one(paths[i], te, lx, p_in, base_arr, -1.0)
                F.append(fr)
                X.append(apply_costs(p_in, p1, p2, split))
                P.append(per[i])
                tin.append(c.t0 + te)
                tout.append(c.t0 + to)
            add(_pack("Momentum", f"Momentum D{D} jeda {L}", F, X, P, tin, tout, specs_m, exits))


def _build_grad(coins, paths, per, exits, base_arr, add):
    specs_age = age_specs()
    for pc in GRAD_PC:
        thr = (30 + pc / 100.0 * 85) ** 2 / K_CURVE
        hits = []
        for i, c in enumerate(coins):
            pa = paths[i]
            hi = pa["bar_hi"]
            if hi.size == 0 or float(hi.max()) < thr:
                continue
            j = int(np.argmax(hi >= thr))
            if hi[j] < thr:
                continue
            hits.append((i, float(pa["bar_t"][j])))
        for L in DELAYS:
            F, X, P, tin, tout = [], [], [], [], []
            for i, th in hits:
                c = coins[i]
                lx = lag(4, i, pc, L)
                te = th + lx
                if te >= c.end - 1:
                    continue
                p_in = price_at_py(paths[i], te)
                if p_in <= 0:
                    continue
                p1, p2, split, to = sim_one(paths[i], te, lx, p_in, base_arr, -1.0)
                F.append([th])
                X.append(apply_costs(p_in, p1, p2, split))
                P.append(per[i])
                tin.append(c.t0 + te)
                tout.append(c.t0 + to)
            add(_pack("Graduation", f"Graduation {pc}% jeda {L}", F, X, P, tin, tout, specs_age, exits))


def _build_copy(coins, paths, per, events, dummy, add):
    cex = make_exits(with_follow=True)
    carr = exits_arrays(cex)
    cspecs = copy_specs()
    # kompilasi ulang untuk panjang exit yang beda
    sim_one(dummy, 0.0, 0.4, max(dummy["anchor"], 1.0), carr, -1.0)
    for L in DELAYS:
        F, X, P, tin, tout, ci, fols = [], [], [], [], [], [], []
        for ev_i, (ci_i, ag, tabs, fol, sv) in enumerate(events):
            if ev_i and ev_i % 20000 == 0:
                print(f"  copy {L} {ev_i}/{len(events)}", flush=True)
            c = coins[ci_i]
            lx = lag(5, ci_i, ev_i % 997, L)
            te = ag + lx
            if te >= c.end - 1:
                continue
            p_in = price_at_py(paths[ci_i], te)
            if p_in <= 0:
                continue
            p1, p2, split, to = sim_one(paths[ci_i], te, lx, p_in, carr, fol if fol >= 0 else -1.0)
            F.append(sv)
            X.append(apply_costs(p_in, p1, p2, split))
            P.append(per[ci_i])
            tin.append(tabs + lx)
            tout.append(c.t0 + to)
            ci.append(ci_i)
        g = _pack("Copy", f"Copy-wallet jeda {L}", F, X, P, tin, tout, cspecs, cex, True, ci)
        add(g)


def group_pass(g, perm=None):
    F = g.F if perm is None else g.F[perm]
    if F.shape[0] != g.X.shape[0]:
        raise RuntimeError("ukuran fitur dan hasil tidak sama")
    M = masks_from(F, g.specs)
    M = apply_copy_masks(M, g)
    return count_pass(g.X, M, g.per)


def one_mask(g, f, perm=None):
    F = g.F if perm is None else g.F[perm]
    m = _axis_mask(F, g.specs[f][1])
    if g.copy:
        m = first_per_coin(m, g.ci, g.tin)
    return m


def nobest_of(xs):
    xs = np.asarray(xs, np.float64)
    if xs.size < 2:
        return float("nan")
    return float((xs.sum() - xs.max()) / (xs.size - 1))


def wilson(k, n):
    return ms.wilson(int(k), int(n))


def boot_p(xs, B=20000, seed=1):
    xs = np.asarray(xs, np.float64)
    if xs.size < 2:
        return float("nan"), B
    rng = np.random.default_rng(seed)
    bad = 0
    left = B
    while left:
        b = min(left, 400)
        # sampel indeks supaya memori tetap kecil
        idx = rng.integers(0, xs.size, size=(b, xs.size))
        means = xs[idx].mean(1)
        bad += int(np.sum(means <= 1.0))
        left -= b
    return bad / B, B


def sim200(trades, frac, maxpos, cap=200.0):
    eq, open_, n, k = cap, [], 0, 0
    for t, x, tx in sorted(trades):
        still = []
        for te_, st, xx in open_:
            if te_ <= t:
                eq += st * xx
            else:
                still.append((te_, st, xx))
        open_ = still
        tot = eq + sum(s for _t, s, _x in open_)
        if len(open_) >= maxpos or tot < 1:
            continue
        st = min(eq, tot * frac)
        if st <= 0.05:
            continue
        eq -= st
        open_.append((tx, st, x))
        n += 1
        k += x > 1
    eq += sum(s * xx for _t, s, xx in open_)
    return float(eq), int(n), int(k)


def slice_stats(g, f, k, s):
    m = one_mask(g, f)
    sel = m & (g.per == s)
    xs = g.X[sel, k].astype(np.float64)
    n = int(xs.size)
    if n == 0:
        return dict(n=0, mean=None, win=None, wilson=(0.0, 0.0), nobest=None, best=None)
    wins = int(np.sum(xs > 1))
    return dict(n=n, mean=float(xs.mean()), win=wins / n, wilson=wilson(wins, n),
                nobest=nobest_of(xs), best=float(xs.max()),
                xs=xs, tin=g.tin[sel], tout=g.tout[sel, k])


def sim_pack(st):
    if st["n"] == 0:
        return {}
    tr = list(zip(st["tin"].tolist(), st["xs"].tolist(), st["tout"].tolist()))
    out = {}
    for frac in (0.08, 0.10):
        for mp in (1, 5):
            eq, n, k = sim200(tr, frac, mp)
            out[f"{int(frac * 100)}% maks{mp}"] = (eq, n, k)
    return out


def public_stats(st, with_sim=False):
    d = {k: st[k] for k in ("n", "mean", "win", "wilson", "nobest", "best")}
    d["wilson"] = [float(st["wilson"][0]), float(st["wilson"][1])]
    if with_sim:
        d["sim"] = {k: list(v) for k, v in sim_pack(st).items()}
    return d


def outcome_sig(g, f, k, s, decimals=3):
    m = one_mask(g, f)
    sel = m & (g.per == s)
    xs = np.round(g.X[sel, k].astype(np.float64), decimals)
    return (int(xs.size), xs.tobytes())


def top_by_A(groups, n=5):
    pool = []
    for gi, g in enumerate(groups):
        if g.F.shape[0] == 0:
            continue
        M = apply_copy_masks(masks_from(g.F, g.specs), g)
        ns, means = period_stats(g.X, M, g.per)
        g.ns, g.means, g.M = ns, means, M
        mA = means[:, 0, :]
        ok = (ns[:, 0] >= 30)[:, None] & np.isfinite(mA)
        if not np.any(ok):
            continue
        vals = np.where(ok, mA, -1e9)
        flat = vals.ravel()
        take = min(400, flat.size)
        idx = np.argpartition(flat, -take)[-take:]
        idx = idx[np.argsort(flat[idx])[::-1]]
        E = vals.shape[1]
        for j in idx:
            if flat[j] <= -1e8:
                break
            f, k = divmod(int(j), E)
            pool.append((float(flat[j]), gi, int(f), int(k)))
    pool.sort(reverse=True)
    picked, seen = [], set()
    for mean, gi, f, k in pool:
        sig = outcome_sig(groups[gi], f, k, 0)
        if sig in seen or sig[0] < 30:
            continue
        seen.add(sig)
        picked.append((mean, gi, f, k))
        if len(picked) >= n:
            break
    return picked


def top_nobest(groups, n=10):
    pool = []
    for gi, g in enumerate(groups):
        M = getattr(g, "M", None)
        if M is None:
            continue
        sel = g.per == 2
        if not np.any(sel):
            continue
        mk = M[:, sel]
        ns = mk.sum(1)
        Xc = g.X[sel]
        E = Xc.shape[1]
        best_local = []
        for k in range(E):
            xs = Xc[:, k].astype(np.float64)
            sums = mk @ xs
            order = np.argsort(-xs)
            first = np.argmax(mk[:, order], axis=1)
            has = mk.any(1)
            mx = np.zeros(ns.shape[0])
            mx[has] = xs[order][first[has]]
            ok = ns >= 30
            if not np.any(ok):
                continue
            nob = np.full(ns.shape[0], -1e9)
            nob[ok] = (sums[ok] - mx[ok]) / (ns[ok] - 1.0)
            take = min(8, nob.size)
            idx = np.argpartition(nob, -take)[-take:]
            for f in idx:
                if nob[f] <= -1e8:
                    continue
                best_local.append((float(nob[f]), gi, int(f), int(k), float(ns[f])))
        best_local.sort(reverse=True)
        pool.extend(best_local[:12])
    pool.sort(reverse=True)
    picked, seen = [], set()
    for nob, gi, f, k, nC in pool:
        sig = outcome_sig(groups[gi], f, k, 2)
        if sig in seen:
            continue
        seen.add(sig)
        picked.append((nob, gi, f, k))
        if len(picked) >= n:
            break
    return picked


def row_detail(g, f, k, do_c):
    A = slice_stats(g, f, k, 0)
    B = slice_stats(g, f, k, 1)
    b_ok = (B["mean"] or 0) > 1
    C = slice_stats(g, f, k, 2) if (do_c or b_ok) and do_c else None
    # do_c True forces C. For official top5, caller passes do_c=b_ok after seeing B.
    if do_c:
        C = slice_stats(g, f, k, 2)
    out = dict(family=g.family, name=g.name, filt=g.specs[f][0], exit=g.exits[k]["name"],
               A=public_stats(A), B=public_stats(B))
    if C is None:
        out["C"] = None
        out["tested_c"] = False
    else:
        out["C"] = public_stats(C, with_sim=True)
        out["tested_c"] = True
        p, Bboot = boot_p(C["xs"]) if C["n"] >= 2 else (float("nan"), 0)
        out["C"]["p_boot"] = p
        out["C"]["boot_B"] = Bboot
        out["pass_c"] = bool(C["n"] >= 30 and (A["mean"] or 0) > 1 and (B["mean"] or 0) > 1
                             and (C["mean"] or 0) > 1 and (C["nobest"] or 0) > 1)
    # lepas array besar
    return out


def best_per_family(groups):
    out = {}
    for gi, g in enumerate(groups):
        if not hasattr(g, "means"):
            continue
        mA = g.means[:, 0, :]
        nA = g.ns[:, 0]
        ok = (nA >= 30)[:, None] & np.isfinite(mA)
        if not np.any(ok):
            continue
        vals = np.where(ok, mA, -1e9)
        j = int(np.argmax(vals))
        f, k = divmod(j, vals.shape[1])
        if vals.ravel()[j] <= -1e8:
            continue
        fam = g.family
        if fam not in out or vals.ravel()[j] > out[fam][0]:
            out[fam] = (float(vals.ravel()[j]), gi, int(f), int(k))
    rows = []
    for fam, (_m, gi, f, k) in out.items():
        g = groups[gi]
        A = public_stats(slice_stats(g, f, k, 0))
        B = public_stats(slice_stats(g, f, k, 1))
        rows.append(dict(family=fam, name=g.name, filt=g.specs[f][0], exit=g.exits[k]["name"], A=A, B=B))
    return rows


def evaluate(groups, meta, n_null, n_pick=5, n_desc=10):
    t0 = time.time()
    real = 0
    by = {}
    combos = {}
    for g in groups:
        cnt, ns, means = group_pass(g)
        g.ns, g.means = ns, means
        g.M = apply_copy_masks(masks_from(g.F, g.specs), g)
        real += cnt
        by[g.family] = by.get(g.family, 0) + cnt
        combos[g.family] = combos.get(g.family, 0) + len(g.specs) * len(g.exits)
        print(f"lulus {g.name}: {cnt}", flush=True)
    print(f"lulus total {real} dari {sum(combos.values())} kombinasi", flush=True)
    nulls = []
    null_by = {fam: [] for fam in combos}
    for s in range(n_null):
        rng = np.random.default_rng(100 + s)
        total = 0
        acc = {fam: 0 for fam in combos}
        for g in groups:
            if g.F.shape[0] == 0:
                continue
            perm = rng.permutation(g.F.shape[0])
            cnt, _ns, _m = group_pass(g, perm)
            total += cnt
            acc[g.family] += cnt
        nulls.append(total)
        for fam, v in acc.items():
            null_by[fam].append(v)
        print(f"null {s}: {total}", flush=True)
    picked = top_by_A(groups, n_pick)
    final_rows = []
    for mean, gi, f, k in picked:
        g = groups[gi]
        B = slice_stats(g, f, k, 1)
        do_c = (B["mean"] or 0) > 1
        final_rows.append(row_detail(g, f, k, do_c))
    descriptive = []
    for nob, gi, f, k in top_nobest(groups, n_desc):
        d = row_detail(groups[gi], f, k, True)
        d["nobest_rank"] = nob
        descriptive.append(d)
    fam_rows = best_per_family(groups)
    k_combo = int(sum(combos.values()))
    k_c = sum(1 for r in final_rows if r.get("tested_c"))
    return dict(real_pass=real, null=nulls, null_by=null_by, pass_by=by, combos=combos,
                k_combo=k_combo, k_c=k_c, bonferroni_full=0.05 / k_combo if k_combo else None,
                bonferroni_c=0.05 / k_c if k_c else None,
                top5=final_rows, top10=descriptive, per_family=fam_rows,
                secs_eval=time.time() - t0, meta=meta)


def fmt_x(x, nd=3):
    if x is None:
        return "—"
    try:
        if x != x:
            return "—"
    except Exception:
        return "—"
    return f"{float(x):.{nd}f}".replace(".", ",") + "x"


def fmt_n(x, nd=1):
    if x is None:
        return "—"
    try:
        if x != x:
            return "—"
    except Exception:
        return "—"
    s = f"{float(x):.{nd}f}"
    return s.replace(".", ",")


def fmt_t(ts):
    if not ts:
        return "—"
    utc = time.strftime("%d %b %Y %H:%M UTC", time.gmtime(ts))
    wib = time.strftime("%H:%M WIB", time.gmtime(ts + 7 * 3600))
    return f"{utc} / {wib}"


def fmt_block(lab, d):
    if not d:
        return f"{lab}: tidak diuji"
    if d.get("n", 0) == 0:
        return f"{lab}: n=0"
    w = d.get("wilson") or [0, 0]
    return (f"{lab}: n={d['n']} rata {fmt_x(d.get('mean'))} menang {fmt_n((d.get('win') or 0) * 100)}% "
            f"Wilson [{fmt_n(w[0] * 100)}–{fmt_n(w[1] * 100)}%] tanpa terbaik {fmt_x(d.get('nobest'))} "
            f"terbaik {fmt_x(d.get('best'))}")


def fmt_sim(d):
    sim = (d or {}).get("sim") or {}
    if not sim:
        return "—"
    bits = []
    for k in ("8% maks1", "8% maks5", "10% maks1", "10% maks5"):
        v = sim.get(k)
        if not v:
            continue
        bits.append(f"{k} ${v[0]:.2f} ({v[1]} trade, menang {v[2]})")
    return "; ".join(bits)


def p_upper(p, B):
    if p is None or (isinstance(p, float) and p != p):
        return None
    if p <= 0 and B:
        return 1.0 / B
    return p


def build_report(R):
    meta = R["meta"]
    nulls = R["null"]
    nmean = sum(nulls) / len(nulls) if nulls else float("nan")
    nmax = max(nulls) if nulls else float("nan")
    econ = R["real_pass"]
    finals = [r for r in R["top5"] if r.get("pass_c")]
    cleared = []
    for r in finals:
        c = r.get("C") or {}
        pu = p_upper(c.get("p_boot"), c.get("boot_B") or 0)
        if pu is not None and R["bonferroni_full"] and pu < R["bonferroni_full"] and econ > nmax:
            cleared.append(r)
    if cleared:
        line = (f"LAYAK SEBAGAI KANDIDAT PAPER, BUKAN LIVE. {len(cleared)} finalis lolos A/B/C, "
                f"jumlah lulus {econ} di atas null maks {fmt_n(nmax)}, dan p di bawah Bonferroni "
                f"{R['bonferroni_full']:.3g}.")
    else:
        line = (f"TIDAK LAYAK. {R['k_combo']} kombinasi, lulus ekonomi {econ}, "
                f"null rata-rata {fmt_n(nmean, 2)} (maks {fmt_n(nmax, 1)}). "
                f"Finalis protokol A→B→C yang lolos syarat: {len(finals)}. "
                f"Tidak ada yang lolos koreksi uji berganda atas seluruh pencarian.")
    L = [line, "",
         "# Riset grid luas strategi pump.fun, 10 Nov 2026, PAPER", "",
         "Bukan saran beli. Tidak ada kunci, tidak ada transaksi.", "",
         "## Data",
         f"- Kunci cache: `{meta.get('cache_key') or '—'}`",
         f"- Berkas: {len(meta.get('files') or [])} file rec, {meta['n_lines']} baris, "
         f"{meta['n_with_w']} punya trade wallet.",
         f"- Periode rekaman (t0 pertama–terakhir): {fmt_t(meta.get('t_min'))} – {fmt_t(meta.get('t_max'))}.",
         f"- Koin kurva standar: {meta['n_std']}. Yang diuji (sampel merata waktu, kalau dipotong): {meta['n_used']}.",
         f"- Periode yang diuji: {fmt_t(meta.get('t_first'))} – {fmt_t(meta.get('t_last'))}.",
         f"- Potongan A/B/C: {fmt_t(meta.get('cut1'))} / {fmt_t(meta.get('cut2'))}.",
         f"- Jumlah koin A/B/C: {meta['nA']}/{meta['nB']}/{meta['nC']}.",
         f"- Dedupe: {meta['n_dup_rows']} baris trade dibuang di {meta['n_coins_dup']} koin "
         f"(kunci wallet+sisi+SOL, selisih umur ≤0,3 dtk). Signature tidak ada di rekaman.",
         f"- Hash skrip sha256: `{meta.get('sha256')}`",
         "",
         "## Protokol",
         "- Pilih hanya di A (n_A≥30, rata tertinggi). Lima teratas, satu per pola trade (cara jual yang hasilnya sama di A dihitung satu).",
         "- B harus rata >1. C diuji sekali, hanya untuk yang lolos B.",
         "- Lulus ekonomi: n_C≥30, rata A, B, dan C >1, dan C tanpa koin terbaik >1.",
         "- Null mengacak fitur 20 kali. Jumlah lulus harus mengalahkan null.",
         f"- Bonferroni pencarian penuh: 0,05/{R['k_combo']} = {R['bonferroni_full']}.",
         f"- Bonferroni hanya pada yang benar-benar diuji di C (k={R['k_c']}): {R['bonferroni_c']}.",
         "- Top 10 di bawah ini melihat C. Itu deskripsi, bukan seleksi, dan tidak dihitung lulus.",
         "",
         "## Kombinasi dan lulus per keluarga",
         "",
         "| Keluarga | Kombinasi | Lulus ekonomi | Null rata | Null maks |",
         "|---|---:|---:|---:|---:|"]
    for fam, ncom in R["combos"].items():
        nb = R["null_by"].get(fam) or []
        L.append(f"| {fam} | {ncom} | {R['pass_by'].get(fam, 0)} | "
                 f"{fmt_n(sum(nb) / len(nb), 2) if nb else '—'} | {fmt_n(max(nb), 1) if nb else '—'} |")
    L += ["",
          f"Total kombinasi {R['k_combo']}. Total lulus ekonomi {econ}.",
          f"Null global ({len(nulls)}): {', '.join(str(int(x)) for x in nulls) if nulls else '—'}.",
          f"Null rata {fmt_n(nmean, 2)}, maks {fmt_n(nmax, 1)}.",
          "",
          "## Lima teratas menurut A (seleksi resmi)",
          ""]
    if not R["top5"]:
        L.append("Tidak ada kombinasi dengan n_A≥30.")
    for i, r in enumerate(R["top5"], 1):
        L.append(f"### {i}. {r['name']} — {r['filt']} — {r['exit']}")
        L.append(f"- {fmt_block('A', r.get('A'))}")
        L.append(f"- {fmt_block('B', r.get('B'))}")
        if r.get("tested_c"):
            L.append(f"- {fmt_block('C', r.get('C'))}")
            c = r["C"]
            pu = p_upper(c.get("p_boot"), c.get("boot_B") or 0)
            L.append(f"- p bootstrap C = {fmt_n(c.get('p_boot'), 4)} (batas atas pelaporan {fmt_n(pu, 6)}), "
                     f"B={c.get('boot_B')}. Ambang penuh {R['bonferroni_full']}.")
            L.append(f"- Simulasi $200 di C: {fmt_sim(c)}")
            L.append(f"- Lolos syarat ekonomi C: {'ya' if r.get('pass_c') else 'tidak'}.")
        else:
            L.append("- C: tidak diuji (gagal di B, atau B tidak di atas 1).")
        L.append("")
    L += ["## Terbaik di A per keluarga (C tidak dibuka di sini)", ""]
    if not R["per_family"]:
        L.append("Tidak ada.")
    for r in R["per_family"]:
        L.append(f"- {r['family']}: {r['name']} — {r['filt']} — {r['exit']}. "
                 f"{fmt_block('A', r['A'])}. {fmt_block('B', r['B'])}.")
    L += ["",
          "## Top 10 menurut C tanpa koin terbaik",
          "Diurut dari rata C setelah koin terbaik dibuang. Bukan hasil seleksi. "
          "Kalau n_C<30 atau A/B≤1, baris ini gagal.",
          ""]
    if not R["top10"]:
        L.append("Tidak ada kombinasi dengan n_C≥30.")
    for i, r in enumerate(R["top10"], 1):
        L.append(f"### {i}. {r['name']} — {r['filt']} — {r['exit']}")
        L.append(f"- {fmt_block('A', r.get('A'))}")
        L.append(f"- {fmt_block('B', r.get('B'))}")
        L.append(f"- {fmt_block('C', r.get('C'))}")
        c = r.get("C") or {}
        if c.get("p_boot") is not None:
            L.append(f"- p bootstrap C = {fmt_n(c.get('p_boot'), 4)}")
        L.append(f"- Simulasi $200 di C: {fmt_sim(c)}")
        L.append("")
    L += ["## Batasan",
          "- Signature transaksi tidak disimpan perekam GitHub. Dedupe memakai umur, 10 huruf wallet, sisi, dan SOL. "
          "Dua beli asli yang sama persis dalam 0,3 detik bisa terbuang. Dua notifikasi RPC yang umurnya terbulatkan "
          "lebih dari 0,3 detik bisa tetap dobel.",
          "- Harga, likuiditas, holder, top10, dan inflow di snapshot berasal dari cadangan kurva (tidak ikut dobel). "
          "Rasio beli/jual di snapshot memakai jumlah event, jadi kira-kira tetap kalau kedua sisi dobel, tetapi tidak persis.",
          "- Volume di candle (bukan yang dipakai filter) bisa dobel. Filter volume memakai selisih inflow snapshot.",
          "- Riwayat rug pembuat hanya sejak perekam berjalan, bukan seluruh riwayat on-chain.",
          "- Wallet pintar / copy hanya dari trade 5 menit pertama, maks 150 per koin, wallet terpotong 10 huruf.",
          "- Harga setelah lulus ke PumpSwap tidak ada. Graduation berhenti di ujung rekaman (batas atas).",
          "- Sampel, kalau jumlah koin standar melebihi --sample, diambil merata dari yang paling lama sampai yang paling baru.",
          "- Biaya berat (fee+slippage+priority+dampak kurva). Isi stop candle x0,72.",
          f"- Waktu hitung statistik+null: {fmt_n(R.get('secs_eval'), 0)} detik. Total skrip: {fmt_n(R.get('secs'), 0)} detik.",
          "",
          "Paper saja. Jangan dipakai live karena protokol ini belum menemukan edge yang mengalahkan kebetulan dan koreksi uji berganda."
          if not cleared else
          "Paper saja. Kandidat di atas boleh diuji forward di kertas. Jangan dipakai live dari laporan ini.",
          ""]
    return "\n".join(L)


PARTIAL_2_5 = dict(kind=2, tp=2.0, sl=0.7, T=600.0, arm=0.0, trail=0.0, tp2=5.0,
                    name="parsial 50% 2x sisa TP5 SL0.7 600s")
# Aturan dikunci dari laporan sampel 30.000. Tidak ada ambang baru.
FIXED_RULES = [
    dict(key="a", judul="(a) Momentum, baris 1 top-10 C tanpa koin terbaik",
         D=120, delay="1", kind=3, mode="snap", exit=PARTIAL_2_5,
         conds=[(9, ">=", 3.0), (11, "<=", 0.35), (1, "<=", 0.35)],
         teks="D120 jeda 1 dtk, growth≥3, drawdown≤35%, top10≤35%, beli/vol/laju bebas, parsial 50% di 2x sisa TP5 SL0,7 600 dtk"),
    dict(key="b", judul="(b) Momentum terbaik menurut A pada sampel",
         D=120, delay="3-8", kind=3, mode="snap", exit=PARTIAL_2_5,
         conds=[(9, ">=", 3.0), (10, ">=", 0.65), (12, ">=", 3.0), (13, ">=", 1.5)],
         teks="D120 jeda 3–8 dtk, growth≥3, rasio beli≥65%, inflow baru≥3 SOL, laju pembeli≥1,5, parsial 50% di 2x sisa TP5 SL0,7 600 dtk"),
    dict(key="c", judul="(c) Bom terbaik menurut A pada sampel",
         D=180, delay="1", kind=2, mode="snap",
         exit=dict(kind=0, tp=3.0, sl=0.5, T=600.0, arm=0.0, trail=0.0, tp2=0.0, name="TP3 SL0.5 600s"),
         conds=[(5, "==", 0.0), (1, "<=", 0.40), (2, ">=", 40), (4, ">=", 8), (7, ">=", 1), (6, "<", 0.5), (8, "==", 0.0)],
         teks="D180 jeda 1 dtk, dev belum jual, top10≤40%, buyer≥40, liq≥8, smart≥1, devbuy<0,5, rug pembuat 0, TP3 SL0,5 600 dtk"),
    dict(key="d", judul="(d) Graduation 98%, umur di bawah 5 menit",
         pc=98, delay="3-8", kind=4, mode="grad", age_max=300.0,
         exit=dict(kind=0, tp=1e9, sl=0.0, T=1800.0, arm=0.0, trail=0.0, tp2=0.0, name="tahan sampai habis"),
         teks="kurva 98%, umur sinyal <5 menit, jeda 3–8 dtk, tahan sampai rekaman habis"),
]


def _conds_ok(fr, conds):
    for col, op, val in conds:
        x = float(fr[col])
        if op == ">=" and not x >= val:
            return False
        if op == "<=" and not x <= val:
            return False
        if op == ">" and not x > val:
            return False
        if op == "<" and not x < val:
            return False
        if op == "==" and not x == val:
            return False
    return True


def _pack_slice(xs, tin, tout):
    xs = np.asarray(xs, np.float64)
    n = int(xs.size)
    if n == 0:
        return dict(n=0, mean=None, win=None, wilson=[0.0, 0.0], nobest=None, best=None, sim={})
    wins = int(np.sum(xs > 1))
    lo, hi = wilson(wins, n)
    tr = list(zip(np.asarray(tin, np.float64).tolist(), xs.tolist(), np.asarray(tout, np.float64).tolist()))
    sim = {}
    for frac, mp in ((0.08, 1), (0.08, 5), (0.10, 1), (0.10, 5)):
        eq, nn, k = sim200(tr, frac, mp)
        sim[f"{int(frac * 100)}% maks{mp}"] = [eq, nn, k]
    return dict(n=n, mean=float(xs.mean()), win=wins / n, wilson=[float(lo), float(hi)],
                nobest=nobest_of(xs), best=float(xs.max()), sim=sim)


def run_holdout(a):
    """Uji aturan yang sudah dikunci pada koin yang TIDAK masuk sampel 30.000. Tanpa setel ulang."""
    _need_numba()
    t0 = time.time()
    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    print(f"sha256 {sha}", flush=True)
    coins, meta = load_coins(a.data)
    if not coins:
        raise SystemExit("Tidak ada koin kurva standar.")
    for i, c in enumerate(coins):
        c.full_i = i
        c.i = i
    print("riwayat wallet pada SEMUA koin standar (supaya filter smart kausal utuh)...", flush=True)
    prepare(coins)
    taken = set(int(i) for i in sample_index(len(coins), a.holdout_of))
    hold = [c for i, c in enumerate(coins) if i not in taken]
    print(f"std {len(coins)}, sampel lama {len(taken)}, holdout {len(hold)}", flush=True)
    del coins
    t0s = np.array([c.t0 for c in hold], np.float64)
    cut1, cut2 = float(t0s[int(len(hold) * 0.5)]), float(t0s[int(len(hold) * 0.7)])
    per = np.where(t0s < cut1, 0, np.where(t0s < cut2, 1, 2)).astype(np.int8)
    print("bangun jalur harga holdout...", flush=True)
    paths = []
    for i, c in enumerate(hold):
        paths.append(extract_path(c))
        if i and i % 5000 == 0:
            print(f"  jalur {i}", flush=True)
    sim_one(paths[0], 0.0, 0.4, max(paths[0]["anchor"], 1.0), exits_arrays([PARTIAL_2_5]), -1.0)
    rules_out = []
    for rule in FIXED_RULES:
        arr = exits_arrays([rule["exit"]])
        bag = {0: [], 1: [], 2: []}
        n_try = 0
        for i, c in enumerate(hold):
            if rule["mode"] == "snap":
                fr = feat_row(c, rule["D"])
                if fr is None or not _conds_ok(fr, rule["conds"]):
                    continue
                lx = lag(rule["kind"], c.full_i, rule["D"], rule["delay"])
                te = rule["D"] + lx
            else:
                pa = paths[i]
                hi = pa["bar_hi"]
                thr = (30 + rule["pc"] / 100.0 * 85) ** 2 / K_CURVE
                if hi.size == 0 or float(hi.max()) < thr:
                    continue
                j = int(np.argmax(hi >= thr))
                if hi[j] < thr:
                    continue
                th = float(pa["bar_t"][j])
                if th >= rule["age_max"]:
                    continue
                lx = lag(rule["kind"], c.full_i, rule["pc"], rule["delay"])
                te = th + lx
            if te >= c.end - 1:
                continue
            p_in = price_at_py(paths[i], te)
            if p_in <= 0:
                continue
            p1, p2, split, to = sim_one(paths[i], te, lx, p_in, arr, -1.0)
            x = float(apply_costs(p_in, p1, p2, split)[0])
            s = int(per[i])
            bag[s].append((x, c.t0 + te, c.t0 + float(to[0])))
            n_try += 1
        slices = {}
        for s, lab in ((0, "A"), (1, "B"), (2, "C")):
            rows = bag[s]
            slices[lab] = _pack_slice([r[0] for r in rows], [r[1] for r in rows], [r[2] for r in rows])
        print(f"{rule['key']} trade {n_try} A/B/C "
              f"{slices['A']['n']}/{slices['B']['n']}/{slices['C']['n']}", flush=True)
        rules_out.append(dict(key=rule["key"], judul=rule["judul"], teks=rule["teks"],
                              exit=rule["exit"]["name"], n=n_try, slices=slices))
    meta.update(sha256=sha, cache_key=os.environ.get("CACHE_MATCHED_KEY") or "",
                n_std=len(taken) + len(hold), n_sample=len(taken), n_hold=len(hold),
                nA=int((per == 0).sum()), nB=int((per == 1).sum()), nC=int((per == 2).sum()),
                t_first=float(t0s[0]), t_last=float(t0s[-1]), cut1=cut1, cut2=cut2,
                secs=time.time() - t0, holdout_of=a.holdout_of)
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, "holdout.json")
    with open(path, "w") as f:
        json.dump(dict(meta=meta, rules=rules_out), f, indent=1, default=float)
    print(f"tulis {path}", flush=True)


def run(a):
    if a.holdout_of:
        run_holdout(a)
        return
    _need_numba()
    t0 = time.time()
    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    print(f"sha256 {sha}", flush=True)
    coins, meta = load_coins(a.data)
    meta["sha256"] = sha
    meta["cache_key"] = os.environ.get("CACHE_MATCHED_KEY") or ""
    if not coins:
        raise SystemExit("Tidak ada koin kurva standar.")
    n_std = len(coins)
    coins = take_sample(coins, a.sample)
    for i, c in enumerate(coins):
        c.i = i
    meta["n_std"] = n_std
    meta["n_used"] = len(coins)
    t0s = np.array([c.t0 for c in coins], np.float64)
    meta["t_first"] = float(t0s[0])
    meta["t_last"] = float(t0s[-1])
    cut1, cut2 = float(t0s[int(len(coins) * 0.5)]), float(t0s[int(len(coins) * 0.7)])
    meta["cut1"], meta["cut2"] = cut1, cut2
    per = np.where(t0s < cut1, 0, np.where(t0s < cut2, 1, 2)).astype(np.int8)
    meta["nA"], meta["nB"], meta["nC"] = int((per == 0).sum()), int((per == 1).sum()), int((per == 2).sum())
    print(f"uji {len(coins)} koin std (dari {n_std}), A/B/C {meta['nA']}/{meta['nB']}/{meta['nC']}", flush=True)
    print("bangun jalur harga...", flush=True)
    paths = []
    for i, c in enumerate(coins):
        paths.append(extract_path(c))
        if i and i % 2000 == 0:
            print(f"  jalur {i}", flush=True)
    events = prepare(coins)
    exits = make_exits(False)
    print(f"cara keluar dasar: {len(exits)}", flush=True)
    fams = [x.strip() for x in a.families.split(",") if x.strip()] or None
    groups = build_groups(coins, paths, per, events, exits, fams)
    del paths, events
    if not groups:
        raise SystemExit("Tidak ada kelompok yang cukup datanya.")
    R = evaluate(groups, meta, a.null, a.pick, a.desc)
    R["secs"] = time.time() - t0
    text = build_report(R)
    os.makedirs(a.out, exist_ok=True)
    md_path = os.path.join(a.out, a.report_name)
    js_path = os.path.join(a.out, "grid_luas_result.json")
    with open(md_path, "w") as f:
        f.write(text)
    slim = {k: R[k] for k in ("real_pass", "null", "null_by", "pass_by", "combos", "k_combo", "k_c",
                              "bonferroni_full", "bonferroni_c", "top5", "top10", "per_family", "secs_eval", "secs")}
    slim["meta"] = meta
    with open(js_path, "w") as f:
        json.dump(slim, f, indent=1, default=float)
    print("\n" + text, flush=True)
    print(f"tulis {md_path} dan {js_path}", flush=True)


def self_test():
    _need_numba()
    # dedupe
    w, n = dedupe_trades([[0.4, "DEV1234567", 1, 1.0], [0.5, "DEV1234567", 1, 1.0],
                          [1.2, "DEV1234567", 1, 1.0], [1.2, "BUYER00001", 1, 0.4]])
    assert n == 1 and len(w) == 3, (n, w)
    # harga & isi stop / TP pada jalur buatan
    pa = {
        "bar_t": np.array([10.0, 40.0, 80.0], np.float64),
        "bar_hi": np.array([30.0, 40.0, 90.0], np.float64),
        "bar_lo": np.array([30.0, 10.0, 70.0], np.float64),
        "bar_tick": np.array([1, 0, 1], np.int8),
        "tick_t": np.array([10.0, 80.0], np.float64),
        "tick_px": np.array([30.0, 90.0], np.float64),
        "anchor": 30.0, "cov": 100.0,
        "cs_start": np.array([0.0, 35.0], np.float64),
        "cs_close": np.array([30.0, 40.0], np.float64),
        "m0": 30.0, "end": 200.0,
    }
    exits = [
        dict(kind=0, tp=2.0, sl=0.5, T=600, arm=0, trail=0, tp2=0, name="tp"),
        dict(kind=0, tp=5.0, sl=0.7, T=600, arm=0, trail=0, tp2=0, name="sl"),
    ]
    arr = exits_arrays(exits)
    # Candle di t=40 menyentuh SL 0,5 (harga 15) lebih dulu. Isi candle = 15 x 0,72.
    p1, p2, split, tout = sim_one(pa, 10.0, 0.4, 30.0, arr, -1.0)
    assert abs(p1[0] - 15.0 * 0.72) < 1e-6, p1[0]
    assert abs(p1[1] - 21.0 * 0.72) < 1e-6, p1[1]
    xs = apply_costs(30.0, p1, p2, split)
    assert xs[0] < 0.6 and xs[1] < 0.6, xs
    up = dict(pa)
    up["bar_t"] = np.array([40.0], np.float64)
    up["bar_hi"] = np.array([90.0], np.float64)
    up["bar_lo"] = np.array([90.0], np.float64)
    up["bar_tick"] = np.array([1], np.int8)
    up["tick_t"] = np.array([10.0, 40.0], np.float64)
    up["tick_px"] = np.array([30.0, 90.0], np.float64)
    p1, p2, split, tout = sim_one(up, 10.0, 0.4, 30.0, arr, -1.0)
    # TP 2x kena di tick 40; isi = harga setelah jeda = 90. SL 0,7 tidak kena.
    assert abs(p1[0] - 90.0) < 1e-6, p1[0]
    assert split[0] == 0
    xs = apply_costs(30.0, p1, p2, split)
    assert float(xs[0]) > 1.15, xs[0]
    part = {
        "bar_t": np.array([20.0, 50.0], np.float64),
        "bar_hi": np.array([50.0, 100.0], np.float64),
        "bar_lo": np.array([50.0, 100.0], np.float64),
        "bar_tick": np.array([1, 1], np.int8),
        "tick_t": np.array([20.0, 50.0], np.float64),
        "tick_px": np.array([50.0, 100.0], np.float64),
        "anchor": 30.0, "cov": 500.0,
        "cs_start": np.array([0.0], np.float64),
        "cs_close": np.array([30.0], np.float64),
        "m0": 30.0, "end": 500.0,
    }
    pex = [dict(kind=2, tp=1.5, sl=0.5, T=600, arm=0.0, trail=0.0, tp2=3.0, name="parsial")]
    p1, p2, split, tout = sim_one(part, 5.0, 0.4, 30.0, exits_arrays(pex), -1.0)
    assert split[0] == 1 and abs(p1[0] - 50) < 1e-6 and abs(p2[0] - 100) < 1e-6, (p1, p2, split)
    tr = {
        "bar_t": np.array([20.0, 40.0], np.float64),
        "bar_hi": np.array([60.0, 60.0], np.float64),
        "bar_lo": np.array([60.0, 40.0], np.float64),
        "bar_tick": np.array([1, 0], np.int8),
        "tick_t": np.array([20.0], np.float64),
        "tick_px": np.array([60.0], np.float64),
        "anchor": 30.0, "cov": 500.0,
        "cs_start": np.array([0.0, 30.0], np.float64),
        "cs_close": np.array([30.0, 40.0], np.float64),
        "m0": 30.0, "end": 500.0,
    }
    tex = [dict(kind=1, tp=1e9, sl=0.5, T=600, arm=0.5, trail=0.20, tp2=0.0, name="trail")]
    p1, _p2, split, _to = sim_one(tr, 5.0, 0.4, 30.0, exits_arrays(tex), -1.0)
    # puncak 60, trail 20% → stop 48, candle ×0,72
    assert abs(p1[0] - 48.0 * 0.72) < 1e-6, p1[0]
    # price_at vs kol.Path pada koin sintetis
    import tempfile
    td = tempfile.mkdtemp()
    rec = os.path.join(td, "rec")
    os.makedirs(rec)
    feats_idx = {name: i for i, name in enumerate(ms.FEATURES)}

    def snap(age, mc, liq, buyers=20, growth=1.1):
        fv = [0.0] * len(ms.FEATURES)
        fv[feats_idx["inflow_sol"]] = liq
        fv[feats_idx["unique_buyers"]] = buyers
        fv[feats_idx["holders"]] = 30
        fv[feats_idx["top10"]] = 0.2
        fv[feats_idx["liq_sol"]] = liq
        fv[feats_idx["growth"]] = growth
        fv[feats_idx["drawdown"]] = 0.05
        fv[feats_idx["buy_sell_ratio"]] = 0.7
        fv[feats_idx["buyer_rate"]] = buyers / max(age, 1)
        fv[feats_idx["creator_prev_rugs"]] = 0
        return [age, mc] + [float(f"{x:.4g}") for x in fv]

    liq, mc = 5.0, (30 + 5.0) ** 2 / K_CURVE
    lines = []
    for i in range(36):
        t0 = 1700000000 + i * 900
        w = [[0.4, "DEV1234567", 1, 1.0], [2.0, "BUYER00001", 1, 0.5], [8.0, "BUYER00002", 1, 0.4]]
        if i % 2 == 0:
            w.insert(1, [0.5, "DEV1234567", 1, 1.0])
        cs = []
        for b in range(0, 40):
            # bucket 5s sampai 120s lalu 15s; cukup umur 10 menit
            px = mc * (1.8 if i == 35 and b > 12 else 1.0)
            cs.append([b, px * 1.02, px * 0.99, px, 0.2, 0.05, 2, 1])
        recj = {"m": f"M{i}", "t0": t0, "m0": mc, "end": 400.0, "dev": "DEV1234567", "w": w,
                "c": cs, "snaps": [snap(10, mc, liq), snap(30, mc, liq), snap(60, mc, liq, growth=1.02)]}
        lines.append(json.dumps(recj))
    with open(os.path.join(rec, "rec-20231114.jsonl"), "w") as f:
        f.write("\n".join(lines) + "\n")
    coins, meta = load_coins(td)
    assert meta["n_dup_rows"] > 0, meta
    assert coins, "std kosong — rumus kurva fixture salah"
    assert abs(coins[0].devbuy - 1.0) < 1e-9, coins[0].devbuy
    for i, c in enumerate(coins):
        c.i = i
    pa = extract_path(coins[0])
    p = kol.Path(coins[0], 0)
    for t in (0.0, 0.4, 5.0, 30.0, 100.0, 250.0):
        a, b = price_at_py(pa, t), p.price_at(t)
        assert abs(a - b) < 1e-6, (t, a, b)
    events = prepare(coins)
    t0s = np.array([c.t0 for c in coins])
    per = np.where(t0s < t0s[int(len(coins) * 0.5)], 0, np.where(t0s < t0s[int(len(coins) * 0.7)], 1, 2))
    paths = [extract_path(c) for c in coins]
    groups = build_groups(coins, paths, per, events, make_exits(False))
    assert any(g.family == "Bom" for g in groups)
    R = evaluate(groups, {**meta, "n_used": len(coins), "nA": int((per == 0).sum()),
                          "nB": int((per == 1).sum()), "nC": int((per == 2).sum()),
                          "t_first": float(t0s[0]), "t_last": float(t0s[-1]),
                          "cut1": float(t0s[int(len(coins) * 0.5)]),
                          "cut2": float(t0s[int(len(coins) * 0.7)]),
                          "sha256": "test", "cache_key": "test", "n_std": len(coins)}, 2)
    assert R["k_combo"] > 1000
    assert len(R["null"]) == 2
    R["secs"] = 1
    text = build_report(R)
    assert text.startswith("TIDAK LAYAK") or text.startswith("LAYAK"), text[:80]
    print("self-test OK", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="riset")
    ap.add_argument("--sample", type=int, default=30000)
    ap.add_argument("--null", type=int, default=20)
    ap.add_argument("--report-name", default="riset-grid-luas-2026-11-10.md")
    ap.add_argument("--families", default="", help="Sniper,Bom,Momentum,Graduation,Copy. Kosong = semua.")
    ap.add_argument("--holdout-of", type=int, default=0,
                    help="Kalau >0, uji aturan terkunci pada koin di luar sampel merata sebesar ini.")
    ap.add_argument("--pick", type=int, default=5)
    ap.add_argument("--desc", type=int, default=10)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        self_test()
        return
    try:
        run(a)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        os.makedirs(a.out, exist_ok=True)
        err = os.path.join(a.out, a.report_name)
        with open(err, "w") as f:
            f.write("GAGAL. Skrip berhenti sebelum ada hasil.\n\n```\n" + traceback.format_exc() + "```\n")
        raise


if __name__ == "__main__":
    main()

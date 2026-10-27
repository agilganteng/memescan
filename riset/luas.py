"""Pencarian strategi SANGAT luas (27 Okt 2026): teknikal, copy wallet, dan hybrid, dengan penjaga kebetulan.

Desain (ditulis sebelum melihat hasil):
  Data : koin pump.fun dengan data wallet, 7 hari terakhir, urut waktu.
         W (0-25%)  nilai wallet | P (25-50%) pilih | T (50-100%) uji sekali. Hanya T untuk kesimpulan.
  Mesin: harga tiap koin dijadikan grid 5 dtk (0-1800 dtk). Sinyal & fitur hanya memakai candle yang SUDAH
         selesai (grid "as-of"). Isi beli = close candle yang memuat waktu sinyal + jeda acak 3-9 dtk.
         Exit dicek tiap 5 dtk, isi jual = close 1-2 slot kemudian (jeda 3-9 dtk). Dalam satu slot: stop dulu.
  Biaya: 2,5% dan 6% pulang-pergi. Posisi min(10% modal, $20), 1 posisi (variasi risk hanya untuk finalis).
  Ruang: 40 entry x 579 filter x 12 exit = 277.920 konfigurasi.
    entry  : umur 30/60/120/180/300/480 dtk | akselerasi volume (2 x 2) | breakout setelah konsolidasi (2) |
             beli dip setelah pump (4) | copy: 4 daftar wallet x 1/2 wallet x delay 0/15/45 dtk (24)
    filter : 17 fitur (harga, volume, likuiditas, top10, pembeli unik, konsentrasi, bot, sniper, flipper,
             dev jual, net beli, smart money, skor teknikal, skor wallet, skor gabungan), ambang dari kuantil P,
             tanpa filter / 1 syarat / 2 syarat
    exit   : waktu 60/180/600 dtk, SL+waktu, trailing (2), TP bertahap + trailing (2), volume decay,
             structure stop, tahan sampai akhir rekaman
  Penjaga kebetulan: (1) permutasi acak hasil di T untuk tiap kombinasi entry x exit -> berapa konfigurasi
  "untung" yang muncul hanya karena kebetulan; (2) korelasi rata P vs rata T semua konfigurasi;
  (3) persentase untung di T untuk 500 teratas P vs semua konfigurasi.
  "Lolos" = T >= 30 trade, batas bawah CI 95% rata > 1,0 di biaya 2,5%, rata > 1,0 di biaya 6%,
            dan simulasi $200 untung di kedua biaya.

Pakai: python3 riset/luas.py --data data
"""
import argparse
import itertools
import math
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep  # noqa: E402

w2, ms = deep.w2, deep.ms
NS, STEP = 360, 5.0
COSTS = {"2,5%": 0.0125, "6%": 0.03}
START = 200.0
CPS = (10, 30, 60, 120, 180, 300)


# ---------------------------------------------------------------- grid
def build_grid(coins):
    N = len(coins)
    H = np.empty((NS, N), np.float32)
    L = np.empty((NS, N), np.float32)
    C = np.empty((NS, N), np.float32)
    CA = np.empty((NS, N), np.float32)
    VA = np.zeros((NS, N), np.float32)
    end = np.zeros(N, np.int32)
    for j, c in enumerate(coins):
        h, l_, cl, ca, va = [None] * NS, [None] * NS, [None] * NS, [None] * NS, [None] * NS
        for k, (a, b, hi, lo, cc) in enumerate(c.cs):
            sa = min(NS - 1, int(a // STEP))
            sb = max(sa + 1, min(NS, int(math.ceil(b / STEP))))
            for s in range(sa, sb):
                h[s], l_[s], cl[s] = hi, lo, cc
            ca[sb - 1] = cc
            va[sb - 1] = c.cum_b[k] + c.cum_s[k]
        prev, pa, pv = c.m0, c.m0, 0.0
        for s in range(NS):
            if cl[s] is None:
                h[s] = l_[s] = cl[s] = prev
            prev = cl[s]
            if ca[s] is None:
                ca[s] = pa
            pa = ca[s]
            if va[s] is None:
                va[s] = pv
            pv = va[s]
        H[:, j], L[:, j], C[:, j], CA[:, j], VA[:, j] = h, l_, cl, ca, va
        end[j] = max(1, min(NS, int(math.ceil(c.end / STEP))))
    return H, L, C, CA, VA, end


# ---------------------------------------------------------------- exit tervektor
EXITS = [
    ("jual 60 dtk", dict(T=60)), ("jual 3 mnt", dict(T=180)), ("jual 10 mnt", dict(T=600)),
    ("SL10 + 5 mnt", dict(sl=0.10, T=300)), ("SL20 + 10 mnt", dict(sl=0.20, T=600)),
    ("SL15 trail 10% stl +20%", dict(sl=0.15, arm=0.20, tr=0.10, T=900)),
    ("SL25 trail 25% stl +50%", dict(sl=0.25, arm=0.50, tr=0.25, T=1200)),
    ("SL15 jual 30% di +25%, trail 12% stl +30%", dict(sl=0.15, tp=0.25, tpf=0.30, arm=0.30, tr=0.12, T=900)),
    ("SL25 jual 50% di +50%, trail 20%", dict(sl=0.25, tp=0.50, tpf=0.50, arm=0.50, tr=0.20, T=1500)),
    ("SL20 + volume decay 30%", dict(sl=0.20, vd=0.30, T=900)),
    ("structure stop (low 60 dtk) + 10 mnt", dict(struct=True, T=600)),
    ("tahan sampai akhir", dict(T=1800)),
]


def run_exit(G, cols, sig, rng, X):
    """G: grid yang sudah dipotong ke koin bersinyal (kolom = baris hasil); cols tidak dipakai lagi; sig: waktu sinyal (dtk). Return (gross x, waktu masuk, waktu keluar) per baris,
    gross NaN kalau tidak bisa masuk."""
    H, L, C, CA, VA, END = G
    M = len(cols)
    lat_in = rng.uniform(3, 9, M)
    lat_out = rng.uniform(3, 9, M)
    dl = np.where(lat_out <= 5, 1, 2)
    te = sig + lat_in
    es = np.floor(te / STEP).astype(np.int64)
    endc = END
    ok = es < endc
    es = np.minimum(es, NS - 1)
    ar = np.arange(M)
    fill = C[es, ar].astype(np.float64)
    ok &= fill > 0
    got, part = np.zeros(M), np.zeros(M)
    opn = ok.copy()
    xs = np.full(M, NS - 1)
    peak = fill.copy()
    armed = np.zeros(M, bool)
    slp = fill * (1 - X["sl"]) if X.get("sl") else np.full(M, -1.0)
    if X.get("struct"):
        ss = np.clip(np.floor(sig / STEP).astype(np.int64), 0, NS - 1)
        mn = np.full(M, np.inf)
        for k in range(1, 13):
            idx = np.clip(ss - k, 0, NS - 1)
            mn = np.minimum(mn, L[idx, ar])
        slp = np.minimum(mn * 0.98, fill * 0.98)
    tlim = es + int(X["T"] / STEP)
    if X.get("vd"):
        e6 = np.clip(es - 6, 0, NS - 1)
        ref = (VA[es, ar] - VA[e6, ar]).astype(np.float64)
    tr = X.get("tr", 0.0)
    for s in range(int(es[ok].min()) + 1 if ok.any() else NS, NS):
        act = opn & (s > es)
        if not act.any():
            if not opn.any():
                break
            continue
        h = H[s]
        lo = L[s]
        c = C[s].astype(np.float64)
        cn = np.where(dl == 1, C[min(s + 1, NS - 1)], C[min(s + 2, NS - 1)]).astype(np.float64)
        dead = act & (s >= endc)
        got[dead] += (1 - part[dead]) * c[dead]
        xs[dead] = s
        opn &= ~dead
        act &= ~dead
        stop = np.where(armed, np.maximum(slp, peak * (1 - tr)), slp)
        hit = act & (lo <= stop)
        if hit.any():
            got[hit] += (1 - part[hit]) * np.minimum(stop[hit], cn[hit])
            xs[hit] = s
            opn &= ~hit
            act &= ~hit
        if X.get("tp"):
            tpx = fill * (1 + X["tp"])
            th = act & (part == 0) & (h >= tpx)
            if th.any():
                got[th] += X["tpf"] * np.minimum(tpx[th], cn[th])
                part[th] = X["tpf"]
        peak = np.where(act, np.maximum(peak, h), peak)
        if X.get("arm"):
            armed |= act & (peak >= fill * (1 + X["arm"]))
            tx = act & armed & (c <= peak * (1 - tr))
            if tx.any():
                got[tx] += (1 - part[tx]) * np.minimum(peak[tx] * (1 - tr), cn[tx])
                xs[tx] = s
                opn &= ~tx
                act &= ~tx
        if X.get("vd"):
            s6 = max(0, s - 6)
            now = (VA[s] - VA[s6]).astype(np.float64)
            vx = act & (s - es >= 6) & (ref > 0) & (now < X["vd"] * ref)
            if vx.any():
                got[vx] += (1 - part[vx]) * cn[vx]
                xs[vx] = s
                opn &= ~vx
                act &= ~vx
        to = act & (s >= tlim)
        if to.any():
            got[to] += (1 - part[to]) * cn[to]
            xs[to] = s
            opn &= ~to
    if opn.any():
        got[opn] += (1 - part[opn]) * C[NS - 1][opn]
    gx = np.where(ok, got / np.where(fill > 0, fill, 1), np.nan)
    return gx, te, xs * STEP + STEP + lat_out


# ---------------------------------------------------------------- sinyal (entry)
def ev_age(a):
    def f(G, coins):
        return np.where(G[5] * STEP > a + 10, float(a), np.nan)
    return f


def first_true(cond, s_lo, s_hi):
    sub = cond[s_lo:s_hi]
    anyv = sub.any(axis=0)
    idx = sub.argmax(axis=0) + s_lo
    return np.where(anyv, (idx + 1) * STEP, np.nan)


def ev_accel(k, g):
    def f(G, coins):
        CA, VA, END = G[3], G[4], G[5]
        s = np.arange(NS)[:, None]
        v30 = VA - np.roll(VA, 6, axis=0)
        vp = np.roll(VA, 6, axis=0) - np.roll(VA, 12, axis=0)
        r30 = CA / np.maximum(np.roll(CA, 6, axis=0), 1e-12)
        cond = (v30 >= k * np.maximum(vp, 0.5)) & (v30 >= 2.0) & (r30 >= g) & (s >= 12) & (s < END[None, :])
        return first_true(cond, 12, 121)
    return f


def ev_breakout(tol):
    def f(G, coins):
        CA, END = G[3], G[5]
        mx = np.roll(CA, 1, axis=0)
        mn = mx.copy()
        for k in range(2, 13):
            r = np.roll(CA, k, axis=0)
            np.maximum(mx, r, out=mx)
            np.minimum(mn, r, out=mn)
            del r
        s = np.arange(NS)[:, None]
        cond = (mx / np.maximum(mn, 1e-12) <= 1 + tol) & (CA >= mx * 1.05) & (s >= 24) & (s < END[None, :])
        return first_true(cond, 24, 121)
    return f


def ev_dip(p, dd):
    def f(G, coins):
        CA, END = G[3], G[5]
        m0 = np.array([c.m0 for c in coins], np.float32)
        rm = np.maximum.accumulate(CA, axis=0)
        s = np.arange(NS)[:, None]
        cond = (rm >= p * m0[None, :]) & (CA <= rm * (1 - dd)) & (s >= 6) & (s < END[None, :])
        return first_true(cond, 6, 301)
    return f


def ev_copy(mask, k, delay):
    def f(G, coins):
        out = np.full(len(coins), np.nan)
        for j, c in enumerate(coins):
            ts = sorted(bl[0][0] for w, bl in c.buys.items() if mask[w])
            if len(ts) >= k:
                out[j] = ts[k - 1] + delay
        return out
    return f


# ---------------------------------------------------------------- fitur
TECH = ("naik_dari_awal", "naik_30dtk", "volume_60dtk", "akselerasi_vol", "likuiditas", "top10", "skor_teknikal")
WAL = ("pembeli_unik", "pembeli_terbesar", "porsi_bot", "porsi_sniper", "porsi_flip", "net_beli",
       "smart_money", "dev_jual", "skor_wallet")
BOTH = ("skor_gabungan",)
FEATS = TECH + WAL + BOTH


def wallet_cp(coins, beh):
    """Fitur wallet di umur 10/30/60/120/180/300 dtk (hanya trade sebelum umur itu)."""
    out = np.full((len(CPS), len(coins), 8), np.nan, np.float32)
    for j, c in enumerate(coins):
        for ci, a in enumerate(CPS):
            bsol, n_b, bot, sn, flip, mx, smart = 0.0, 0, 0.0, 0, 0, 0.0, 0
            for w, bl in c.buys.items():
                s = sum(v for t, v in bl if t < a)
                if s <= 0:
                    continue
                n_b += 1
                bsol += s
                mx = max(mx, s)
                if beh["bot"][w]:
                    bot += s
                sn += beh["sniper"][w]
                smart += beh["good"][w]
                flip += any(t < a for t, _ in c.sells.get(w, []))
            if n_b == 0:
                continue
            ssol = sum(v for sl in c.sells.values() for t, v in sl if t < a)
            dev = float(any(t < a for t, _ in c.sells.get(c.dev, [])))
            out[ci, j] = (n_b, mx / bsol, bot / bsol, sn / n_b, flip / n_b, bsol / (bsol + ssol), smart, dev)
    return out


def features(G, coins, sig, wcp):
    H, L, C, CA, VA, END = G
    M = len(coins)
    ar = np.arange(M)
    sa = np.clip(np.floor(np.nan_to_num(sig) / STEP).astype(np.int64) - 1, 0, NS - 1)
    s6, s12 = np.clip(sa - 6, 0, NS - 1), np.clip(sa - 12, 0, NS - 1)
    m0 = np.array([c.m0 for c in coins])
    ca = CA[sa, ar].astype(np.float64)
    F = {
        "naik_dari_awal": ca / m0,
        "naik_30dtk": ca / np.maximum(CA[s6, ar], 1e-12),
        "volume_60dtk": (VA[sa, ar] - VA[s12, ar]).astype(np.float64),
        "akselerasi_vol": (VA[sa, ar] - VA[s6, ar]) / np.maximum(VA[s6, ar] - VA[s12, ar], 0.1),
        "likuiditas": 2 * (np.sqrt(30 * 1.073e9 / 1e9 * np.maximum(ca, 1e-9)) - 30),
    }
    top = np.full(M, np.nan)
    for j, c in enumerate(coins):
        if not np.isnan(sig[j]):
            ag = [a for a in c.snaps if a <= sig[j]]
            if ag:
                top[j] = c.snaps[max(ag)][deep.FI["top10"]]
    F["top10"] = top
    cpi = np.full(M, -1)
    for ci, a in enumerate(CPS):
        cpi = np.where(np.nan_to_num(sig, nan=-1) >= a, ci, cpi)
    W = np.where((cpi >= 0)[:, None], wcp[np.maximum(cpi, 0), ar], np.nan)
    for k, nm in enumerate(("pembeli_unik", "pembeli_terbesar", "porsi_bot", "porsi_sniper", "porsi_flip",
                            "net_beli", "smart_money", "dev_jual")):
        F[nm] = W[:, k].astype(np.float64)
    return F


def pct_rank(v, ref):
    r = np.sort(ref[~np.isnan(ref)])
    if not len(r):
        return np.full(len(v), np.nan)
    out = np.searchsorted(r, np.nan_to_num(v), side="right") / len(r)
    return np.where(np.isnan(v), np.nan, out)


def add_scores(F, isP):
    def rk(name, neg=False):
        v = -F[name] if neg else F[name]
        return pct_rank(v, v[isP])
    F["skor_teknikal"] = np.nanmean([rk("naik_30dtk"), rk("akselerasi_vol"), rk("volume_60dtk")], axis=0)
    F["skor_wallet"] = np.nanmean([rk("smart_money"), rk("porsi_bot", True), rk("porsi_sniper", True),
                                   rk("pembeli_terbesar", True), rk("net_beli")], axis=0)
    F["skor_gabungan"] = F["skor_teknikal"] + F["skor_wallet"]


def conditions(F, isP):
    """List (nama, fitur, mask)."""
    out = []
    for nm in FEATS:
        v = F[nm]
        if nm == "smart_money":
            out += [("smart money >= 1", nm, v >= 1), ("tanpa smart money", nm, v == 0)]
            continue
        if nm == "dev_jual":
            out += [("dev sudah jual", nm, v == 1), ("dev belum jual", nm, v == 0)]
            continue
        ref = v[isP & ~np.isnan(v)]
        if len(ref) < 30:
            continue
        if nm.startswith("skor"):
            for q in (0.67, 0.90):
                t = float(np.quantile(ref, q))
                out.append((f"{nm} >= q{int(q * 100)}", nm, v >= t))
            continue
        lo, hi = np.quantile(ref, [0.33, 0.67])
        out += [(f"{nm} <= {lo:.3g}", nm, v <= lo), (f"{nm} >= {hi:.3g}", nm, v >= hi)]
    return out


# ---------------------------------------------------------------- simulasi $200
def sim200(t_in, x, t_out, size=0.10, cap=20.0, per_day=None, per_hour=None):
    eq, busy, rows, peak, mdd, pd_, ph = START, -1.0, [], START, 0.0, {}, {}
    for t, v, tx in sorted(zip(t_in, x, t_out)):
        if t < busy:
            continue
        d, hh = int(t // 86400), int(t // 3600)
        if per_day and pd_.get(d, 0) >= per_day:
            continue
        if per_hour and ph.get(hh, 0) >= per_hour:
            continue
        pd_[d] = pd_.get(d, 0) + 1
        ph[hh] = ph.get(hh, 0) + 1
        st = min(eq * size, cap)
        eq += st * (v - 1)
        busy = tx
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        rows.append((v, st * (v - 1)))
    n = len(rows)
    if not n:
        return dict(n=0, eq=eq)
    wins = [r for r in rows if r[0] > 1]
    loss = [r for r in rows if r[0] <= 1]
    gw, gl = sum(r[1] for r in wins), -sum(r[1] for r in loss)
    return dict(n=n, eq=eq, mdd=mdd, win=len(wins) / n, ci=ms.wilson(len(wins), n),
                aw=float(np.mean([r[0] - 1 for r in wins])) if wins else 0.0,
                al=float(np.mean([r[0] - 1 for r in loss])) if loss else 0.0,
                pf=gw / gl if gl else float("inf"), dump=sum(r[0] < 0.7 for r in rows))


def fmt_sim(s):
    if not s["n"]:
        return "0 trade"
    return (f"{s['n']} trade, menang {s['win']:.0%} (CI {s['ci'][0]:.0%}-{s['ci'][1]:.0%}), "
            f"rata menang {s['aw']:+.0%} / kalah {s['al']:+.0%}, $200 -> ${s['eq']:.2f} ({s['eq'] / START - 1:+.0%}), "
            f"MDD {s['mdd']:.0%}, PF {s['pf']:.2f}, dump >30% {s['dump']}")


# ---------------------------------------------------------------- utama
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--floor", default="lookahead", choices=("lookahead", "causal", "cap"),
                    help="lookahead: buang koin yang kapan pun di bawah lantai kurva (pakai info masa depan); "
                         "causal: buang sinyal setelah harga di bawah lantai terlihat, hasil trade apa adanya; "
                         "cap: seperti causal, tapi untung dari koin itu dipotong jadi maks 1,0x")
    a = ap.parse_args()
    t0 = time.time()
    cfg = ms.load_config(a.data)
    coins, wid, n_bad = deep.load(a.data, "lookahead" if a.floor == "lookahead" else "causal")
    print(f"== MODE LANTAI: {a.floor}")
    N = len(coins)
    W, PT = coins[:N // 4], coins[N // 4:]
    nP = N // 2 - N // 4
    ts = lambda c: time.strftime("%d/%m %H:%M", time.gmtime(c.t0))
    print(f"== {N:,} koin ({n_bad} kurva tidak standar dibuang), {len(wid):,} wallet. "
          f"W {ts(W[0])}-{ts(W[-1])} | P {ts(PT[0])}-{ts(PT[nP - 1])} | T {ts(PT[nP])}-{ts(PT[-1])} UTC")
    lists, beh, sizes = deep.wallet_lists(W, len(wid), cfg)
    W3 = W[2 * len(W) // 3:]
    S3 = w2.wallet_stats(W3, len(wid), cfg, W3[len(W3) // 2].t0)
    lists["L4 baru untung (sepertiga akhir W: >= 3 koin, copy >= 1,3x)"] = (
        (S3["n"] >= 3) & (np.nan_to_num(S3["cp_mean"]) >= 1.3) & ~S3["sniper"].astype(bool))
    for k, v in lists.items():
        print(f"   {k}: {int(v.sum())} wallet")
    G = build_grid(PT)
    isP = np.zeros(len(PT), bool)
    isP[:nP] = True
    wcp = wallet_cp(PT, beh)
    t0abs = np.array([c.t0 for c in PT])
    tbad = np.array([c.tbad for c in PT])
    print(f"   Koin P+T yang pernah di bawah lantai kurva: {int(np.isfinite(tbad).sum()):,} dari {len(PT):,}")
    print(f"   Grid + fitur wallet siap ({time.time() - t0:.0f} dtk).")

    events = [(f"umur {x} dtk", ev_age(x), "teknikal") for x in (30, 60, 120, 180, 300, 480)]
    events += [(f"akselerasi volume >= {k}x, naik >= {g}x (30 dtk)", ev_accel(k, g), "teknikal")
               for k in (2, 4) for g in (1.0, 1.2)]
    events += [(f"breakout setelah konsolidasi 60 dtk (range <= {int(t * 100)}%)", ev_breakout(t), "teknikal")
               for t in (0.15, 0.30)]
    events += [(f"beli dip: sudah {p}x lalu turun {int(d * 100)}%", ev_dip(p, d), "teknikal")
               for p in (2, 3) for d in (0.4, 0.6)]
    events += [(f"copy {ln[:2]}, {k} wallet, delay +{dl} dtk", ev_copy(m, k, dl), "copy")
               for ln, m in lists.items() for k in (1, 2) for dl in (0, 15, 45)]

    rows = []        # (ei, xi, ci, nP, mP, nT, mT, loT, mT6, nullT)
    keep = {}        # (ei, xi) -> data untuk finalis
    n_cfg = 0
    perm_rng = np.random.default_rng(99)
    for ei, (ename, fn, kind) in enumerate(events):
        sig = fn(G, PT)
        sig = np.where(sig >= tbad, np.nan, sig)     # bot sudah melihat harga di bawah lantai -> lewati
        cols = np.nonzero(~np.isnan(sig))[0]
        if len(cols) < 60:
            print(f"  [{ename}] {len(cols)} sinyal, dilewati")
            continue
        sub = [PT[j] for j in cols]
        Gs = tuple(g[:, cols] for g in G[:5]) + (G[5][cols],)
        F = features(Gs, sub, sig[cols], wcp[:, cols])
        isPs = isP[cols]
        add_scores(F, isPs)
        conds = conditions(F, isPs)
        filt = [("tanpa filter", (), np.ones(len(cols), bool))]
        filt += [(n, (f,), m) for n, f, m in conds]
        filt += [(f"{n1} & {n2}", (f1, f2), m1 & m2) for (n1, f1, m1), (n2, f2, m2) in itertools.combinations(conds, 2)
                 if f1 != f2]
        Mk = np.array([m for _, _, m in filt], np.float32)
        fmeta = [(n, f) for n, f, _ in filt]
        packed = np.packbits(Mk.astype(bool), axis=1)
        del filt
        nfilt = len(fmeta)
        loc = np.arange(len(cols))
        for xi, (xname, X) in enumerate(EXITS):
            rng = np.random.default_rng(ei * 100 + xi)
            gx, te, tx = run_exit(Gs, loc, sig[cols], rng, X)
            if a.floor == "cap":
                gx = np.where(np.isfinite(tbad[cols]), np.minimum(gx, 1.0), gx)
            valid = ~np.isnan(gx)
            x25 = np.where(valid, gx * (1 - COSTS["2,5%"]) / (1 + COSTS["2,5%"]), 0.0)
            x6 = np.where(valid, gx * (1 - COSTS["6%"]) / (1 + COSTS["6%"]), 0.0)
            vP, vT = (valid & isPs).astype(np.float32), (valid & ~isPs).astype(np.float32)
            xT = x25 * vT
            perm = np.zeros_like(xT)
            idxT = np.nonzero(vT > 0)[0]
            perm[idxT] = perm_rng.permutation(x25[idxT])
            f32 = lambda v: np.ascontiguousarray(v, np.float32)
            nPv, sP = Mk @ vP, Mk @ f32(x25 * vP)
            nTv, sT, sT2 = Mk @ vT, Mk @ f32(xT), Mk @ f32(xT * xT)
            sT6, sN = Mk @ f32(x6 * vT), Mk @ f32(perm)
            sN2 = Mk @ f32(perm * perm)
            n_cfg += nfilt
            for ci in range(nfilt):
                if nPv[ci] < 30:
                    continue
                nt = nTv[ci]
                mT = sT[ci] / nt if nt else np.nan
                var = (sT2[ci] / nt - mT * mT) * nt / max(nt - 1, 1) if nt > 1 else np.nan
                loT = mT - 1.96 * math.sqrt(max(var, 0) / nt) if nt > 1 else np.nan
                mN = sN[ci] / nt if nt else np.nan
                varN = (sN2[ci] / nt - mN * mN) * nt / max(nt - 1, 1) if nt > 1 else np.nan
                loN = mN - 1.96 * math.sqrt(max(varN, 0) / nt) if nt > 1 else np.nan
                rows.append((ei, xi, ci, int(nPv[ci]), sP[ci] / nPv[ci], int(nt), mT, loT,
                             sT6[ci] / nt if nt else np.nan, mN, loN))
            keep[(ei, xi)] = (cols, fmeta, packed, len(cols), gx.astype(np.float32), te.astype(np.float32),
                              tx.astype(np.float32), isPs)
        print(f"  [{ename}] {len(cols):,} sinyal (P {int(isPs.sum()):,} / T {int((~isPs).sum()):,}), "
              f"{nfilt} filter x {len(EXITS)} exit. {time.time() - t0:.0f} dtk", flush=True)

    R = np.array([r[3:] for r in rows], np.float64)
    E = np.array([r[:3] for r in rows], np.int64)
    nP_, mP, nT_, mT, loT, mT6, mN, loN = R.T
    okT = nT_ >= 30
    print(f"\n==== TOTAL: {n_cfg:,} konfigurasi diuji ({len(events)} entry x filter x {len(EXITS)} exit). "
          f"{len(rows):,} punya >= 30 trade di P.")
    posP = mP > 1
    print(f"  Untung di P: {int(posP.sum()):,} ({posP.mean():.1%}).")
    print(f"  Untung di P dan >= 30 trade di T: {int((posP & okT).sum()):,}; dari itu untung di T (2,5%): "
          f"{int((posP & okT & (mT > 1)).sum()):,}, untung di T (6%): {int((posP & okT & (mT6 > 1)).sum()):,}, "
          f"CI bawah > 1 di T: {int((posP & okT & (loT > 1)).sum()):,}.")
    print(f"  Semua konfigurasi dengan >= 30 trade di T: {int(okT.sum()):,}; untung di T (2,5%): "
          f"{int((okT & (mT > 1)).sum()):,} ({(okT & (mT > 1)).sum() / max(okT.sum(), 1):.2%}); "
          f"CI bawah > 1: {int((okT & (loT > 1)).sum()):,}.")
    print(f"  PEMBANDING KEBETULAN (hasil T diacak antar koin): untung {int((okT & (mN > 1)).sum()):,}, "
          f"CI bawah > 1: {int((okT & (loN > 1)).sum()):,}.")
    sel = np.nonzero(okT)[0]
    if len(sel) > 10:
        rP, rT = np.argsort(np.argsort(mP[sel])), np.argsort(np.argsort(mT[sel]))
        rho = np.corrcoef(rP, rT)[0, 1]
        top = sel[np.argsort(-mP[sel])][:500]
        print(f"  Korelasi peringkat P vs T (Spearman): {rho:.3f}. 500 teratas P: rata T {np.mean(mT[top]):.3f}x, "
              f"untung di T {np.mean(mT[top] > 1):.1%} (semua: rata T {np.mean(mT[sel]):.3f}x, "
              f"untung {np.mean(mT[sel] > 1):.1%}).")

    # ringkasan per keluarga
    def family(r):
        ei, xi, ci = r
        kind = events[ei][2]
        fl = keep[(ei, xi)][1][ci][1]
        has_w = any(f in WAL or f in BOTH for f in fl)
        has_t = any(f in TECH or f in BOTH for f in fl)
        if kind == "teknikal":
            return "Hybrid A: entry teknikal + filter wallet" if has_w else "Non-copy: teknikal saja"
        return "Hybrid B: copy + filter teknikal" if has_t else "Copy wallet saja"
    fam = np.array([family(tuple(e)) for e in E])
    print("\n==== PER KELUARGA (konfigurasi dengan >= 30 trade di P)")
    for f in sorted(set(fam)):
        m = fam == f
        print(f"  {f}: {int(m.sum()):,} konfig | untung di P {int((m & posP).sum()):,} | dari itu bertahan di T "
              f"(>= 30 trade, 2,5%) {int((m & posP & okT & (mT > 1)).sum()):,}, di 6% {int((m & posP & okT & (mT6 > 1)).sum()):,}, "
              f"CI bawah > 1 {int((m & posP & okT & (loT > 1)).sum()):,} | kebetulan (acak) {int((m & okT & (mN > 1)).sum()):,}")
    print("\n==== PER EXIT (rata T semua konfigurasi dengan >= 30 trade di T)")
    for xi, (xname, _) in enumerate(EXITS):
        m = okT & (E[:, 1] == xi)
        if m.any():
            print(f"  {xname}: rata T {np.mean(mT[m]):.3f}x, terbaik {np.max(mT[m]):.3f}x, untung {np.mean(mT[m] > 1):.1%}")

    def full(i, label):
        ei, xi, ci = E[i]
        cols, fmeta, packed, ncol, gx, te, tx, isPs = keep[(ei, xi)]
        fm = np.unpackbits(packed[ci])[:ncol].astype(bool)
        m = fm & ~isPs & ~np.isnan(gx)
        gx, te, tx = gx.astype(np.float64), te.astype(np.float64), tx.astype(np.float64)
        tin, tout = t0abs[cols][m] + te[m], t0abs[cols][m] + tx[m]
        print(f"\n {label} {events[ei][0]} | filter: {fmeta[ci][0]} | exit: {EXITS[xi][0]}")
        print(f"    P: {int(nP_[i])} sinyal rata {mP[i]:.3f}x | T: {int(nT_[i])} sinyal rata {mT[i]:.3f}x "
              f"(CI bawah {loT[i]:.3f}), biaya 6% {mT6[i]:.3f}x")
        g = np.sort(gx[m])
        k5 = max(1, len(g) // 20)
        nb = int(np.isfinite(tbad[cols][m]).sum())
        print(f"    T kotor: median {np.median(g):.3f}x, rata tanpa 5% trade terbaik {np.mean(g[:-k5]):.3f}x, "
              f"5 terbesar {', '.join(f'{v:.1f}x' for v in g[-5:][::-1])}; koin pernah di bawah lantai: {nb}")
        res = {}
        for cn, c in COSTS.items():
            xx = gx[m] * (1 - c) / (1 + c)
            res[cn] = sim200(tin, xx, tout)
            print(f"    $200 biaya {cn}: {fmt_sim(res[cn])}")
        return res, (tin, gx[m], tout)

    print("\n==== 10 TERATAS MENURUT P (dipilih jujur: tiap entry x exit maks 1), hasil di T")
    order = np.argsort(-mP)
    seen, fin = set(), []
    for i in order:
        if not okT[i] or nP_[i] < 50:
            continue
        key = (E[i][0], E[i][1])
        if key in seen:
            continue
        seen.add(key)
        fin.append(i)
        if len(fin) == 10:
            break
    passed = []
    for r, i in enumerate(fin):
        res, data = full(i, f"#{r + 1}")
        ok = (loT[i] > 1 and mT6[i] > 1 and res["2,5%"]["n"] >= 30 and res["2,5%"]["eq"] > START
              and res["6%"]["eq"] > START)
        print(f"    -> {'LOLOS' if ok else 'TIDAK LOLOS'}")
        if ok:
            passed.append((i, data))
    if fin:
        i = fin[0]
        _, (tin, g, tout) = full(i, "VARIASI RISK untuk #1:")
        for lab, kw in (("posisi 5% / maks $10", dict(size=0.05, cap=10.0)), ("maks 3 trade/hari", dict(per_day=3)),
                        ("maks 1 trade/jam", dict(per_hour=1))):
            for cn, c in COSTS.items():
                print(f"    {lab}, biaya {cn}: {fmt_sim(sim200(tin, g * (1 - c) / (1 + c), tout, **kw))}")

    print("\n==== 10 TERBAIK DI T (DIPILIH SETELAH MELIHAT T = cherry-pick, hanya gambaran batas atas)")
    order = np.argsort(-np.where(okT, mT, -1))
    seen, k = set(), 0
    for i in order:
        key = (E[i][0], E[i][1])
        if key in seen:
            continue
        seen.add(key)
        full(i, f"T#{k + 1}")
        k += 1
        if k == 10:
            break

    print(f"\n==== HASIL AKHIR: {len(passed)} dari 10 finalis pilihan P yang LOLOS semua syarat.")
    print(f"  Selesai {time.time() - t0:.0f} dtk. Paper saja. Data 20-27 Okt 2026; Jan 2026 - sekarang tidak bisa "
          "disimulasikan.")


if __name__ == "__main__":
    main()

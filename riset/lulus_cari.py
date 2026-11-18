#!/usr/bin/env python3
"""lulus_cari: pencarian besar "beli hanya lulusan PumpSwap yang jackpot, jual sebelum jatuh" (18 Nov 2026).

Data: perekam maju lulus.py (koin pump.fun yang lulus ke PumpSwap, harga DexScreener tiap ~60 dtk s/d 6 jam, lalu
tiap 5 menit s/d 72 jam). Horizon uji 48 jam setelah masuk. Harga lonjakan palsu dibuang (>3x / <1/3 median 5 tetangga), isi TP dibatasi 1,1x target.

Ruang cari (jutaan kombinasi):
  masuk   : 1, 10, 30, 60, 120, 360 menit setelah lulus terdeteksi; ATAU saat hype mulai: harga naik >=1,3/1,5/2x
            dalam 5 menit, atau pertama kali tembus 2x/3x/5x harga awal (beli di baris harga berikutnya, ~60 dtk)
  ciri    : ~40 ciri yang SUDAH diketahui saat masuk (latar belakang DexScreener/rugcheck/X saat lulus + jalur harga,
            likuiditas, volume, beli/jual sampai detik masuk). Tiap ciri -> aturan ambang di 9 kuantil x 2 arah.
  aturan  : 1 syarat dan semua pasangan 2 syarat (DAN)
  keluar  : 14 cara (tahan, TP/SL, trailing longgar/ketat, jual sebagian, batas waktu)
Pembagian waktu: W 40% pertama (cari), P 30% (pilih), T 30% terakhir (uji, tidak disentuh saat memilih).
Seleksi pakai hasil yang dipotong di 10x supaya tidak dipilih karena 1 koin; laporan T pakai hasil asli.
Lolos W: n>=40 dan rata>1,05. Lolos P: n>=25 dan rata>1. Uji T: n>=30, rata>1, rata tanpa koin terbaik>1.
Kontrol acak: hasil diacak antar koin (per waktu masuk, per bagian) lalu seluruh proses diulang.
Model: gradient boosting memprediksi "naik >=5x dalam 48 jam" dan "hasil keluar", latih W, pilih ambang di P, uji T.
"""
import argparse
import bisect
import gzip
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telecall as tc  # noqa: E402

COST = 0.015
HOR = 48 * 3600   # horizon maksimal; koin yang belum punya 6 jam + 48 jam data dibuang supaya bagian T utuh
ENTRIES = {"M1": 60, "M10": 600, "M30": 1800, "M60": 3600, "M120": 7200, "M360": 21600,
           # masuk saat hype mulai (dalam 24 jam pertama), beli di baris harga BERIKUTNYA (~60 dtk kemudian):
           "HYPE1.3": ("hype", 1.3), "HYPE1.5": ("hype", 1.5), "HYPE2": ("hype", 2.0),   # naik >= k dalam 5 menit
           "TEMBUS2": ("break", 2.0), "TEMBUS3": ("break", 3.0), "TEMBUS5": ("break", 5.0)}  # pertama kali >= k x harga awal


def entry_index(v, ts_, x, spec):
    if not isinstance(spec, tuple):
        t_in = x["t_seen"] + spec
        i0 = bisect.bisect_left(ts_, t_in)
        return i0 if i0 < len(v) and ts_[i0] - t_in <= 300 and v[i0][1] > 0 else None
    kind, k = spec
    first = next((z[1] for z in v if z[1] > 0), 0)
    if not first:
        return None
    for i in range(1, len(v) - 1):
        if ts_[i] - x["t_seen"] > 24 * 3600:
            return None
        p = v[i][1]
        if p <= 0:
            continue
        if kind == "break":
            hit = p >= k * first
        else:
            j = bisect.bisect_left(ts_, ts_[i] - 300)
            hit = j < i and v[j][1] > 0 and ts_[i] - ts_[j] <= 450 and p / v[j][1] >= k
        if hit:
            return i + 1 if ts_[i + 1] - ts_[i] <= 400 and v[i + 1][1] > 0 else None
    return None
EXITS = {
    "H1": dict(T=3600), "H6": dict(T=6 * 3600), "H24": dict(T=24 * 3600), "H72": dict(T=HOR),
    "TP2 SL30": dict(tp=2.0, sl=0.30, T=24 * 3600),
    "TP3 SL30": dict(tp=3.0, sl=0.30, T=HOR),
    "TP5 SL50": dict(tp=5.0, sl=0.50, T=HOR),
    "TP10 SL50": dict(tp=10.0, sl=0.50, T=HOR),
    "TRAIL20 SL20": dict(arm=1.0, trail=0.20, sl=0.20, T=HOR),
    "TRAIL30 arm1.5 SL40": dict(arm=1.5, trail=0.30, sl=0.40, T=HOR),
    "TRAIL50 arm2 SL50": dict(arm=2.0, trail=0.50, sl=0.50, T=HOR),
    "1/2@2x TRAIL30": dict(half=2.0, trail=0.30, sl=0.40, T=HOR),
    "1/2@3x TRAIL40": dict(half=3.0, trail=0.40, sl=0.50, T=HOR),
    "TP1.5 SL20 2j": dict(tp=1.5, sl=0.20, T=2 * 3600),
}


def sim(ts_, ps, i0, ex):
    p0, t0 = ps[i0], ts_[i0]
    T = ex["T"]
    held, got, peak, armed, last = 1.0, 0.0, p0, False, p0
    for k in range(i0 + 1, len(ps)):
        t, p = ts_[k], ps[k]
        if t - t0 > T:
            break
        if p <= 0:
            return got * (1 - COST) ** 2
        last = p
        r = p / p0
        if p > peak:
            peak = p
        if "half" in ex and held == 1.0 and r >= ex["half"]:
            got += 0.5 * min(r, ex["half"] * 1.1)
            held = 0.5
            armed = True
        if "tp" in ex and r >= ex["tp"]:
            got += held * min(r, ex["tp"] * 1.1)
            held = 0
            break
        if "arm" in ex and r >= ex["arm"]:
            armed = True
        if "trail" in ex and armed and p <= peak * (1 - ex["trail"]):
            got += held * r
            held = 0
            break
        if "sl" in ex and r <= 1 - ex["sl"]:
            got += held * r
            held = 0
            break
    if held:
        got += held * last / p0
    return got * (1 - COST) ** 2


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return math.nan


def load(data):
    d = os.path.join(data, "lulus")
    toks = {}
    for line in open(os.path.join(d, "tokens.jsonl")):
        try:
            x = json.loads(line)
            toks[x["mint"]] = x
        except (ValueError, KeyError):
            pass
    px, t_last = {}, 0
    for fn in sorted(os.listdir(d)):
        if fn.startswith("px-"):
            with gzip.open(os.path.join(d, fn), "rt") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    p = r[2] if r[3] >= 500 else 0.0
                    px.setdefault(r[1], []).append((r[0], p, r[3], r[4], r[5], r[6], r[7]))
                    t_last = max(t_last, r[0])
    drop = 0
    for m, v in px.items():
        v.sort()
        keep = []
        for i, q in enumerate(v):
            nb = sorted(z[1] for z in v[max(0, i - 2):i + 3] if z[1] > 0)
            med = nb[len(nb) // 2] if nb else 0
            if q[1] > 0 and med > 0 and (q[1] > 3 * med or q[1] < med / 3):
                drop += 1
                continue
            keep.append(q)
        px[m] = keep
    print(f"[data] {len(toks)} koin, {sum(len(v) for v in px.values()):,} baris harga, lonjakan palsu dibuang {drop}", flush=True)
    return toks, px, t_last


def static_feats(x):
    ds, rc, xp = x.get("ds") or {}, x.get("rc") or {}, x.get("xp") or {}
    b, s = num(ds.get("buys_h1")), num(ds.get("sells_h1"))
    return {
        "ds_mcap": num(ds.get("mcap")), "ds_liq": num(ds.get("liq")), "ds_umur_mnt": num(ds.get("age_min")),
        "ds_vol_h1": num(ds.get("vol_h1")), "ds_beli_h1": b, "ds_jual_h1": s,
        "ds_rasio_beli": b / (b + s) if b + s > 0 else math.nan, "ds_chg_h1": num(ds.get("chg_h1")),
        "ds_boost": num(ds.get("boosts")), "punya_x": float(bool(ds.get("x"))), "punya_tg": float(bool(ds.get("tg"))),
        "punya_web": float(bool(ds.get("web"))),
        "rc_skor": num(rc.get("risk_score")), "rc_top10": num(rc.get("top10_pct")), "rc_dev": num(rc.get("dev_pct")),
        "rc_insider": num(rc.get("insiders")), "rc_holder": num(rc.get("holders")),
        "rc_lp_kunci": num(rc.get("lp_locked_pct")), "rc_bahaya": float(len(rc.get("danger") or [])) if rc else math.nan,
        "x_follower": num(xp.get("followers")), "x_umur_hr": num(xp.get("age_d")),
        "x_akun": float(xp.get("kind") == "account"), "x_komunitas": float(xp.get("kind") == "community"),
        "telat_dtk": num(x.get("t_seen", 0) - x["t_pool"]) if x.get("t_pool") else math.nan,
        "jam_utc": float(time.gmtime(x["t_seen"]).tm_hour),
        "gt_fdv": num(x.get("gt_fdv")), "gt_liq": num(x.get("gt_liq")),
    }


def dyn_feats(v, i0):
    """Ciri jalur harga sampai baris masuk i0 (termasuk)."""
    q = v[i0]
    first = next((z for z in v[:i0 + 1] if z[1] > 0), None)
    ps = [z[1] for z in v[:i0 + 1] if z[1] > 0]
    out = {"liq_kini": q[2], "mcap_kini": q[3], "vol5": q[4], "beli5": q[5], "jual5": q[6],
           "rasio_beli5": q[5] / (q[5] + q[6]) if q[5] + q[6] > 0 else math.nan}
    if first and ps:
        out["ret_dari_awal"] = q[1] / first[1]
        out["puncak_dari_awal"] = max(ps) / first[1]
        out["turun_dari_puncak"] = q[1] / max(ps)
        out["dasar_dari_awal"] = min(ps) / first[1]
        out["liq_vs_awal"] = q[2] / first[2] if first[2] > 0 else math.nan
    t = q[0]
    for lab, back in (("ret5m", 300), ("ret15m", 900), ("ret60m", 3600)):
        j = bisect.bisect_left([z[0] for z in v[:i0 + 1]], t - back)
        out[lab] = q[1] / v[j][1] if j < i0 and v[j][1] > 0 and t - v[j][0] <= back * 1.5 else math.nan
    w = [z for z in v[:i0 + 1] if z[0] >= t - 1800]
    out["vol30m"] = float(sum(z[4] for z in w)) / max(1, len(w))
    out["beli30m"] = float(sum(z[5] for z in w))
    out["jual30m"] = float(sum(z[6] for z in w))
    out["rasio_beli30m"] = out["beli30m"] / (out["beli30m"] + out["jual30m"]) if out["beli30m"] + out["jual30m"] > 0 else math.nan
    return out


def build(toks, px, t_last):
    """Per waktu masuk: X (ciri), Y (hasil per exit, nan kalau jendela belum penuh), MX (naik maks 48j), seen."""
    out = {}
    for en, lag in ENTRIES.items():
        rows, ys, mxs, seen, mints = [], [], [], [], []
        for m, x in toks.items():
            v = px.get(m)
            if not v or x["t_seen"] + 21600 + HOR + 600 > t_last:
                continue
            ts_ = [z[0] for z in v]
            i0 = entry_index(v, ts_, x, lag)
            if i0 is None:
                continue
            ps = [z[1] for z in v]
            f = static_feats(x)
            f.update(dyn_feats(v, i0))
            f["menit_sejak_lulus"] = (ts_[i0] - x["t_seen"]) / 60
            y = []
            for ex in EXITS.values():
                y.append(sim(ts_, ps, i0, ex) if ts_[i0] + ex["T"] <= t_last else math.nan)
            fut = [ps[k] for k in range(i0, len(ps)) if ts_[k] - ts_[i0] <= HOR]
            mxs.append(max(fut) / ps[i0] if ts_[i0] + HOR <= t_last else math.nan)
            rows.append(f)
            ys.append(y)
            seen.append(x["t_seen"])
            mints.append(m)
        if len(rows) < 150:
            print(f"[bangun] {en}: hanya {len(rows)} kejadian, dilewati", flush=True)
            continue
        names = sorted({k for r in rows for k in r})
        X = np.array([[r.get(k, math.nan) for k in names] for r in rows], dtype=np.float64)
        out[en] = dict(names=names, X=X, Y=np.array(ys, dtype=np.float64), MX=np.array(mxs), seen=np.array(seen))
        print(f"[bangun] {en}: {len(rows)} kejadian, {len(names)} ciri ({time.time() - T0:.0f}s)", flush=True)
    return out


def rules(X, names, wmask):
    """Aturan ambang: kuantil 10..90% dihitung HANYA di W. Hasil: matriks bool (R x n) dan label."""
    M, labs = [], []
    for j, nm in enumerate(names):
        col = X[:, j]
        w = col[wmask & ~np.isnan(col)]
        if len(w) < 50:
            continue
        seen_thr = set()
        for qv in np.unique(np.quantile(w, np.arange(0.1, 0.95, 0.1))):
            if qv in seen_thr:
                continue
            seen_thr.add(qv)
            for op in (">=", "<="):
                with np.errstate(invalid="ignore"):
                    mk = (col >= qv) if op == ">=" else (col <= qv)
                mk = mk & ~np.isnan(col)
                fr = mk[wmask].mean()
                if 0.03 <= fr <= 0.97:
                    M.append(mk)
                    labs.append(f"{nm}{op}{qv:.4g}")
    return np.array(M, dtype=np.float32), labs


def grid(M, Yc, masks, shuffle=None):
    """Hitung n dan rata (hasil dipotong) untuk semua pasangan aturan, per bagian dan exit.
    Kembalikan dict[(bagian)] -> (N[e], S[e]) dengan bentuk (E, R, R)."""
    out = {}
    for part, pm in masks.items():
        Mp = M[:, pm]
        Y = Yc[pm]
        if shuffle is not None:
            Y = Y[shuffle.permutation(len(Y))]
        Ns, Ss = [], []
        for e in range(Y.shape[1]):
            ok = ~np.isnan(Y[:, e])
            A = Mp[:, ok]
            y = Y[ok, e].astype(np.float32)
            Ns.append(A @ A.T)
            Ss.append((A * y) @ A.T)
        out[part] = (np.array(Ns), np.array(Ss))
    return out


def count_pass(g):
    def mean(part):
        N, S = g[part]
        with np.errstate(invalid="ignore", divide="ignore"):
            return N, S / N
    NW, MW = mean("W")
    NP, MP = mean("P")
    NT, MT = mean("T")
    iu = np.triu(np.ones(NW.shape[1:], bool))[None]
    w = (NW >= 40) & (MW > 1.05) & iu
    p = w & (NP >= 25) & (MP > 1.0)
    t = p & (NT >= 30) & (MT > 1.0)
    return w, p, t, MP, MT, NT


def stat(x):
    x = np.array(x, dtype=float)
    n = len(x)
    if n == 0:
        return "n=0"
    nb = (x.sum() - x.max()) / (n - 1) if n > 1 else 0
    b = 200.0
    for v in x:
        b += b * 0.10 * (v - 1)
    lo, hi = tc.wilson(int((x > 1).sum()), n)
    return (f"n={n} rata {x.mean():.3f}x tanpa-terbaik {nb:.3f}x median {np.median(x):.3f}x menang {(x > 1).mean():.0%} "
            f"[{lo:.0%}-{hi:.0%}] $200 -> ${b:,.0f}")


def banding(D, toks, px, t_last):
    """Beda koin jackpot (>=5x dalam 48 jam dari harga 1 menit setelah lulus) dengan koin biasa + waktu geraknya."""
    d = D["M1"]
    mx = d["MX"]
    ok = ~np.isnan(mx)
    J, B = ok & (mx >= 5), ok & (mx < 2)
    print(f"\n## BEDA JACKPOT vs BIASA (ciri 1 menit setelah lulus). jackpot >=5x: {int(J.sum())} koin ({J.sum() / ok.sum():.1%}); "
          f"biasa (<2x): {int(B.sum())} koin; >=10x: {int((ok & (mx >= 10)).sum())}", flush=True)
    rows = []
    for j, nm in enumerate(d["names"]):
        a, b = d["X"][J, j], d["X"][B, j]
        a, b = a[~np.isnan(a)], b[~np.isnan(b)]
        if len(a) < 20 or len(b) < 20:
            continue
        # AUC = peluang ciri koin jackpot lebih besar dari koin biasa (0,5 = tidak ada beda)
        allv = np.concatenate([a, b])
        u, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
        rk = (np.cumsum(cnt) - (cnt - 1) / 2.0)[inv]   # peringkat rata-rata untuk nilai kembar
        auc = (rk[:len(a)].sum() - len(a) * (len(a) + 1) / 2) / (len(a) * len(b))
        rows.append((abs(auc - 0.5), nm, np.median(a), np.median(b), auc))
    for _, nm, ma, mb, auc in sorted(rows, reverse=True)[:18]:
        print(f"  {nm:20s} median jackpot {ma:12.4g} | biasa {mb:12.4g} | daya pisah {auc:.2f}", flush=True)
    # waktu gerak koin jackpot
    t2, tpk, pk, left2, left3 = [], [], [], [], []
    for m, x in toks.items():
        v = px.get(m)
        if not v or x["t_seen"] + 21600 + HOR + 600 > t_last:
            continue
        ts_ = [z[0] for z in v]
        i0 = entry_index(v, ts_, x, 60)
        if i0 is None:
            continue
        p0 = v[i0][1]
        seg = [(z[0] - ts_[i0], z[1] / p0) for z in v[i0:] if z[0] - ts_[i0] <= HOR]
        mxr = max(r for _, r in seg)
        if mxr < 5:
            continue
        a2 = next(t for t, r in seg if r >= 2)
        ap = next(t for t, r in seg if r >= mxr)
        t2.append(a2 / 60)
        tpk.append(ap / 60)
        pk.append(mxr)
        left2.append(mxr / 2)
        a3 = next((t for t, r in seg if r >= 3), None)
        if a3 is not None:
            left3.append(mxr / 3)
    if t2:
        q = lambda z, p: float(np.quantile(z, p))
        print(f"  waktu koin jackpot: capai 2x median {q(t2, .5):.0f} mnt (p25 {q(t2, .25):.0f}, p75 {q(t2, .75):.0f}); capai puncak median "
              f"{q(tpk, .5):.0f} mnt (p25 {q(tpk, .25):.0f}, p75 {q(tpk, .75):.0f}); puncak median {q(pk, .5):.1f}x (p75 {q(pk, .75):.1f}x)", flush=True)
    # kalau masuk saat tembus 2x: berapa yang lanjut?
    for en in ("TEMBUS2", "TEMBUS3", "TEMBUS5", "HYPE1.3", "HYPE1.5", "HYPE2"):
        if en not in D:
            continue
        dd = D[en]
        m2 = dd["MX"][~np.isnan(dd["MX"])]
        if len(m2):
            print(f"  masuk {en}: {len(m2)} koin; setelah masuk naik lagi >=2x {(m2 >= 2).mean():.1%}, >=5x {(m2 >= 5).mean():.1%}; "
                  f"median naik maksimal {np.median(m2):.2f}x; masuk median menit ke-"
                  f"{np.nanmedian(dd['X'][:, dd['names'].index('menit_sejak_lulus')]):.0f}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--null", type=int, default=3)
    a = ap.parse_args()
    toks, px, t_last = load(a.data)
    D = build(toks, px, t_last)
    allseen = np.sort(np.concatenate([d["seen"] for d in D.values()]))
    c1, c2 = allseen[int(len(allseen) * 0.4)], allseen[int(len(allseen) * 0.7)]
    f = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"[bagi] W < {f(c1)} <= P < {f(c2)} <= T (UTC); data harga terakhir {f(t_last)}", flush=True)
    exn = list(EXITS)
    banding(D, toks, px, t_last)
    tot = {"combo": 0, "w": 0, "p": 0, "t": 0}
    nul = [dict(w=0, p=0, t=0) for _ in range(a.null)]
    finals = []
    print("\n## Dasar: beli SEMUA (tanpa filter), bagian T, hasil asli", flush=True)
    for en, d in D.items():
        tm = d["seen"] >= c2
        for e in (0, 2, 4, 9, 11):
            y = d["Y"][tm, e]
            if len(y):
                print(f"  {en} | {exn[e]}: {stat(y[~np.isnan(y)])}", flush=True)
    for en, d in D.items():
        masks = {"W": d["seen"] < c1, "P": (d["seen"] >= c1) & (d["seen"] < c2), "T": d["seen"] >= c2}
        M, labs = rules(d["X"], d["names"], masks["W"])
        Yc = np.minimum(d["Y"], 10.0)
        g = grid(M, Yc, masks)
        w, p, t, MP, MT, NT = count_pass(g)
        R = len(labs)
        ncombo = len(exn) * R * (R + 1) // 2
        tot["combo"] += ncombo
        tot["w"] += int(w.sum())
        tot["p"] += int(p.sum())
        tot["t"] += int(t.sum())
        print(f"[cari] {en}: {R} aturan dasar -> {ncombo:,} kombinasi; lolos W {int(w.sum()):,}, lolos W+P {int(p.sum()):,}, "
              f"dan untung di T (dipotong 10x) {int(t.sum()):,} ({time.time() - T0:.0f}s)", flush=True)
        idx = np.argwhere(p)
        if len(idx):
            sc = MP[p]
            for k in np.argsort(-sc)[:15]:
                e, i, j = idx[k]
                finals.append((en, e, i, j, labs[i], labs[j], float(sc[k]), M, d, masks))
        for s in range(a.null):
            rng = np.random.default_rng(100 + s)
            wn, pn, tn, _, _, _ = count_pass(grid(M, Yc, masks, shuffle=rng))
            nul[s]["w"] += int(wn.sum())
            nul[s]["p"] += int(pn.sum())
            nul[s]["t"] += int(tn.sum())
        del g
    print(f"\n## RINGKASAN PENCARIAN: {tot['combo']:,} kombinasi. Lolos W {tot['w']:,}; lolos W+P {tot['p']:,}; "
          f"lolos W+P dan untung di T {tot['t']:,}", flush=True)
    print(f"## KONTROL ACAK (hasil diacak, proses sama): {nul}", flush=True)
    print("\n## FINALIS: 15 teratas di P per waktu masuk -> hasil ASLI di T (tidak dipakai memilih)", flush=True)
    npass = 0
    for en, e, i, j, li, lj, sc, M, d, masks in finals:
        mk = (M[i] > 0) & (M[j] > 0) & masks["T"] & ~np.isnan(d["Y"][:, e])
        y = d["Y"][mk, e]
        ok = len(y) >= 30 and y.mean() > 1 and (y.sum() - y.max()) / (len(y) - 1) > 1
        npass += ok
        rule = li if i == j else f"{li} & {lj}"
        print(f"  {en} | {exn[e]} | {rule} | P {sc:.3f}x -> T {stat(y)}{'  <== LULUS' if ok else ''}", flush=True)
    print(f"## Finalis lulus di T: {npass} dari {len(finals)}", flush=True)

    # ---------------- model
    try:
        from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
        from sklearn.metrics import roc_auc_score
    except ImportError:
        print("sklearn tidak ada, model dilewati")
        return
    print("\n## MODEL (latih W, pilih ambang di P, uji T)", flush=True)
    for en, d in D.items():
        W, P, T = d["seen"] < c1, (d["seen"] >= c1) & (d["seen"] < c2), d["seen"] >= c2
        X = d["X"]
        okm = ~np.isnan(d["MX"])
        for lab, thr in (("jackpot>=5x", 5.0), ("jackpot>=10x", 10.0)):
            yj = (d["MX"] >= thr).astype(int)
            if yj[W & okm].sum() < 15:
                print(f"  {en} {lab}: contoh positif di W terlalu sedikit ({int(yj[W & okm].sum())})")
                continue
            clf = HistGradientBoostingClassifier(max_depth=3, max_iter=150, learning_rate=0.05, random_state=0)
            clf.fit(X[W & okm], yj[W & okm])
            s = clf.predict_proba(X)[:, 1]
            auc = roc_auc_score(yj[T & okm], s[T & okm]) if 0 < yj[T & okm].sum() < (T & okm).sum() else math.nan
            base = yj[T & okm].mean()
            print(f"  {en} {lab}: AUC di T {auc:.3f}; kejadian dasar di T {base:.2%}", flush=True)
            for top in (0.01, 0.02, 0.05, 0.10):
                cut = np.quantile(s[P], 1 - top)
                hit = yj[T & okm & (s >= cut)]
                best = None
                for e in range(len(exn)):
                    yp = np.minimum(d["Y"][P & (s >= cut), e], 10.0)
                    yp = yp[~np.isnan(yp)]
                    if len(yp) >= 10 and (best is None or yp.mean() > best[1]):
                        best = (e, yp.mean())
                if best is None:
                    continue
                yt = d["Y"][T & (s >= cut), best[0]]
                yt = yt[~np.isnan(yt)]
                print(f"    skor {top:.0%} teratas: kena {lab} {hit.mean() if len(hit) else 0:.1%} (n {len(hit)}); exit terbaik di P "
                      f"{exn[best[0]]} ({best[1]:.3f}x) -> T {stat(yt)}", flush=True)
        for e in (4, 6, 9, 11):
            okw = W & ~np.isnan(d["Y"][:, e])
            if okw.sum() < 200:
                continue
            reg = HistGradientBoostingRegressor(max_depth=3, max_iter=150, learning_rate=0.05, random_state=0)
            reg.fit(X[okw], np.minimum(d["Y"][okw, e], 10.0))
            s = reg.predict(X)
            for top in (0.02, 0.05, 0.10):
                cut = np.quantile(s[P], 1 - top)
                yp = d["Y"][P & (s >= cut), e]
                yp = yp[~np.isnan(yp)]
                yt = d["Y"][T & (s >= cut), e]
                yt = yt[~np.isnan(yt)]
                print(f"  {en} regresi {exn[e]} skor {top:.0%} teratas: P rata {np.minimum(yp, 10).mean() if len(yp) else 0:.3f}x "
                      f"-> T {stat(yt)}", flush=True)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


T0 = time.time()
if __name__ == "__main__":
    main()

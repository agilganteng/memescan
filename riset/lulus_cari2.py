#!/usr/bin/env python3
"""lulus_cari2: putaran lanjutan pencarian lulusan PumpSwap, dengan UJI MAJU otomatis (18 Nov 2026).

Beda dari lulus_cari:
  - pool bukan memecoin baru dibuang (gt_fdv > $1 juta: token lama yang membuka pool PumpSwap, harga nyaris diam).
  - horizon 12 jam (set 2) atau 1 jam (set 3), supaya koin 16-18 Nov bisa dipakai sebagai data MAJU (F).
  - W/P/T dibagi 40/30/30 dari koin yang lulus SEBELUM 16 Nov 00:45 UTC; F = setelahnya, tidak pernah dipakai memilih.
  - set 2: 14 cara keluar pendek (15 menit s/d 12 jam). set 3: 14 cara keluar sangat pendek (5 menit s/d 1 jam).
Hitungan jujur: berapa kombinasi yang lolos W+P+T DAN untung di F, dibanding kontrol acak (hasil diacak).
Finalis (10 teratas per cara masuk menurut min(P,T)) dilaporkan dengan hasil ASLI di F.
Lulus F: n >= 30, rata > 1, rata tanpa koin terbaik > 1.
"""
import argparse
import calendar
import time

import numpy as np

import lulus_cari as lc

CUT = calendar.timegm((2026, 11, 16, 0, 45, 0))
H = 3600
SETS = {
    2: (12 * H, {
        "H15m": dict(T=900), "H30m": dict(T=1800), "H2": dict(T=2 * H), "H3": dict(T=3 * H), "H12": dict(T=12 * H),
        "TP1.3 SL15 1j": dict(tp=1.3, sl=0.15, T=H), "TP1.5 SL30 6j": dict(tp=1.5, sl=0.30, T=6 * H),
        "TP2 SL50 12j": dict(tp=2.0, sl=0.50, T=12 * H), "TP3 SL50 12j": dict(tp=3.0, sl=0.50, T=12 * H),
        "TP4 SL40 12j": dict(tp=4.0, sl=0.40, T=12 * H),
        "TRAIL15 arm1.2 SL15": dict(arm=1.2, trail=0.15, sl=0.15, T=12 * H),
        "TRAIL25 arm1.3 SL25": dict(arm=1.3, trail=0.25, sl=0.25, T=12 * H),
        "TRAIL40 arm1.5 SL40": dict(arm=1.5, trail=0.40, sl=0.40, T=12 * H),
        "1/2@1.5 TRAIL25": dict(half=1.5, trail=0.25, sl=0.30, T=12 * H)}),
    3: (H, {
        "H5m": dict(T=300), "H10m": dict(T=600), "H20m": dict(T=1200), "H45m": dict(T=2700),
        "TP1.1 SL10": dict(tp=1.1, sl=0.10, T=H), "TP1.2 SL10": dict(tp=1.2, sl=0.10, T=H),
        "TP1.2 SL20": dict(tp=1.2, sl=0.20, T=H), "TP1.3 SL20 30m": dict(tp=1.3, sl=0.20, T=1800),
        "TP1.5 SL15": dict(tp=1.5, sl=0.15, T=H), "TP2 SL20": dict(tp=2.0, sl=0.20, T=H),
        "TRAIL10 arm1.1 SL10": dict(arm=1.1, trail=0.10, sl=0.10, T=H),
        "TRAIL15 arm1.0 SL15": dict(arm=1.0, trail=0.15, sl=0.15, T=H),
        "TRAIL20 arm1.3 SL20": dict(arm=1.3, trail=0.20, sl=0.20, T=H),
        "1/2@1.2 TRAIL15": dict(half=1.2, trail=0.15, sl=0.20, T=H)}),
}


def cnt(g):
    def mean(part):
        N, S = g[part]
        with np.errstate(invalid="ignore", divide="ignore"):
            return N, S / N
    NW, MW = mean("W")
    NP, MP = mean("P")
    NT, MT = mean("T")
    NF, MF = mean("F")
    iu = np.triu(np.ones(NW.shape[1:], bool))[None]
    w = (NW >= 40) & (MW > 1.05) & iu
    p = w & (NP >= 25) & (MP > 1.0)
    t = p & (NT >= 25) & (MT > 1.0)
    f = t & (NF >= 20) & (MF > 1.0)
    return w, p, t, f, MP, MT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--set", type=int, default=2)
    ap.add_argument("--null", type=int, default=3)
    a = ap.parse_args()
    lc.HOR, lc.EXITS = SETS[a.set]
    toks, px, t_last = lc.load(a.data)
    n0 = len(toks)
    toks = {m: x for m, x in toks.items() if not (lc.num(x.get("gt_fdv")) > 1e6)}
    print(f"[saring] pool gt_fdv > $1 juta dibuang: {n0 - len(toks)} dari {n0}", flush=True)
    D = lc.build(toks, px, t_last)
    pre = np.sort(np.concatenate([d["seen"][d["seen"] < CUT] for d in D.values()]))
    c1, c2 = pre[int(len(pre) * 0.4)], pre[int(len(pre) * 0.7)]
    f = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"[bagi] set {a.set}: W < {f(c1)} <= P < {f(c2)} <= T < {f(CUT)} <= F (maju); data terakhir {f(t_last)}", flush=True)
    exn = list(lc.EXITS)
    tot = dict(combo=0, w=0, p=0, t=0, f=0)
    nul = [dict(w=0, p=0, t=0, f=0) for _ in range(a.null)]
    finals = []
    print("\n## Dasar: beli SEMUA di data maju F", flush=True)
    for en, d in D.items():
        fm = d["seen"] >= CUT
        for e in (1, 6, 11):
            y = d["Y"][fm, e]
            y = y[~np.isnan(y)]
            if len(y):
                print(f"  {en} | {exn[e]}: {lc.stat(y)}", flush=True)
    for en, d in D.items():
        s = d["seen"]
        masks = {"W": s < c1, "P": (s >= c1) & (s < c2), "T": (s >= c2) & (s < CUT), "F": s >= CUT}
        if masks["F"].sum() < 40 or masks["W"].sum() < 150:
            print(f"[cari] {en}: data terlalu sedikit (W {int(masks['W'].sum())}, F {int(masks['F'].sum())}), dilewati", flush=True)
            continue
        M, labs = lc.rules(d["X"], d["names"], masks["W"])
        Yc = np.minimum(d["Y"], 10.0)
        w, p, t, ff, MP, MT = cnt(lc.grid(M, Yc, masks))
        R = len(labs)
        tot["combo"] += len(exn) * R * (R + 1) // 2
        for k, v in (("w", w), ("p", p), ("t", t), ("f", ff)):
            tot[k] += int(v.sum())
        print(f"[cari] {en}: {len(exn) * R * (R + 1) // 2:,} kombinasi; lolos W {int(w.sum()):,}, W+P {int(p.sum()):,}, "
              f"W+P+T {int(t.sum()):,}, dan untung di F {int(ff.sum()):,} (F n={int(masks['F'].sum())}) ({time.time() - lc.T0:.0f}s)",
              flush=True)
        idx = np.argwhere(t)
        if len(idx):
            sc = np.minimum(MP[t], MT[t])
            for k in np.argsort(-sc)[:10]:
                e, i, j = idx[k]
                finals.append((en, e, i, j, labs[i], labs[j], float(sc[k]), M, d, masks))
        for q in range(a.null):
            rng = np.random.default_rng(1000 * a.set + q)
            wn, pn, tn, fn, _, _ = cnt(lc.grid(M, Yc, masks, shuffle=rng))
            for k, v in (("w", wn), ("p", pn), ("t", tn), ("f", fn)):
                nul[q][k] += int(v.sum())
    print(f"\n## RINGKASAN set {a.set}: {tot['combo']:,} kombinasi. Lolos W {tot['w']:,}; W+P {tot['p']:,}; W+P+T {tot['t']:,}; "
          f"W+P+T dan untung di data maju F {tot['f']:,}", flush=True)
    print(f"## KONTROL ACAK: {nul}", flush=True)
    print("\n## FINALIS -> hasil ASLI di data maju F", flush=True)
    npass = 0
    for en, e, i, j, li, lj, sc, M, d, masks in finals:
        mk = (M[i] > 0) & (M[j] > 0) & masks["F"] & ~np.isnan(d["Y"][:, e])
        y = d["Y"][mk, e]
        ok = len(y) >= 30 and y.mean() > 1 and (y.sum() - y.max()) / (len(y) - 1) > 1
        npass += ok
        rule = li if i == j else f"{li} & {lj}"
        print(f"  {en} | {exn[e]} | {rule} | min(P,T) {sc:.3f}x -> F {lc.stat(y)}{'  <== LULUS' if ok else ''}", flush=True)
    print(f"## Finalis lulus di F: {npass} dari {len(finals)}", flush=True)
    print(f"[selesai] {time.time() - lc.T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

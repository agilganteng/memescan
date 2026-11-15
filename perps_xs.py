#!/usr/bin/env python3
"""perps_xs: strategi netral pasar (long satu kelompok koin, short kelompok lain) di Binance USDT-M futures.

Data: cache perps_baru (pcache/data.json.gz): candle harian + funding 896 simbol, 2023-sekarang.
Semesta tiap rebalance: 100 koin dengan volume 30 hari terbesar (punya histori cukup), tanpa stablecoin/indeks.
Sinyal dihitung di close hari t, posisi dipegang H hari, lalu dihitung ulang.
  MOM   long koin paling naik L hari terakhir, short paling turun   (REV = kebalikannya)
  FUND  short koin funding tertinggi, long funding terendah          (FUNDX = kebalikannya)
  VOL   long volatilitas rendah, short volatilitas tinggi            (VOLX = kebalikannya)
  ALT   short semua 100 koin rata + long BTC
Eksposur kotor 1x (0,5 long + 0,5 short). Biaya 0,1% x perputaran posisi + funding nyata. Tanpa leverage.
A = 2023-2024 (pilih, urut Sharpe), B = 2025-sekarang (uji). Lulus: B rata-rata per periode > 0 dengan t >= 2,
n periode >= 30, dan lebih baik dari kontrol acak (kelompok long/short diacak, 20 seed).
Simulasi saldo: hasil majemuk, posisi < $5 dianggap tidak bisa dibuka (saldo kecil).
"""
import argparse
import gzip
import json
import math
import os
import random
import time

import numpy as np

FEE = 0.001
DAY = 86400
T_SPLIT = 1735689600  # 2025-01-01 UTC
SKIP = {"USDCUSDT", "FDUSDUSDT", "BTCDOMUSDT", "DEFIUSDT", "TUSDUSDT", "BUSDUSDT", "USDPUSDT", "BTCSTUSDT"}
NUNI = 100


def load():
    with gzip.open(os.path.join("pcache", "data.json.gz"), "rt") as f:
        data = json.load(f)
    data = [d for d in data if d["sym"] not in SKIP]
    days = sorted({int(x[0]) for d in data for x in d["k"]})
    ix = {t: i for i, t in enumerate(days)}
    T, N = len(days), len(data)
    C = np.full((T, N), np.nan)
    F = np.zeros((T, N))
    V = np.full((T, N), np.nan)
    for j, d in enumerate(data):
        for x, fu in zip(d["k"], d["f"]):
            i = ix[int(x[0])]
            if x[4] > 0:
                C[i, j], F[i, j], V[i, j] = x[4], fu, x[5]
    return np.array(days), [d["sym"] for d in data], C, F, V


def run(days, C, F, V, sig_fn, H, q, rnd=None, alt_btc=None):
    """Return list (t, ret_periode, n_posisi)."""
    T, N = C.shape
    out, w_old = [], np.zeros(N)
    t = 95
    R = np.full((T, N), np.nan)
    R[1:] = C[1:] / C[:-1] - 1
    while t + H < T:
        vol30 = np.nanmedian(V[t - 29:t + 1], axis=0)
        ok = ~np.isnan(C[t]) & ~np.isnan(C[t - 90]) & ~np.isnan(vol30)
        idx = np.where(ok)[0]
        if len(idx) < 40:
            t += H
            continue
        idx = idx[np.argsort(-vol30[idx])][:NUNI]
        w = np.zeros(N)
        if alt_btc is not None:
            sh = [j for j in idx if j != alt_btc]
            w[sh] = -0.5 / len(sh)
            w[alt_btc] = 0.5
        else:
            s = sig_fn(t, idx, R, F)
            good = ~np.isnan(s)
            idx, s = idx[good], s[good]
            if rnd is not None:
                s = np.array([rnd.random() for _ in s])
            k = max(3, int(len(idx) * q))
            order = np.argsort(s)
            w[idx[order[-k:]]] = 0.5 / k
            w[idx[order[:k]]] = -0.5 / k
        # hasil per posisi: beli-tahan H hari, koin yang hilang pakai close terakhir
        seg = C[t:t + H + 1]
        last = seg[0].copy()
        for row in seg[1:]:
            m = ~np.isnan(row)
            last[m] = row[m]
        pr = last / C[t] - 1
        fs = np.nansum(np.where(np.isnan(C[t + 1:t + H + 1]), 0.0, F[t + 1:t + H + 1]), axis=0)
        held = w != 0
        ret = float(np.sum(w[held] * (pr[held] - fs[held])))
        cost = float(np.sum(np.abs(w - w_old))) * FEE
        out.append((int(days[t]), ret - cost, int(held.sum())))
        # bobot lama setelah bergerak (kira-kira)
        w_old = w
        t += H
    return out


def summarize(rows, H):
    if not rows:
        return {"n": 0}
    x = np.array([r[1] for r in rows])
    n = len(x)
    mu, sd = x.mean(), x.std(ddof=1) if n > 1 else 0.0
    eq = np.cumprod(1 + x)
    mdd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    npos = int(np.median([r[2] for r in rows]))
    sims = {}
    for S in (100, 200, 500, 1000, 5000):
        sims[f"${S}"] = round(S * float(eq[-1]), 2) if S / npos >= 5 else "posisi < $5"
    return {"n": n, "rata_per_periode": round(float(mu), 5), "t": round(float(mu / sd * math.sqrt(n)), 2) if sd else 0,
            "sharpe_tahunan": round(float(mu / sd * math.sqrt(365 / H)), 2) if sd else 0,
            "menang": round(float((x > 0).mean()), 3), "total": round(float(eq[-1]), 3), "mdd": round(mdd, 3),
            "terburuk": round(float(x.min()), 3), "posisi": npos, "sim": sims}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    T0 = time.time()
    days, syms, C, F, V = load()
    print(f"[data] {len(syms)} simbol, {len(days)} hari ({time.time() - T0:.0f}s)", flush=True)

    def mom(L):
        return lambda t, idx, R, F_: C[t, idx] / C[t - L, idx] - 1

    def fund(L):
        return lambda t, idx, R, F_: -np.sum(F_[t - L + 1:t + 1, idx], axis=0)   # tinggi = funding rendah (long)

    def lowvol(L):
        return lambda t, idx, R, F_: -np.nanstd(R[t - L + 1:t + 1, idx], axis=0)

    neg = lambda fn: (lambda t, idx, R, F_: -fn(t, idx, R, F_))  # noqa: E731
    cfgs = []
    for L in (1, 3):
        for q in (0.1, 0.2):
            cfgs.append((f"MOM L{L} H1 q{q}", mom(L), 1, q))
            cfgs.append((f"REV L{L} H1 q{q}", neg(mom(L)), 1, q))
    for L in (7, 14, 30, 60):
        for H in (7, 14):
            for q in (0.1, 0.2):
                cfgs.append((f"MOM L{L} H{H} q{q}", mom(L), H, q))
                cfgs.append((f"REV L{L} H{H} q{q}", neg(mom(L)), H, q))
    for L in (3, 7):
        for H in (1, 3, 7):
            for q in (0.1, 0.2):
                cfgs.append((f"FUND L{L} H{H} q{q}", fund(L), H, q))
                cfgs.append((f"FUNDX L{L} H{H} q{q}", neg(fund(L)), H, q))
    for H in (7, 14):
        for q in (0.1, 0.2):
            cfgs.append((f"VOL L30 H{H} q{q}", lowvol(30), H, q))
            cfgs.append((f"VOLX L30 H{H} q{q}", neg(lowvol(30)), H, q))
    res = []
    for nm, fn, H, q in cfgs:
        rows = run(days, C, F, V, fn, H, q)
        A = summarize([r for r in rows if r[0] < T_SPLIT], H)
        B = summarize([r for r in rows if r[0] >= T_SPLIT], H)
        res.append({"nama": nm, "H": H, "q": q, "A": A, "B": B})
    btc = syms.index("BTCUSDT")
    for H in (7, 30):
        rows = run(days, C, F, V, None, H, 0, alt_btc=btc)
        res.append({"nama": f"ALT short100+longBTC H{H}", "H": H, "q": 0,
                    "A": summarize([r for r in rows if r[0] < T_SPLIT], H),
                    "B": summarize([r for r in rows if r[0] >= T_SPLIT], H)})
    res.sort(key=lambda r: -r["A"].get("sharpe_tahunan", -9))
    print(f"[xs] {len(res)} strategi ({time.time() - T0:.0f}s). Urut Sharpe A:", flush=True)
    for r in res:
        print(f"  {r['nama']}: A {r['A']} | B {r['B']}", flush=True)
    okA = [r for r in res if r["A"].get("n", 0) >= 30 and r["A"].get("t", 0) >= 2]
    okAB = [r for r in okA if r["B"].get("n", 0) >= 30 and r["B"].get("t", 0) >= 2]
    print(f"[xs] t>=2 di A: {len(okA)}/{len(res)}; t>=2 di A dan B: {len(okAB)}: {[r['nama'] for r in okAB]}",
          flush=True)
    # null: kelompok diacak, untuk H dan q dari 5 teratas A
    nulls = {}
    for r in res[:5]:
        if r["q"] == 0:
            continue
        ts_ = []
        for seed in range(20):
            rows = run(days, C, F, V, mom(7), r["H"], r["q"], rnd=random.Random(seed))
            ts_.append(summarize([x for x in rows if x[0] >= T_SPLIT], r["H"]).get("t", 0))
        nulls[r["nama"]] = {"t_B_asli": r["B"].get("t"), "null_t_maks": max(ts_), "null_t_rata": round(sum(ts_) / 20, 2)}
        print(f"[null] {r['nama']}: {nulls[r['nama']]}", flush=True)
    with open(os.path.join(a.out, "perps_xs.json"), "w") as f:
        json.dump({"hasil": res, "lolos_A": len(okA), "lolos_AB": [r["nama"] for r in okAB], "null": nulls}, f, indent=1)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

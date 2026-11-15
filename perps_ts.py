#!/usr/bin/env python3
"""perps_ts: strategi IKUT TREN per koin (time-series) di Binance USDT-M futures, harian.

Beda dengan perps_xs (lintas koin, netral pasar): di sini tiap koin dinilai sendiri, naik -> long, turun -> short/flat.
Data: cache perps_baru (pcache/data.json.gz), 2023-sekarang. Semesta tiap hari: N koin volume 30 hari terbesar.
Sinyal dihitung di close hari t, dipegang hari t+1.
  TS L    long kalau harga > harga L hari lalu, selain itu short (LS) atau tidak pegang (LF)
  MA a/b  long kalau rata-rata a hari > rata-rata b hari
  DON L   long saat close tembus tertinggi L hari, keluar saat tembus terendah L/2 hari (LS: kebalikannya untuk short)
  BH      pembanding: beli-tahan semua koin semesta rata (tanpa sinyal)
Bobot 1/N per koin (eksposur kotor maksimal 1x, tanpa leverage). Biaya 0,1% x perputaran + funding nyata.
A = 2023-2024 (pilih, urut Sharpe), B = 2025-sekarang (uji). Lulus: t >= 2 di A dan B DAN Sharpe B > Sharpe beli-tahan B.
Kontrol acak: sinyal tiap koin digeser waktunya secara acak (20 seed) -> sebaran t di B.
"""
import argparse
import json
import math
import os
import time

import warnings

import numpy as np

warnings.filterwarnings("ignore")

from perps_xs import load, T_SPLIT

FEE = 0.001


def universe(C, V, N, hist):
    T, M = C.shape
    U = np.zeros((T, M), bool)
    for t in range(hist, T):
        vol30 = np.nanmedian(V[t - 29:t + 1], axis=0)
        ok = ~np.isnan(C[t]) & ~np.isnan(C[t - hist]) & ~np.isnan(vol30)
        idx = np.where(ok)[0]
        if len(idx) < 10:
            continue
        U[t, idx[np.argsort(-vol30[idx])][:N]] = True
    return U


def sig_ts(C, L, short):
    S = np.zeros(C.shape)
    r = C[L:] / C[:-L] - 1
    S[L:] = np.where(r > 0, 1.0, -1.0 if short else 0.0)
    S[np.isnan(C)] = 0
    S[L:][np.isnan(r)] = 0
    return S


def sma(C, n):
    X = np.where(np.isnan(C), 0.0, C)
    cs = np.cumsum(X, axis=0)
    out = np.full(C.shape, np.nan)
    out[n - 1:] = (cs[n - 1:] - np.vstack([np.zeros((1, C.shape[1])), cs[:-n]])) / n
    bad = np.cumsum(np.isnan(C), axis=0)
    nb = bad.copy()
    nb[n:] = bad[n:] - bad[:-n]
    out[nb > 0] = np.nan
    return out


def sig_ma(C, a, b, short):
    A, B = sma(C, a), sma(C, b)
    S = np.where(A > B, 1.0, -1.0 if short else 0.0)
    S[np.isnan(A) | np.isnan(B)] = 0
    return S


def sig_don(C, L, short):
    T, M = C.shape
    S = np.zeros((T, M))
    st = np.zeros(M)
    X = L // 2
    for t in range(L, T):
        c = C[t]
        hi, lo = np.nanmax(C[t - L:t], axis=0), np.nanmin(C[t - L:t], axis=0)
        xhi, xlo = np.nanmax(C[t - X:t], axis=0), np.nanmin(C[t - X:t], axis=0)
        ok = ~np.isnan(c) & ~np.isnan(C[t - L])
        st = np.where((st == 1) & (c <= xlo), 0, st)
        st = np.where((st == -1) & (c >= xhi), 0, st)
        st = np.where(ok & (c >= hi), 1, st)
        if short:
            st = np.where(ok & (c <= lo), -1, st)
        st = np.where(ok, st, 0)
        S[t] = st
    return S


def run(days, C, F, U, S, N):
    """Hasil harian portofolio: list (t_hari, ret)."""
    T, M = C.shape
    R = np.zeros((T, M))
    R[1:] = C[1:] / C[:-1] - 1
    R[np.isnan(R)] = 0
    W = S * U / N
    out = []
    w_old = np.zeros(M)
    for t in range(201, T):
        w = W[t - 1]
        cost = FEE * float(np.sum(np.abs(w - w_old)))
        out.append((int(days[t]), float(np.sum(w * (R[t] - F[t]))) - cost, int(np.count_nonzero(w))))
        w_old = w
    return out


def summ(rows):
    if len(rows) < 30:
        return {"n": len(rows)}
    x = np.array([r[1] for r in rows])
    n = len(x)
    mu, sd = x.mean(), x.std(ddof=1)
    eq = np.cumprod(1 + x)
    mdd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    # t dengan koreksi autokorelasi sederhana (blok 7 hari)
    k = n // 7
    wk = np.array([np.prod(1 + x[i * 7:(i + 1) * 7]) - 1 for i in range(k)])
    t = float(wk.mean() / wk.std(ddof=1) * math.sqrt(k)) if k > 2 and wk.std(ddof=1) > 0 else 0.0
    npos = int(np.median([r[2] for r in rows]))
    return {"n": n, "total": round(float(eq[-1]), 3), "per_bulan": round(float(eq[-1] ** (30.4 / n) - 1), 4),
            "sharpe": round(float(mu / sd * math.sqrt(365)), 2) if sd else 0, "t": round(t, 2),
            "minggu_untung": round(float((wk > 0).mean()), 3) if k else None, "mdd": round(mdd, 3),
            "minggu_terburuk": round(float(wk.min()), 3) if k else None, "posisi": npos,
            "$200": round(200 * float(eq[-1]), 2) if npos == 0 or 200 / max(npos, 1) >= 5 else "posisi < $5"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    T0 = time.time()
    days, syms, C, F, V = load()
    print(f"[data] {len(syms)} simbol, {len(days)} hari ({time.time() - T0:.0f}s)", flush=True)
    res = []
    sigs = {}
    for short in (False, True):
        m = "LS" if short else "LF"
        for L in (10, 20, 30, 60, 120):
            sigs[f"TS L{L} {m}"] = sig_ts(C, L, short)
        for a_, b_ in ((10, 50), (20, 100), (50, 200)):
            sigs[f"MA {a_}/{b_} {m}"] = sig_ma(C, a_, b_, short)
        for L in (20, 55, 100):
            sigs[f"DON L{L} {m}"] = sig_don(C, L, short)
    print(f"[sinyal] {len(sigs)} sinyal ({time.time() - T0:.0f}s)", flush=True)
    bh = {}
    for N in (10, 20, 30):
        U = universe(C, V, N, 200)
        rows = run(days, C, F, U, np.where(np.isnan(C), 0.0, 1.0), N)
        bh[N] = {"A": summ([r for r in rows if r[0] < T_SPLIT]), "B": summ([r for r in rows if r[0] >= T_SPLIT])}
        print(f"[BH] beli-tahan top{N}: A {bh[N]['A']} | B {bh[N]['B']}", flush=True)
        for nm, S in sigs.items():
            rows = run(days, C, F, U, S, N)
            res.append({"nama": f"{nm} top{N}", "sig": nm, "N": N, "A": summ([r for r in rows if r[0] < T_SPLIT]),
                        "B": summ([r for r in rows if r[0] >= T_SPLIT])})
    # BTC saja dan BTC+ETH
    for label, names in (("BTC", ["BTCUSDT"]), ("BTC+ETH", ["BTCUSDT", "ETHUSDT"]),
                         ("BTC+ETH+SOL", ["BTCUSDT", "ETHUSDT", "SOLUSDT"])):
        U = np.zeros(C.shape, bool)
        for s in names:
            U[200:, syms.index(s)] = True
        rows = run(days, C, F, U, np.where(np.isnan(C), 0.0, 1.0), len(names))
        bh[label] = {"A": summ([r for r in rows if r[0] < T_SPLIT]), "B": summ([r for r in rows if r[0] >= T_SPLIT])}
        print(f"[BH] beli-tahan {label}: A {bh[label]['A']} | B {bh[label]['B']}", flush=True)
        for nm, S in sigs.items():
            rows = run(days, C, F, U, S, len(names))
            res.append({"nama": f"{nm} {label}", "sig": nm, "N": label, "A": summ([r for r in rows if r[0] < T_SPLIT]),
                        "B": summ([r for r in rows if r[0] >= T_SPLIT])})
    res.sort(key=lambda r: -r["A"].get("sharpe", -9))
    print(f"[ts] {len(res)} strategi ({time.time() - T0:.0f}s). Urut Sharpe A:", flush=True)
    for r in res:
        print(f"  {r['nama']}: A {r['A']} | B {r['B']}", flush=True)
    okA = [r for r in res if r["A"].get("t", 0) >= 2]
    okAB = [r for r in okA if r["B"].get("t", 0) >= 2 and r["B"].get("sharpe", 0) > bh[r["N"]]["B"].get("sharpe", 0)]
    posB = [r for r in res if r["B"].get("total", 0) > 1]
    print(f"[ts] t>=2 di A: {len(okA)}/{len(res)}; lulus A dan B (dan kalahkan beli-tahan): {len(okAB)}: "
          f"{[r['nama'] for r in okAB]}; untung di B: {len(posB)}/{len(res)}", flush=True)
    top = res[:10]
    print("[ts] 10 teratas A -> B:", flush=True)
    for r in top:
        print(f"  {r['nama']}: A total {r['A'].get('total')} sharpe {r['A'].get('sharpe')} | B total "
              f"{r['B'].get('total')} sharpe {r['B'].get('sharpe')} t {r['B'].get('t')} mdd {r['B'].get('mdd')} "
              f"$200 {r['B'].get('$200')} (beli-tahan B sharpe {bh[r['N']]['B'].get('sharpe')})", flush=True)
    # null: geser sinyal tiap koin secara acak dalam waktu
    nulls = {}
    rng = np.random.default_rng(0)
    for r in top[:3]:
        if not isinstance(r["N"], int):
            continue
        U = universe(C, V, r["N"], 200)
        S = sigs[r["sig"]]
        ts_ = []
        for _ in range(20):
            S2 = np.empty_like(S)
            for j in range(S.shape[1]):
                S2[:, j] = np.roll(S[:, j], int(rng.integers(30, S.shape[0] - 30)))
            rows = run(days, C, F, U, S2, r["N"])
            ts_.append(summ([x for x in rows if x[0] >= T_SPLIT]).get("t", 0))
        nulls[r["nama"]] = {"t_B_asli": r["B"].get("t"), "null_t_maks": max(ts_), "null_t_rata": round(sum(ts_) / 20, 2)}
        print(f"[null] {r['nama']}: {nulls[r['nama']]}", flush=True)
    with open(os.path.join(a.out, "perps_ts.json"), "w") as f:
        json.dump({"hasil": res, "beli_tahan": {str(k): v for k, v in bh.items()}, "lulus": [r["nama"] for r in okAB],
                   "null": nulls}, f, indent=1)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

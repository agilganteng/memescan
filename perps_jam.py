#!/usr/bin/env python3
"""perps_jam: strategi DALAM HARI (candle 1 jam) di Binance USDT-M futures. Semua uji sebelumnya pakai data harian.

Data: candle 1 jam dari data.binance.vision untuk gabungan koin yang pernah masuk 30 besar volume (semesta harian
kemarin, jadi tanpa info masa depan), 2023-sekarang. Disimpan di hcache/h1.npz.
Posisi ditetapkan di tutup jam t, dipegang jam t+1. Biaya 0,1% x perputaran + funding (funding harian nyata / 24).
  TS    ikut tren per koin: harga > harga L jam lalu -> long, selain itu short (LS) atau kosong (LF)
  XMOM  lintas koin: long 20% teratas return L jam, short 20% terbawah, dipegang H jam (netral pasar)
  XREV  kebalikannya (pembalikan jangka pendek)
  SHOCK gerak 1 jam > k sigma (sigma 168 jam): ikut (CONT) atau lawan (REV), pegang H jam
  JAM   long/short semesta hanya pada blok 4 jam tertentu (UTC)
  AKHIR long/short semesta hanya Sabtu-Minggu
A = 2023-2024, B = 2025-sekarang. Lulus: t mingguan >= 2 di A DAN di B, total B > 1.
"""
import argparse
import concurrent.futures as cf
import json
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

from perps_baru import BV, get, rows_zip, months, ts
from perps_xs import load, T_SPLIT
from perps_ts import universe, summ

FEE = float(os.environ.get("FEE", "0.001"))
H = 3600
T0H = 1672531200  # 2023-01-01 UTC


def fetch_sym(sym, now, nh):
    jobs = [f"{BV}/monthly/klines/{sym}/1h/{sym}-1h-{mo}.zip" for mo in months(now)]
    g = time.gmtime(now)
    jobs += [f"{BV}/daily/klines/{sym}/1h/{sym}-1h-{g.tm_year}-{g.tm_mon:02d}-{d:02d}.zip" for d in range(1, g.tm_mday)]
    c = np.full(nh, np.nan, dtype=np.float32)
    for u in jobs:
        for r in rows_zip(get(u)):
            i = (ts(r[0]) - T0H) // H
            if 0 <= i < nh:
                c[i] = float(r[4])
    return c


def run(W, R, Fh):
    """W[t] dipegang selama jam t+1. Hasil per jam (panjang T-1)."""
    turn = np.abs(np.diff(W, axis=0, prepend=np.zeros((1, W.shape[1])))).sum(axis=1)
    return (W[:-1] * (R[1:] - Fh[1:])).sum(axis=1) - FEE * turn[:-1]


def harian(x, W, th):
    """Gabung hasil per jam jadi baris harian (t_hari, ret, posisi) untuk summ()."""
    d = th[1:] // 86400
    npos = np.count_nonzero(W[:-1], axis=1)
    out = []
    u, st = np.unique(d, return_index=True)
    st = list(st) + [len(d)]
    for k, dd in enumerate(u):
        s = slice(st[k], st[k + 1])
        if st[k + 1] - st[k] < 24:
            continue
        out.append((int(dd) * 86400, float(np.prod(1 + x[s]) - 1), int(np.median(npos[s]))))
    return out


def weights(S, U):
    X = S * U
    n = np.maximum(np.count_nonzero(X, axis=1), 5)[:, None]
    return X / n


def hold(E, n):
    S = np.zeros(E.shape, dtype=np.float32)
    for h in range(n - 1, -1, -1):
        Eh = np.zeros(E.shape, dtype=np.float32)
        if h:
            Eh[h:] = E[:-h]
        else:
            Eh = E
        S = np.where(Eh != 0, Eh, S)
    return S


def w_xs(C, U, L, hd, q=0.2):
    T, M = C.shape
    r = np.full((T, M), np.nan, dtype=np.float32)
    r[L:] = C[L:] / C[:-L] - 1
    r[~U] = np.nan
    n = (~np.isnan(r)).sum(axis=1)
    rk = np.argsort(np.argsort(np.where(np.isnan(r), np.inf, r), axis=1), axis=1)
    k = np.maximum((q * n).astype(int), 1)[:, None]
    ok = (n >= 10)[:, None] & ~np.isnan(r)
    lo = ok & (rk < k)
    hi = ok & (rk >= n[:, None] - k)
    W = (hi * 0.5 / k - lo * 0.5 / k).astype(np.float32)
    if hd > 1:
        acc = W.copy()
        for h in range(1, hd):
            acc[h:] += W[:-h]
        W = acc / hd
    return W


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    T0 = time.time()
    days, syms, Cd, Fd, Vd = load()
    Ud = universe(Cd, Vd, 30, 30)
    sel = np.where(Ud.any(axis=0))[0]
    names = [syms[j] for j in sel]
    now = time.time()
    nh = int((now - T0H) // H)
    cache = os.path.join("hcache", "h1.npz")
    if os.path.exists(cache):
        z = np.load(cache, allow_pickle=True)
        if list(z["names"]) == names:
            C = z["C"]
            print(f"[cache] {C.shape} dari cache", flush=True)
        else:
            C = None
    else:
        C = None
    if C is None:
        C = np.full((nh, len(names)), np.nan, dtype=np.float32)
        with cf.ThreadPoolExecutor(24) as ex:
            for j, c in enumerate(ex.map(lambda s: fetch_sym(s, now, nh), names)):
                C[:, j] = c
                if j % 25 == 0:
                    print(f"  {j}/{len(names)} simbol ({time.time() - T0:.0f}s)", flush=True)
        os.makedirs("hcache", exist_ok=True)
        np.savez_compressed(cache, C=C, names=np.array(names, dtype=object))
    T, M = C.shape
    th = T0H + H * np.arange(T)
    print(f"[data] {M} simbol, {T} jam, terisi {np.mean(~np.isnan(C)):.2f} ({time.time() - T0:.0f}s)", flush=True)
    # semesta & funding per jam dari data harian HARI SEBELUMNYA / hari yang sama
    dix = {int(d): i for i, d in enumerate(days)}
    di = np.array([dix.get(int(t - t % 86400), -1) for t in th])
    R = np.zeros((T, M), dtype=np.float32)
    R[1:] = C[1:] / C[:-1] - 1
    R[np.isnan(R)] = 0
    R = np.clip(R, -0.9, 3.0)
    Fh = np.zeros((T, M), dtype=np.float32)
    okd = di >= 0
    Fh[okd] = Fd[di[okd]][:, sel] / 24
    unis = {}
    for N in (10, 30):
        UdN = universe(Cd, Vd, N, 30)[:, sel]
        U = np.zeros((T, M), bool)
        pv = di - 1
        ok = (di >= 1)
        U[ok] = UdN[pv[ok]]
        U &= ~np.isnan(C)
        unis[N] = U
        print(f"[semesta] top{N}: median {int(np.median(U.sum(axis=1)))} koin per jam", flush=True)
    hod = (th // H) % 24
    dow = ((th // 86400) + 3) % 7  # 0 = Senin
    nxt_h, nxt_d = np.roll(hod, -1), np.roll(dow, -1)
    sig = {}
    for L in (6, 24, 72, 168):
        r = np.full((T, M), np.nan, dtype=np.float32)
        r[L:] = C[L:] / C[:-L] - 1
        sig[f"TS L{L} LS"] = np.where(np.isnan(r), 0, np.where(r > 0, 1.0, -1.0)).astype(np.float32)
        sig[f"TS L{L} LF"] = np.where(np.isnan(r), 0, np.where(r > 0, 1.0, 0.0)).astype(np.float32)
    R2 = np.cumsum(R.astype(np.float64) ** 2, axis=0)
    sd = np.full((T, M), np.nan)
    sd[169:] = np.sqrt((R2[168:-1] - R2[:-169]) / 168)
    zz = R / sd
    for k in (3, 4):
        E = np.where(np.abs(zz) > k, np.sign(R), 0).astype(np.float32)
        E[np.isnan(zz)] = 0
        for hd in (1, 4, 24):
            sig[f"SHOCK k{k} CONT H{hd}"] = hold(E, hd)
            sig[f"SHOCK k{k} REV H{hd}"] = hold(-E, hd)
    for b in range(6):
        m = (nxt_h // 4 == b).astype(np.float32)[:, None] * np.ones((1, M), dtype=np.float32)
        sig[f"JAM {b * 4:02d}-{b * 4 + 4:02d} LONG"] = m
        sig[f"JAM {b * 4:02d}-{b * 4 + 4:02d} SHORT"] = -m
    m = (nxt_d >= 5).astype(np.float32)[:, None] * np.ones((1, M), dtype=np.float32)
    sig["AKHIR pekan LONG"], sig["AKHIR pekan SHORT"] = m, -m
    print(f"[sinyal] {len(sig)} sinyal ({time.time() - T0:.0f}s)", flush=True)
    res = []

    def catat(nama, kel, W):
        rows = harian(run(W, R, Fh), W, th)
        A = summ([r for r in rows if r[0] < T_SPLIT])
        B = summ([r for r in rows if r[0] >= T_SPLIT])
        res.append({"nama": nama, "kel": kel, "A": A, "B": B})

    for N, U in unis.items():
        for nm, S in sig.items():
            catat(f"{nm} top{N}", nm.split()[0], weights(S, U))
        if N == 30:
            for L in (1, 4, 24, 72):
                for hd in (1, 4, 24):
                    W = w_xs(C, U, L, hd)
                    catat(f"XMOM L{L} H{hd} top{N}", "XMOM", W)
                    catat(f"XREV L{L} H{hd} top{N}", "XREV", -W)
        print(f"[uji] top{N} selesai ({time.time() - T0:.0f}s)", flush=True)
    res.sort(key=lambda r: -r["A"].get("sharpe", -9))
    print(f"[jam] {len(res)} strategi. Urut Sharpe A:", flush=True)
    for r in res:
        print(f"  {r['nama']}: A {r['A']} | B {r['B']}", flush=True)

    def lulus(r):
        return r["A"].get("t", 0) >= 2 and r["B"].get("t", 0) >= 2 and r["B"].get("total", 0) > 1

    ok = [r for r in res if lulus(r)]
    posAB = [r for r in res if r["A"].get("total", 0) > 1 and r["B"].get("total", 0) > 1]
    for kel in sorted({r["kel"] for r in res}):
        rr = [r for r in res if r["kel"] == kel]
        print(f"[kel] {kel}: {len(rr)} strategi, t>=2 di A {sum(r['A'].get('t', 0) >= 2 for r in rr)}, untung A dan B "
              f"{sum(r in posAB for r in rr)}, lulus {sum(r in ok for r in rr)}, median total A "
              f"{np.median([r['A'].get('total', 1) for r in rr]):.3f}, B {np.median([r['B'].get('total', 1) for r in rr]):.3f}",
              flush=True)
    print(f"[jam] untung A dan B: {len(posAB)}/{len(res)}; LULUS: {len(ok)}: {[r['nama'] for r in ok]}", flush=True)
    print("[jam] 12 teratas A -> B:", flush=True)
    for r in res[:12]:
        print(f"  {r['nama']}: A total {r['A'].get('total')} t {r['A'].get('t')} mdd {r['A'].get('mdd')} | B total "
              f"{r['B'].get('total')} t {r['B'].get('t')} mdd {r['B'].get('mdd')} per_bulan {r['B'].get('per_bulan')} "
              f"$200 {r['B'].get('$200')}", flush=True)
    with open(os.path.join(a.out, "perps_jam.json"), "w") as f:
        json.dump({"hasil": res, "lulus": [r["nama"] for r in ok]}, f, indent=1)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

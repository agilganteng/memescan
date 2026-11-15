#!/usr/bin/env python3
"""perps_sisa: keluarga strategi Binance futures harian yang BELUM pernah diuji (sisa daftar).

Data: cache perps_baru (pcache/data.json.gz), 2023-sekarang. Sinyal di close hari t, dipegang mulai hari t+1.
  PAIR  stat-arb pasangan: tiap 30 hari pilih pasangan dari top-20 volume dengan korelasi 90 hari >= thr; masuk saat
        z-score selisih log harga (jendela L) lewat +-zin melawan arah, keluar saat z balik ke 0, stop di zin+2.
  DOW   musiman hari: long/short semesta hanya pada satu hari dalam seminggu.
  SHOCK gerak 1 hari > k sigma (sigma 30 hari sebelumnya): ikut (CONT) atau lawan (REV), pegang H hari.
  VOL   volume > m x median 30 hari + arah harga hari itu: ikut atau lawan, pegang H hari.
  FUND  funding harian ekstrem: > x -> short (terima funding), < -x -> long, pegang H hari.
  FUNDH sama, setengah modal, posisi bersih dilawan dengan BTC (netral arah pasar).
Bobot: rata di posisi aktif, paling besar 1/5 per koin (eksposur kotor <= 1x). Biaya 0,1% x perputaran + funding nyata.
A = 2023-2024, B = 2025-sekarang. Lulus: t mingguan >= 2 di A DAN di B, total B > 1.
Kontrol: jumlah lulus dibanding jumlah lulus kalau sinyal tiap koin digeser waktunya secara acak.
"""
import argparse
import json
import os
import time
import warnings

import numpy as np

warnings.filterwarnings("ignore")

from perps_xs import load, T_SPLIT
from perps_ts import universe, summ

FEE = 0.001
START = 201


def run_w(days, C, F, W):
    T, M = C.shape
    R = np.zeros((T, M))
    R[1:] = C[1:] / C[:-1] - 1
    R[np.isnan(R)] = 0
    out, w_old = [], np.zeros(M)
    for t in range(START, T):
        w = W[t - 1]
        cost = FEE * float(np.sum(np.abs(w - w_old)))
        out.append((int(days[t]), float(np.sum(w * (R[t] - F[t]))) - cost, int(np.count_nonzero(w))))
        w_old = w
    return out


def weights(S, U):
    """Sinyal +-1 -> bobot rata di posisi aktif, maksimal 1/5 per koin."""
    X = S * U
    n = np.maximum(np.count_nonzero(X, axis=1), 5)[:, None]
    return X / n


def hold(E, H):
    """Kejadian +-1 di hari t dipegang H hari (kejadian terbaru menang)."""
    S = np.zeros(E.shape)
    for h in range(H - 1, -1, -1):
        Eh = np.zeros(E.shape)
        if h:
            Eh[h:] = E[:-h]
        else:
            Eh = E
        S = np.where(Eh != 0, Eh, S)
    return S


def rets(C):
    R = np.full(C.shape, np.nan)
    R[1:] = C[1:] / C[:-1] - 1
    return R


def ev_shock(C, k):
    R = rets(C)
    T = C.shape[0]
    E = np.zeros(C.shape)
    for t in range(31, T):
        sd = np.nanstd(R[t - 30:t], axis=0)
        z = R[t] / sd
        E[t] = np.where(np.abs(z) > k, np.sign(R[t]), 0)
    E[np.isnan(E)] = 0
    return E


def ev_vol(C, V, m):
    R = rets(C)
    T = C.shape[0]
    E = np.zeros(C.shape)
    for t in range(31, T):
        med = np.nanmedian(V[t - 30:t], axis=0)
        E[t] = np.where(V[t] > m * med, np.sign(R[t]), 0)
    E[np.isnan(E)] = 0
    return E


def ev_fund(F, x):
    return np.where(F > x, -1.0, np.where(F < -x, 1.0, 0.0))


def w_pairs(C, V, L, zin, thr, N=20):
    T, M = C.shape
    lc = np.log(C)
    R = rets(C)
    W = np.zeros((T, M))
    npair = 0
    for t0 in range(START, T, 30):
        vol30 = np.nanmedian(V[t0 - 30:t0], axis=0)
        ok = ~np.isnan(vol30) & ~np.isnan(C[t0 - 120:t0 + 1]).any(axis=0)
        idx = np.where(ok)[0]
        if len(idx) < 5:
            continue
        idx = idx[np.argsort(-vol30[idx])][:N]
        cc = np.corrcoef(R[t0 - 90:t0, idx].T)
        end = min(t0 + 30, T)
        P = []
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if not cc[a, b] >= thr:
                    continue
                i, j = idx[a], idx[b]
                s = lc[:, i] - lc[:, j]
                pos, row = 0, np.zeros(end - t0)
                for t in range(t0, end):
                    win = s[t - L + 1:t + 1]
                    if np.isnan(win).any():
                        pos = 0
                        continue
                    sd = win.std()
                    z = (s[t] - win.mean()) / sd if sd > 0 else 0.0
                    if pos == 0:
                        if z > zin:
                            pos = -1
                        elif z < -zin:
                            pos = 1
                    elif (pos == 1 and z >= 0) or (pos == -1 and z <= 0) or abs(z) > zin + 2:
                        pos = 0
                    row[t - t0] = pos
                P.append((i, j, row))
        npair += len(P)
        if not P:
            continue
        act = np.maximum(sum(np.abs(r) for _, _, r in P), 5)
        for i, j, row in P:
            W[t0:end, i] += 0.5 * row / act
            W[t0:end, j] -= 0.5 * row / act
    return W, npair


def ab(rows):
    return summ([r for r in rows if r[0] < T_SPLIT]), summ([r for r in rows if r[0] >= T_SPLIT])


def lulus(A, B):
    return A.get("t", 0) >= 2 and B.get("t", 0) >= 2 and B.get("total", 0) > 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    T0 = time.time()
    days, syms, C, F, V = load()
    T, M = C.shape
    print(f"[data] {len(syms)} simbol, {len(days)} hari ({time.time() - T0:.0f}s)", flush=True)
    res = []
    events = {}  # nama -> (S, keluarga)
    for k in (2, 3):
        E = ev_shock(C, k)
        for H in (1, 3, 5):
            events[f"SHOCK k{k} CONT H{H}"] = hold(E, H)
            events[f"SHOCK k{k} REV H{H}"] = hold(-E, H)
    for m in (3, 5):
        E = ev_vol(C, V, m)
        for H in (1, 3, 5):
            events[f"VOL m{m} CONT H{H}"] = hold(E, H)
            events[f"VOL m{m} REV H{H}"] = hold(-E, H)
    for x in (0.001, 0.002):
        E = ev_fund(F, x)
        for H in (1, 3, 7):
            events[f"FUND x{x} H{H}"] = hold(E, H)
    wd = ((days // 86400) + 3) % 7  # 0 = Senin
    nama_hari = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]
    for d in range(7):
        for sgn, lab in ((1.0, "LONG"), (-1.0, "SHORT")):
            S = np.zeros((T, M))
            S[:-1][wd[1:] == d] = sgn  # sinyal di close t untuk dipegang hari t+1 = hari d
            events[f"DOW {nama_hari[d]} {lab}"] = S
    print(f"[sinyal] {len(events)} sinyal kejadian ({time.time() - T0:.0f}s)", flush=True)
    ib = syms.index("BTCUSDT")
    unis = {N: universe(C, V, N, 200) for N in (20, 50)}
    for N, U in unis.items():
        for nm, S in events.items():
            A, B = ab(run_w(days, C, F, weights(S, U)))
            res.append({"nama": f"{nm} top{N}", "kel": nm.split()[0], "A": A, "B": B})
            if nm.startswith("FUND"):
                # versi lindung nilai: posisi bersih ditutup dengan BTC supaya tidak ikut arah pasar
                W = weights(S, U) * 0.5
                W[:, ib] -= W.sum(axis=1)
                A, B = ab(run_w(days, C, F, W))
                res.append({"nama": f"{nm} top{N} +BTC", "kel": "FUNDH", "A": A, "B": B})
    for L in (20, 40, 60):
        for zin in (1.5, 2.0, 2.5):
            for thr in (0.7, 0.85):
                W, npair = w_pairs(C, V, L, zin, thr)
                A, B = ab(run_w(days, C, F, W))
                res.append({"nama": f"PAIR L{L} z{zin} c{thr}", "kel": "PAIR", "pasangan": npair, "A": A, "B": B})
        print(f"[pair] L{L} selesai ({time.time() - T0:.0f}s)", flush=True)
    res.sort(key=lambda r: -r["A"].get("sharpe", -9))
    print(f"[sisa] {len(res)} strategi. Urut Sharpe A:", flush=True)
    for r in res:
        print(f"  {r['nama']}: A {r['A']} | B {r['B']}", flush=True)
    ok = [r for r in res if lulus(r["A"], r["B"])]
    okA = [r for r in res if r["A"].get("t", 0) >= 2]
    posAB = [r for r in res if r["A"].get("total", 0) > 1 and r["B"].get("total", 0) > 1]
    for kel in ("PAIR", "DOW", "SHOCK", "VOL", "FUND", "FUNDH"):
        rr = [r for r in res if r["kel"] == kel]
        print(f"[kel] {kel}: {len(rr)} strategi, t>=2 di A {sum(r['A'].get('t', 0) >= 2 for r in rr)}, "
              f"untung A dan B {sum(r in posAB for r in rr)}, lulus {sum(r in ok for r in rr)}, "
              f"median total B {np.median([r['B'].get('total', 1) for r in rr]):.3f}", flush=True)
    print(f"[sisa] t>=2 di A: {len(okA)}/{len(res)}; untung A dan B: {len(posAB)}; LULUS: {len(ok)}: "
          f"{[r['nama'] for r in ok]}", flush=True)
    print("[sisa] 10 teratas A -> B:", flush=True)
    for r in res[:10]:
        print(f"  {r['nama']}: A total {r['A'].get('total')} t {r['A'].get('t')} | B total {r['B'].get('total')} "
              f"t {r['B'].get('t')} mdd {r['B'].get('mdd')} per_bulan {r['B'].get('per_bulan')} $200 {r['B'].get('$200')}",
              flush=True)
    # kontrol acak: geser sinyal kejadian tiap koin dalam waktu, hitung berapa yang "lulus"
    rng = np.random.default_rng(0)
    nul = []
    for _ in range(10):
        c = 0
        for N, U in unis.items():
            for nm, S in events.items():
                if nm.startswith("DOW"):
                    continue
                S2 = np.empty_like(S)
                for j in range(M):
                    S2[:, j] = np.roll(S[:, j], int(rng.integers(30, T - 30)))
                A, B = ab(run_w(days, C, F, weights(S2, U)))
                c += lulus(A, B)
        nul.append(c)
    asli = sum(1 for r in ok if r["kel"] in ("SHOCK", "VOL", "FUND"))
    print(f"[null] lulus asli (SHOCK/VOL/FUND) {asli}; lulus saat sinyal digeser acak, 10 kali: {nul}", flush=True)
    with open(os.path.join(a.out, "perps_sisa.json"), "w") as f:
        json.dump({"hasil": res, "lulus": [r["nama"] for r in ok], "null": nul}, f, indent=1)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

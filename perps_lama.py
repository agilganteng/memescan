#!/usr/bin/env python3
"""perps_lama: uji kandidat funding ekstrem di data LAMA 2020-2022 yang belum pernah dipakai (bersih dari pilih-pilih).

Aturan dibekukan 18 Nov 2026 dari perps_sisa.py: FUND x0.002 H7 top20 +BTC. Lima varian top20 +BTC lain ikut
dicetak sebagai pembanding, begitu juga versi tanpa lindung BTC dan beli-tahan BTC. Biaya 0,1% x perputaran +
funding nyata. Data: candle harian + funding Binance USDT-M 2020-01 sampai 2022-12 (data.binance.vision).
Lulus (ditetapkan sebelum melihat hasil): total > 1, t mingguan >= 2, rugi terdalam < 30%.
"""
import concurrent.futures as cf
import gzip
import json
import os
import time

import numpy as np

from perps_baru import BV, get, rows_zip, ts, list_symbols, DAY
from perps_xs import SKIP
from perps_ts import universe, summ
from perps_sisa import run_w, weights, hold, ev_fund

MONTHS = [f"{y}-{m:02d}" for y in (2020, 2021, 2022) for m in range(1, 13)]


def fetch(sym):
    days, fund = {}, {}
    for mo in MONTHS:
        for r in rows_zip(get(f"{BV}/monthly/klines/{sym}/1d/{sym}-1d-{mo}.zip", tries=2)):
            t = ts(r[0])
            days[t] = (t, float(r[4]), float(r[7]) if len(r) > 7 else 0.0)
        for r in rows_zip(get(f"{BV}/monthly/fundingRate/{sym}/{sym}-fundingRate-{mo}.zip", tries=2)):
            t = ts(r[0])
            fund[t - t % DAY] = fund.get(t - t % DAY, 0.0) + float(r[-1])
    if len(days) < 60:
        return None
    k = sorted(days.values())
    return {"sym": sym, "k": k, "f": [fund.get(x[0]) for x in k]}


def main():
    T0 = time.time()
    cache = os.path.join("ocache", "lama.json.gz")
    if os.path.exists(cache):
        data = json.load(gzip.open(cache, "rt"))
    else:
        syms = [s for s in list_symbols() if s not in SKIP]
        data = []
        with cf.ThreadPoolExecutor(24) as ex:
            for i, d in enumerate(ex.map(fetch, syms)):
                if d:
                    data.append(d)
                if i % 100 == 0:
                    print(f"  {i}/{len(syms)} ({time.time() - T0:.0f}s)", flush=True)
        os.makedirs("ocache", exist_ok=True)
        json.dump(data, gzip.open(cache, "wt"))
    days = sorted({x[0] for d in data for x in d["k"]})
    ix = {t: i for i, t in enumerate(days)}
    T, M = len(days), len(data)
    C = np.full((T, M), np.nan)
    V = np.full((T, M), np.nan)
    F = np.zeros((T, M))
    nf = 0
    for j, d in enumerate(data):
        for x, fu in zip(d["k"], d["f"]):
            i = ix[x[0]]
            if x[1] > 0:
                C[i, j], V[i, j] = x[1], x[2]
                if fu is not None:
                    F[i, j] = fu
                    nf += 1
    syms = [d["sym"] for d in data]
    days = np.array(days)
    print(f"[data] {M} simbol, {T} hari ({time.strftime('%Y-%m-%d', time.gmtime(days[0]))} s/d "
          f"{time.strftime('%Y-%m-%d', time.gmtime(days[-1]))}); sel funding terisi {nf}/{int((~np.isnan(C)).sum())} "
          f"({time.time() - T0:.0f}s)", flush=True)
    ib = syms.index("BTCUSDT")
    U = universe(C, V, 20, 200)
    print(f"[semesta] hari dengan semesta: {int(U.any(axis=1).sum())}; hari-koin funding > 0,2%: "
          f"{int(((F > 0.002) & U).sum())}, < -0,2%: {int(((F < -0.002) & U).sum())}; > 0,1%: {int(((F > 0.001) & U).sum())}, "
          f"< -0,1%: {int(((F < -0.001) & U).sum())}", flush=True)
    Wb = np.zeros((T, M))
    Wb[:, ib] = 1.0
    print(f"[BTC beli-tahan] {summ(run_w(days, C, F, Wb))}", flush=True)
    out = {}
    for x in (0.002, 0.001):
        for H in (7, 3, 1):
            S = hold(ev_fund(F, x), H)
            W0 = weights(S, U)
            W = W0 * 0.5
            W[:, ib] -= W.sum(axis=1)
            rows = run_w(days, C, F, W)
            tag = "  <== ATURAN BEKU" if (x, H) == (0.002, 7) else ""
            out[f"FUND x{x} H{H} top20 +BTC"] = summ(rows)
            print(f"FUND x{x} H{H} top20 +BTC: {summ(rows)}{tag}", flush=True)
            for y in (2020, 2021, 2022):
                a, b = time.mktime((y, 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone, time.mktime((y + 1, 1, 1, 0, 0, 0, 0, 0, 0)) - time.timezone
                s = summ([r for r in rows if a <= r[0] < b])
                print(f"    {y}: total {s.get('total')} t {s.get('t')} mdd {s.get('mdd')} n {s.get('n')}", flush=True)
            print(f"    tanpa lindung BTC: {summ(run_w(days, C, F, W0))}", flush=True)
    r = out["FUND x0.002 H7 top20 +BTC"]
    ok = r.get("total", 0) > 1 and r.get("t", 0) >= 2 and r.get("mdd", 1) < 0.30
    print(f"[putusan] aturan beku di 2020-2022: {'LULUS' if ok else 'TIDAK LULUS'} (total {r.get('total')}, t {r.get('t')}, "
          f"mdd {r.get('mdd')}, per bulan {r.get('per_bulan')}, $200 -> {r.get('$200')})", flush=True)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

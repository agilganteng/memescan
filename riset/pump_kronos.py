#!/usr/bin/env python3
"""pump_kronos: model AI Kronos sebagai FILTER koin pump.fun yang BELUM lulus (masih di bonding curve).

Ditetapkan 20 Nov 2026 sebelum dijalankan (tidak disetel):
  - Data: rekaman memescan 7 hari terakhir, hanya kurva standar (dicek sebelum sinyal, tanpa info masa depan).
  - S1: sinyal di umur 120 dtk. Kronos melihat 24 candle 5 detik (0-120 dtk), meramal 12 candle (60 dtk).
  - S2: sinyal di umur 600 dtk. Kronos melihat 32 candle 15 detik (120-600 dtk), meramal 20 candle (5 menit).
  - Koin harus masih hidup: minimal 8 candle berisi transaksi dan rekaman berlanjut >= 60 dtk setelah sinyal.
  - Sampel acak tetap maksimal --max koin per sinyal, urut waktu. A = paruh awal, B = paruh akhir.
  - Filter dan syarat lulus sama dengan lulus_kronos. Mesin jual-beli: deep.sim_trade (telat 3-9 dtk), biaya 2,5%.
Catatan: Kronos dilatih di candle bursa >= 1 menit; candle 5-15 detik ada di luar data latihnya.
"""
import argparse
import bisect

import numpy as np

import deep
import kronos_util as ku
import lulus_cari as lc

SETUPS = {
    "S1 umur 120 dtk (candle 5 dtk)": dict(t=120.0, a=0.0, step=5.0, L=24, plen=12,
                                            ex=("T60_slNone", "T300_sl0.3", "tr0.2_0.1")),
    "S2 umur 600 dtk (candle 15 dtk)": dict(t=600.0, a=120.0, step=15.0, L=32, plen=20,
                                             ex=("T300_sl0.3", "T600_sl0.3", "tr0.2_0.1")),
}


def candles(c, a, step, L):
    out, tt, last, act = [], [], None, 0
    k = bisect.bisect_left(c.starts, a)
    if k > 0:
        last = c.cs[k - 1][4]
    if last is None:
        last = c.m0
    for b in range(L):
        s = a + b * step
        o, hi, lo, cl, vol = last, last, last, last, 0.0
        if k < len(c.cs) and abs(c.cs[k][0] - s) < 0.5:
            _, _, h, l, cl = c.cs[k]
            hi, lo = max(o, h), min(o, l)
            vb = c.cum_b[k] - (c.cum_b[k - 1] if k else 0.0)
            vs = c.cum_s[k] - (c.cum_s[k - 1] if k else 0.0)
            vol = vb + vs
            act += 1
            k += 1
        if cl <= 0:
            return None
        out.append([o, hi, lo, cl, vol, vol])
        tt.append(c.t0 + s + step)
        last = cl
    return (np.array(out, dtype=np.float64), tt) if act >= 8 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--max", type=int, default=2500)
    ap.add_argument("--stub", action="store_true")
    a = ap.parse_args()
    coins, wid, n_bad = deep.load(a.data, floor="causal")
    print(f"[data] {len(coins)} koin 7 hari terakhir, dibuang {n_bad} ({__import__('time').time() - lc.T0:.0f}s)", flush=True)
    pred = None if a.stub else ku.muat()
    for nm, s in SETUPS.items():
        ev, ys = [], []
        idx = [i for i, c in enumerate(coins) if c.end >= s["t"] + 60 and c.tbad > s["t"] and c.kbad > s["t"]]
        rng = np.random.default_rng(int(s["t"]))
        rng.shuffle(idx)
        for i in idx:
            c = coins[i]
            r = candles(c, s["a"], s["step"], s["L"])
            if r is None:
                continue
            y = []
            for ex in s["ex"]:
                t = deep.sim_trade(c, s["t"], ex)
                y.append(deep.mult(t, "2,5%") if t else np.nan)
            if any(np.isnan(y)):
                continue
            ev.append((c.t0, r, y))
            if len(ev) >= a.max:
                break
        ev.sort(key=lambda e: e[0])
        print(f"\n## {nm}: {len(idx)} koin masih hidup, {len(ev)} dipakai", flush=True)
        if len(ev) < 100:
            continue
        P = ku.ramal(pred, [e[1] for e in ev], s["step"], s["plen"], stub=a.stub)
        ku.tabel(P, np.array([e[2] for e in ev]), list(s["ex"]))
    print(f"[selesai] {__import__('time').time() - lc.T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

"""Cek apakah hasil ekstrem di luas.py (rata 3-8x per trade) asli atau artefak data.

Ulang konfigurasi teratas-T: copy L4 1 wallet +15 dtk, filter likuiditas rendah & porsi bot rendah, jual 60 dtk.
Cetak trade dengan hasil > 3x beserta candle-nya, dan hitung berapa koin di T yang punya lompatan harga aneh.

Pakai: python3 riset/cek_luas.py --data data
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import deep  # noqa: E402
import luas  # noqa: E402

w2, ms = deep.w2, deep.ms


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    cfg = ms.load_config(a.data)
    coins, wid, _ = deep.load(a.data)
    N = len(coins)
    W, PT = coins[:N // 4], coins[N // 4:]
    nP = N // 2 - N // 4
    _, beh, _ = deep.wallet_lists(W, len(wid), cfg)
    W3 = W[2 * len(W) // 3:]
    S3 = w2.wallet_stats(W3, len(wid), cfg, W3[len(W3) // 2].t0)
    L4 = (S3["n"] >= 3) & (np.nan_to_num(S3["cp_mean"]) >= 1.3) & ~S3["sniper"].astype(bool)
    G = luas.build_grid(PT)
    isP = np.zeros(len(PT), bool)
    isP[:nP] = True
    wcp = luas.wallet_cp(PT, beh)

    # mint per t0 dari file mentah
    mint = {}
    d = os.path.join(a.data, "rec")
    for fn in sorted(os.listdir(d)):
        for line in open(os.path.join(d, fn)):
            try:
                r = json.loads(line)
                mint[round(float(r["t0"]), 1)] = (r["m"], r.get("s"), r.get("why"), r["c"][:30], r["snaps"][:3])
            except (ValueError, KeyError):
                pass

    # 1. lompatan harga aneh di T
    C, H, L = G[2], G[0], G[1]
    T = ~isP
    jump = np.nanmax(C[1:] / np.maximum(C[:-1], 1e-12), axis=0)
    hl = np.nanmax(H / np.maximum(L, 1e-12), axis=0)
    m0 = np.array([c.m0 for c in PT])
    lowstart = C[0] < m0 * 0.9
    print(f"Koin T: {T.sum():,}. Close naik >= 5x dalam 5 dtk: {(T & (jump >= 5)).sum():,}; >= 10x: {(T & (jump >= 10)).sum():,}; "
          f"high/low satu candle >= 10x: {(T & (hl >= 10)).sum():,}; close awal < 0,9 x m0: {(T & lowstart).sum():,}")
    mx = np.nanmax(H, axis=0) / m0
    print(f"Puncak / m0 di T: >= 10x {(T & (mx >= 10)).sum():,}, >= 100x {(T & (mx >= 100)).sum():,}, "
          f">= 1000x {(T & (mx >= 1000)).sum():,}. m0 median {np.median(m0):.2f}, min {m0.min():.4g}, max {m0.max():.4g}")

    # 2. ulang T#1
    sig = luas.ev_copy(L4, 1, 15)(G, PT)
    cols = np.nonzero(~np.isnan(sig))[0]
    sub = [PT[j] for j in cols]
    Gs = tuple(g[:, cols] for g in G[:5]) + (G[5][cols],)
    F = luas.features(Gs, sub, sig[cols], wcp[:, cols])
    isPs = isP[cols]
    liq, bot = F["likuiditas"], F["porsi_bot"]
    tl = np.quantile(liq[isPs & ~np.isnan(liq)], 0.33)
    tb = np.quantile(bot[isPs & ~np.isnan(bot)], 0.33)
    m = (liq <= tl) & (bot <= tb) & ~isPs
    print(f"\nT#1 ulang: ambang likuiditas <= {tl:.3g}, porsi_bot <= {tb:.3g}; {m.sum()} sinyal di T")
    rng = np.random.default_rng(1)
    gx, te, tx = luas.run_exit(Gs, np.arange(len(cols)), sig[cols], rng, dict(T=60))
    idx = np.nonzero(m & (gx > 3))[0]
    print(f"Trade > 3x: {len(idx)} dari {int((m & ~np.isnan(gx)).sum())}; rata semua {np.nanmean(gx[m]):.3f}x, "
          f"median {np.nanmedian(gx[m]):.3f}x, rata tanpa > 3x {np.nanmean(np.where(gx[m] > 3, np.nan, gx[m])):.3f}x")
    for i in idx[:12]:
        c = sub[i]
        info = mint.get(round(c.t0, 1))
        print(f"\n  {info[0] if info else '?'} {info[1] if info else ''} why={info[2] if info else ''} m0={c.m0:.4g} "
              f"sinyal {sig[cols][i]:.0f}s masuk {te[i]:.0f}s keluar {tx[i]:.0f}s hasil {gx[i]:.1f}x likuiditas {liq[i]:.1f}")
        if info:
            print("   candle [bucket, high, low, close, sol beli, sol jual, n beli, n jual]:", info[3][:20])
            print("   snaps awal [umur, mcap, ...]:", [s[:4] for s in info[4]])


if __name__ == "__main__":
    main()

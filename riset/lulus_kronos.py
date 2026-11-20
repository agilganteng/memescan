#!/usr/bin/env python3
"""lulus_kronos: model AI Kronos (NeoQuasar/Kronos-small, model dasar candle) sebagai FILTER koin lulusan PumpSwap.

Ditetapkan 20 Nov 2026 sebelum dijalankan (tidak disetel):
  - Candle 1 menit dibuat dari rekaman harga (open = close sebelumnya, volume = vol_m5 / 5).
  - Masuk di menit ke-L setelah harga pertama (L = 30 dan 60). Kronos melihat L candle itu, meramal 30 menit ke depan
    (rata-rata 3 sampel, T=1.0, top_p=0.9). Ramalan = close menit ke-30 / close terakhir - 1.
  - Kronos TIDAK dilatih di data ini, jadi semua data adalah uji. A = paruh waktu awal, B = paruh akhir.
  - Filter: ramalan > 0; > +5%; > +10%; 20% teratas dan 10% teratas (ambang dihitung di A, dipakai di B).
    Pembanding: semua koin; ramalan <= 0; 20% terbawah.
  - Keluar: tahan 30 menit; tahan 1 jam; TP 1,5x SL 30% maksimal 2 jam. Biaya 1,5% per sisi.
  - Lulus: n_B >= 30, rata A > 1, rata B > 1, rata B tanpa koin terbaik > 1.
"""
import argparse
import os
import sys
import time

import numpy as np

import lulus_cari as lc

PRED = 30
EXITS = {"tahan 30m": dict(T=1800), "tahan 1j": dict(T=3600), "TP1.5 SL30 2j": dict(tp=1.5, sl=0.30, T=7200)}


def bars(v, L):
    """L candle 1 menit dari polling. Kembalikan (ohlcva L x 6, t_candle L, indeks baris masuk) atau None."""
    ts_ = [z[0] for z in v]
    k0 = next((k for k, z in enumerate(v) if z[1] > 0), None)
    if k0 is None:
        return None
    t0 = ts_[k0]
    out, tt, k, last, have = [], [], k0, v[k0][1], 0
    for b in range(L):
        end = t0 + (b + 1) * 60
        o, hi, lo, vol, got = last, last, last, 0.0, False
        while k < len(v) and ts_[k] < end:
            p = v[k][1]
            if p <= 0:
                return None
            last, got = p, True
            hi, lo = max(hi, p), min(lo, p)
            vol = v[k][4] / 5.0
            k += 1
        have += got
        out.append([o, hi, lo, last, vol / last if last > 0 else 0.0, vol])
        tt.append(end)
    if have < 0.7 * L or k >= len(v) or ts_[k] - (t0 + L * 60) > 300 or v[k][1] <= 0:
        return None
    return np.array(out, dtype=np.float64), tt, k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--max", type=int, default=0, help="maksimal kejadian per L (acak tetap); 0 = semua")
    ap.add_argument("--stub", action="store_true", help="tanpa model (uji alur): ramalan = momentum 5 menit")
    ap.add_argument("--model", default="NeoQuasar/Kronos-small")
    ap.add_argument("--batch", type=int, default=48)
    a = ap.parse_args()
    toks, px, t_last = lc.load(a.data)
    toks = {m: x for m, x in toks.items() if not (lc.num(x.get("gt_fdv")) > 1e6)}
    pred = None
    if not a.stub:
        import pandas as pd
        import torch
        sys.path.insert(0, os.environ.get("KRONOS_DIR", "Kronos"))
        from model import Kronos, KronosTokenizer, KronosPredictor
        tk = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        md = Kronos.from_pretrained(a.model)
        pred = KronosPredictor(md, tk, device="cpu", max_context=512)
        print(f"[model] {a.model} siap, thread {torch.get_num_threads()} ({time.time() - lc.T0:.0f}s)", flush=True)
    exn = list(EXITS)
    for L in (30, 60):
        ev = []
        for m, x in toks.items():
            v = px.get(m)
            if not v:
                continue
            r = bars(v, L)
            if r is None:
                continue
            B, tt, i0 = r
            ts_ = [z[0] for z in v]
            if ts_[i0] + 7200 > t_last:
                continue
            ps = [z[1] for z in v]
            y = [lc.sim(ts_, ps, i0, ex) for ex in EXITS.values()]
            ev.append((x["t_seen"], B, tt, y))
        ev.sort(key=lambda e: e[0])
        if a.max and len(ev) > a.max:
            keep = np.sort(np.random.default_rng(L).choice(len(ev), a.max, replace=False))
            ev = [ev[i] for i in keep]
        print(f"\n## L={L} menit: {len(ev)} kejadian", flush=True)
        if len(ev) < 100:
            continue
        P = np.full(len(ev), np.nan)
        for s in range(0, len(ev), a.batch):
            ch = ev[s:s + a.batch]
            if a.stub:
                P[s:s + len(ch)] = [e[1][-1, 3] / e[1][-6, 3] - 1 for e in ch]
                continue
            dfs, xts, yts = [], [], []
            for _, B, tt, _ in ch:
                dfs.append(pd.DataFrame(B, columns=["open", "high", "low", "close", "volume", "amount"]))
                xts.append(pd.Series(pd.to_datetime(tt, unit="s")))
                yts.append(pd.Series(pd.to_datetime([tt[-1] + 60 * (k + 1) for k in range(PRED)], unit="s")))
            try:
                out = pred.predict_batch(dfs, xts, yts, pred_len=PRED, T=1.0, top_p=0.9, sample_count=3, verbose=False)
                P[s:s + len(ch)] = [float(o["close"].iloc[-1]) / e[1][-1, 3] - 1 for o, e in zip(out, ch)]
            except Exception as e:   # noqa: BLE001
                print(f"  batch {s} gagal: {type(e).__name__} {e}", flush=True)
            if (s // a.batch) % 5 == 0:
                print(f"  {s + len(ch)}/{len(ev)} ({time.time() - lc.T0:.0f}s)", flush=True)
        Y = np.array([e[3] for e in ev])
        ok = ~np.isnan(P)
        P, Y = P[ok], Y[ok]
        n = len(P)
        hA = np.arange(n) < n // 2
        q = lambda z: np.quantile(P[hA], z)
        print(f"  ramalan Kronos: median {np.median(P):+.3f}, p10 {np.quantile(P, .1):+.3f}, p90 {np.quantile(P, .9):+.3f}; "
              f"ramalan > 0: {(P > 0).mean():.0%}", flush=True)
        real30 = Y[:, 0]
        rk = lambda z: np.argsort(np.argsort(z))
        print(f"  korelasi peringkat ramalan vs hasil 30 menit: A {np.corrcoef(rk(P[hA]), rk(real30[hA]))[0, 1]:+.3f}, "
              f"B {np.corrcoef(rk(P[~hA]), rk(real30[~hA]))[0, 1]:+.3f}", flush=True)
        filt = [("semua koin", np.ones(n, bool)), ("ramalan > 0", P > 0), ("ramalan > +5%", P > 0.05),
                ("ramalan > +10%", P > 0.10), ("20% teratas", P >= q(0.8)), ("10% teratas", P >= q(0.9)),
                ("ramalan <= 0", P <= 0), ("20% terbawah", P <= q(0.2))]
        for e, ex in enumerate(exn):
            print(f"  -- keluar: {ex}", flush=True)
            for nm, mk in filt:
                ya, yb = Y[mk & hA, e], Y[mk & ~hA, e]
                lul = (len(yb) >= 30 and len(ya) and ya.mean() > 1 and yb.mean() > 1
                       and (yb.sum() - yb.max()) / (len(yb) - 1) > 1 and nm not in ("semua koin", "ramalan <= 0", "20% terbawah"))
                print(f"     {nm:16s} A n={len(ya)} rata {ya.mean() if len(ya) else float('nan'):.3f}x | B {lc.stat(yb)}"
                      f"{'  <== LULUS' if lul else ''}", flush=True)
    print(f"[selesai] {time.time() - lc.T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

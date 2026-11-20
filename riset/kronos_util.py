"""Alat bersama uji filter Kronos: muat model, ramal per batch, tabel filter A/B."""
import os
import sys
import time

import numpy as np

import lulus_cari as lc


def muat(model="NeoQuasar/Kronos-small"):
    import torch
    sys.path.insert(0, os.environ.get("KRONOS_DIR", "Kronos"))
    from model import Kronos, KronosTokenizer, KronosPredictor
    tk = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
    md = Kronos.from_pretrained(model)
    print(f"[model] {model} siap, thread {torch.get_num_threads()} ({time.time() - lc.T0:.0f}s)", flush=True)
    return KronosPredictor(md, tk, device="cpu", max_context=512)


def ramal(pred, ev, step, plen, batch=48, stub=False):
    """ev: daftar (B ohlcva Lx6, tt akhir candle). Kembalikan ramalan = close ke-plen / close terakhir - 1."""
    P = np.full(len(ev), np.nan)
    if not stub:
        import pandas as pd
    for s in range(0, len(ev), batch):
        ch = ev[s:s + batch]
        if stub:
            P[s:s + len(ch)] = [B[-1, 3] / B[-6, 3] - 1 for B, _ in ch]
            continue
        dfs, xts, yts = [], [], []
        for B, tt in ch:
            dfs.append(pd.DataFrame(B, columns=["open", "high", "low", "close", "volume", "amount"]))
            xts.append(pd.Series(pd.to_datetime(tt, unit="s")))
            yts.append(pd.Series(pd.to_datetime([tt[-1] + step * (k + 1) for k in range(plen)], unit="s")))
        try:
            out = pred.predict_batch(dfs, xts, yts, pred_len=plen, T=1.0, top_p=0.9, sample_count=3, verbose=False)
            P[s:s + len(ch)] = [float(o["close"].iloc[-1]) / B[-1, 3] - 1 for o, (B, _) in zip(out, ch)]
        except Exception as e:   # noqa: BLE001
            print(f"  batch {s} gagal: {type(e).__name__} {e}", flush=True)
        if (s // batch) % 5 == 0:
            print(f"  {s + len(ch)}/{len(ev)} ({time.time() - lc.T0:.0f}s)", flush=True)
    return P


def tabel(P, Y, exn):
    ok = ~np.isnan(P)
    P, Y = P[ok], Y[ok]
    n = len(P)
    if n < 100:
        print(f"  hanya {n} ramalan, dilewati", flush=True)
        return
    hA = np.arange(n) < n // 2
    q = lambda z: np.quantile(P[hA], z)
    print(f"  ramalan Kronos: median {np.median(P):+.3f}, p10 {np.quantile(P, .1):+.3f}, p90 {np.quantile(P, .9):+.3f}; "
          f"ramalan > 0: {(P > 0).mean():.0%}", flush=True)
    rk = lambda z: np.argsort(np.argsort(z))
    print(f"  korelasi peringkat ramalan vs hasil ({exn[0]}): A {np.corrcoef(rk(P[hA]), rk(Y[hA, 0]))[0, 1]:+.3f}, "
          f"B {np.corrcoef(rk(P[~hA]), rk(Y[~hA, 0]))[0, 1]:+.3f}", flush=True)
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

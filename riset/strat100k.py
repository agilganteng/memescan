"""Uji 100.000 strategi beli memecoin di rekaman semua koin memescan, cari 3 yang untungnya
paling besar dengan modal $200, tanpa bocor ke masa depan.

Strategi = umur masuk x filter (1 atau 2 syarat fitur) x aturan jual (TP/SL/batas waktu).
Data dibagi menurut waktu: 70% lama untuk MEMILIH, 30% terbaru untuk MENGUJI sekali saja.
  1. Semua strategi dinilai di data lama: untung kotor kalau tiap sinyal dibeli $20.
  2. 500 teratas disimulasikan penuh di data lama ($200, $20 per trade, satu posisi sekaligus,
     berhenti di bawah $40). Top 3 = modal akhir terbesar (umur+filter berbeda).
  3. Top 3 itu diuji sekali di data baru. Hanya angka data baru yang dipakai sebagai hasil.
Biaya sama dengan memescan: jeda eksekusi, fee, slippage, priority fee, dampak harga kurva.

Pakai: python3 riset/strat100k.py --data data [--target 100000]
"""
import argparse
import json
import math
import os
import sys
import time
from array import array
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

AGES = ms.RES_AGES
EXITS = ms.RES_EXITS
SIZE = 0.1
STAKE, START, STOP = 20.0, 200.0, 40.0
G = {}


def load(data_dir):
    """Baca rekaman hemat memori ke array datar: t0, umur akhir, candle, foto fitur per umur.
    Daftar wallet dan isi lain dibuang supaya 250 ribu+ koin muat di runner."""
    t0s, ends, starts, stops = array("d"), array("d"), array("q"), array("q")
    cand = array("d")
    nf = len(ms.FEATURES) + 1
    snap_i = {A: array("q") for A in AGES}
    snap_v = {A: array("d") for A in AGES}
    d = os.path.join(data_dir, "rec")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    cs = [(ms.rec_bucket_start(c[0]), ms.rec_bucket_end(c[0]), c[1], c[2], c[3]) for c in r["c"]]
                    sn = [(s[0], s[1:]) for s in r["snaps"] if s[0] in snap_i and len(s) == nf + 1]
                    t0, end = float(r["t0"]), float(r["end"])
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                i = len(t0s)
                t0s.append(t0)
                ends.append(end)
                starts.append(len(cand) // 5)
                for c in cs:
                    cand.extend(c)
                stops.append(len(cand) // 5)
                for A, v in sn:
                    snap_i[A].append(i)
                    snap_v[A].extend(v)
    t0 = np.frombuffer(t0s, dtype=np.float64)
    order = np.argsort(t0, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    C = np.frombuffer(cand, dtype=np.float64).reshape(-1, 5)
    snaps = {}
    for A in AGES:
        idx = rank[np.frombuffer(snap_i[A], dtype=np.int64)] if len(snap_i[A]) else np.zeros(0, np.int64)
        snaps[A] = (idx, np.frombuffer(snap_v[A], dtype=np.float64).reshape(-1, nf))
    return (t0[order], np.frombuffer(ends, dtype=np.float64)[order], np.frombuffer(starts, dtype=np.int64)[order],
            np.frombuffer(stops, dtype=np.int64)[order], C, snaps)


def sim_age(A):
    """Hasil semua aturan jual untuk semua koin yang punya foto di umur A."""
    cfg, ends, starts, stops, C = G["cfg"], G["ends"], G["starts"], G["stops"], G["C"]
    idx, V = G["snaps"][A]
    X = np.column_stack([V[:, 1:], V[:, 0]])      # fitur ... , mcap (urutan sama dengan research)
    M = np.full((len(EXITS), len(idx)), np.nan, dtype=np.float32)
    H = np.full((len(EXITS), len(idx)), np.nan, dtype=np.float32)
    for j, i in enumerate(idx.tolist()):
        cs = [tuple(c) for c in C[starts[i]:stops[i]].tolist()]
        m0 = float(V[j, 0])
        for e, (tp, sl, T) in enumerate(EXITS):
            r = ms.res_trade(cs, float(ends[i]), A, m0, tp, sl, T, cfg, SIZE)
            if r:
                M[e, j], H[e, j] = r[0], r[1] - A
    return A, idx, X, M, H


def sim200(times, mult, held):
    """$200, $20 per trade, satu posisi sekaligus, berhenti di bawah $40."""
    bal, busy, n, w = START, -1.0, 0, 0
    for t, m, h in sorted(zip(times, mult, held)):
        if t < busy or bal < STOP:
            continue
        bal += min(STAKE, bal) * (m - 1)
        busy, n, w = t + h, n + 1, w + (m > 1)
    return bal, n, w


def stat(v):
    v = v[~np.isnan(v)]
    n = len(v)
    if n < 2:
        return n, float("nan"), float("nan"), float("nan")
    m, sd = float(v.mean()), float(v.std(ddof=1))
    return n, m, m - 1.96 * sd / math.sqrt(n), float((v > 1).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--target", type=int, default=100_000)
    ap.add_argument("--train", type=float, default=0.7)
    ap.add_argument("--stage2", type=int, default=500)
    a = ap.parse_args()
    t_start = time.time()
    cfg = ms.load_config(a.data)
    t0_all, ends, starts, stops, C, snaps = load(a.data)
    n_rec = len(t0_all)
    if n_rec < 1000:
        print(f"Baru {n_rec} koin terekam, terlalu sedikit.")
        return
    t_cut = t0_all[int(n_rec * a.train)]
    day = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"== UJI {a.target:,} STRATEGI: {n_rec:,} koin, {day(t0_all[0])} - {day(t0_all[-1])} UTC")
    print(f"   Data lama (pilih): s/d {day(t_cut)} UTC · data baru (uji sekali): sesudahnya")
    print(f"   Biaya: jeda {cfg['EXEC_DELAY']:g} dtk, fee {cfg['FEE_PCT']:.2%}, slippage {cfg['SLIPPAGE']:.0%}, "
          f"priority fee {cfg['PRIORITY_FEE']} SOL, dampak kurva, {SIZE} SOL per trade")
    print(f"   Data dibaca ({time.time() - t_start:.0f} dtk)")

    G.update(cfg=cfg, ends=ends, starts=starts, stops=stops, C=C, snaps=snaps)
    per_age = {}
    with Pool(min(4, os.cpu_count() or 2)) as pool:
        for A, idx, X, M, H in pool.imap_unordered(sim_age, AGES):
            print(f"   umur {A} dtk: {len(idx):,} koin disimulasikan ({time.time() - t_start:.0f} dtk)")
            if len(idx) >= 300:
                per_age[A] = (idx, X, M, H)
    G.clear()
    names = ms.FEATURES + ["mcap"]

    # ---- filter: 1 syarat (desil data lama) lalu ditambah pasangan 2 syarat sampai target tercapai
    ages = sorted(per_age)
    need = math.ceil(a.target / (len(ages) * len(EXITS)))
    rng = np.random.default_rng(7)
    filt = {}
    for A in ages:
        idx, X, M, H = per_age[A]
        tr = t0_all[idx] < t_cut
        singles = []
        for j, nm in enumerate(names):
            col = X[:, j]
            for q in sorted(set(np.quantile(col[tr], np.arange(0.1, 1.0, 0.1)).round(6))):
                singles.append((f"{nm} >= {q:.4g}", j, col >= q))
                singles.append((f"{nm} <= {q:.4g}", j, col <= q))
        fl = [("semua koin", np.ones(len(idx), bool))] + [(lab, m) for lab, _, m in singles]
        seen = set()
        while len(fl) < need:
            p, q = rng.choice(len(singles), 2, replace=False)
            if singles[p][1] == singles[q][1] or (min(p, q), max(p, q)) in seen:
                continue
            seen.add((min(p, q), max(p, q)))
            fl.append((f"{singles[p][0]} & {singles[q][0]}", singles[p][2] & singles[q][2]))
        filt[A] = fl[:need]
    total = sum(len(filt[A]) for A in ages) * len(EXITS)
    print(f"   {total:,} strategi = {len(ages)} umur masuk x {len(EXITS)} aturan jual x {need} filter "
          f"(1-2 syarat fitur)")

    # ---- tahap 1: untung kotor $20 per sinyal di data lama (matriks, cepat)
    cand = []      # (untung $, A, e, f, n)
    n_pos = 0
    for A in ages:
        idx, X, M, H = per_age[A]
        tr = t0_all[idx] < t_cut
        F = np.array([m & tr for _, m in filt[A]], dtype=np.float32)
        ok = ~np.isnan(M)
        prof = F @ (np.where(ok, M - 1, 0).T * STAKE)     # filter x exit
        cnt = F @ ok.T.astype(np.float32)
        n_pos += int(((prof > 0) & (cnt >= 30)).sum())
        for f, e in zip(*np.where(cnt >= 30)):
            cand.append((float(prof[f, e]), A, int(e), int(f), int(cnt[f, e])))
    print(f"   Tahap 1: {len(cand):,} strategi punya >=30 sinyal di data lama; "
          f"{n_pos:,} untung kalau semua sinyal dibeli $20")
    cand.sort(key=lambda c: -c[0])

    # ---- tahap 2: simulasi $200 penuh di data lama untuk 500 teratas
    def series(A, e, f, part):
        idx, X, M, H = per_age[A]
        tt = t0_all[idx]
        sel = filt[A][f][1] & ((tt < t_cut) if part == "lama" else (tt >= t_cut)) & ~np.isnan(M[e])
        return tt[sel] + A + cfg["EXEC_DELAY"], M[e][sel].astype(float), H[e][sel].astype(float)

    s2 = []
    for c in cand[:a.stage2]:
        bal, n, w = sim200(*series(c[1], c[2], c[3], "lama"))
        if n >= 30:
            s2.append((bal, n, w) + c[1:4])
    s2.sort(key=lambda r: -r[0])
    top, seen_af = [], set()
    for r in s2:
        if (r[3], r[5]) not in seen_af:
            seen_af.add((r[3], r[5]))
            top.append(r)
        if len(top) == 3:
            break

    def ex_lab(e):
        tp, sl, T = EXITS[e]
        return f"TP {tp:g}x, SL -{sl:.0%}, maks {T / 60:g} menit"

    def fmt(st):
        n, m, lo, w = st
        return f"n={n}, menang {w:.0%}, rata {m:.3f}x (CI bawah {lo:.3f})" if n >= 2 else f"n={n}"

    # pembanding: beli semua koin, aturan jual terbaik di data lama
    base = max((c for c in cand if filt[c[1]][c[3]][0] == "semua koin"), key=lambda c: c[0] / c[4], default=None)
    if base:
        _, A, e, f, _ = base
        bal, n, w = sim200(*series(A, e, f, "baru"))
        print(f"\n== PEMBANDING beli semua koin (umur {A} dtk, {ex_lab(e)}): data baru {fmt(stat(series(A, e, f, 'baru')[1]))}; "
              f"$200 -> ${bal:.2f} ({n} trade)")

    print("\n== TOP 3 (dipilih dari modal akhir $200 terbesar di DATA LAMA), lalu diuji sekali di DATA BARU")
    for k, (bal_tr, n_tr, w_tr, A, e, f) in enumerate(top, 1):
        lab = filt[A][f][0]
        tt, mm, hh = series(A, e, f, "baru")
        bal, n, w = sim200(tt, mm, hh)
        st = stat(mm)
        ok = st[0] >= 30 and st[2] > 1.0
        print(f"\n#{k} [{'TERBUKTI' if ok else 'GAGAL'}] beli di umur {A} dtk · {lab} · {ex_lab(e)}")
        print(f"   data lama: $200 -> ${bal_tr:.2f} ({bal_tr - START:+.2f}), {n_tr} trade, menang {w_tr / n_tr:.0%}")
        print(f"   data baru: {fmt(st)}")
        lo, hi = ms.wilson(w, n) if n else (0, 0)
        print(f"   SIMULASI $200 data baru: {n} trade, menang {w}{f' ({w / n:.0%}, CI {lo:.0%}-{hi:.0%})' if n else ''}, "
              f"modal akhir ${bal:.2f} ({bal - START:+.2f})" + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))

    # cek jujur: dari 500 teratas di data lama, berapa yang tetap untung di data baru
    still = 0
    for c in cand[:a.stage2]:
        bal, n, _ = sim200(*series(c[1], c[2], c[3], "baru"))
        still += bal > START and n >= 30
    print(f"\n== Dari {a.stage2} strategi terbaik di data lama, {still} yang tetap untung di data baru (>=30 trade).")
    print("   Data rekaman baru mulai pertengahan Okt 2026, jadi Jan 2026 - sekarang tidak bisa disimulasikan.")
    print(f"   Selesai dalam {time.time() - t_start:.0f} dtk.")


if __name__ == "__main__":
    main()

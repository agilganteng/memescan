"""Riset strategi yang belum pernah dicoba (25 Okt 2026), semua di rekaman koin pump.fun.

Selama ini semua strategi masuk di umur tetap (10 dtk, 30 dtk, ...). Di sini masuknya dipicu kejadian:
  grad     : market cap pertama kali tembus 100-350 SOL (main dekat graduation, lulus ~410 SOL)
  dip      : sudah naik 2x/3x/5x dari awal, lalu turun 30/50/70% dari puncak -> beli turunnya
  breakout : tembus 1,5x/2x/3x dari harga awal untuk pertama kali SETELAH umur 1/3/10 menit
  copycat  : simbol sama dengan koin lain yang barusan (1 jam / 6 jam terakhir) tembus 200 SOL
  semua    : pembanding, beli semua koin di umur 30 dtk / 2 menit
Lalu tiap strategi dikali filter baru:
  jam rilis (UTC 0-6, 6-12, 12-18, 18-24 atau semua)
  kondisi pasar (jumlah koin yang tembus 100 SOL dalam 1 jam terakhir: ramai / sepi / semua)
Aturan jual: TP 1,5x/2x/3x x SL 25%/40% x maks 5/15 menit.
Dipilih di 70% data lama, diuji sekali di 30% data baru, simulasi $200 ($20 per trade).
Koin dengan kurva tidak standar dibuang (rekamannya terpotong).

Pakai: python3 riset/event.py --data data
"""
import argparse
import bisect
import json
import math
import os
import re
import sys
import time
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

EXITS = [(tp, sl, T) for tp in (1.5, 2.0, 3.0) for sl in (0.25, 0.4) for T in (300, 900)]
NE = len(EXITS)
GRAD = (100, 150, 200, 250, 300, 350)
DIP = [(pk, dr) for pk in (2, 3, 5) for dr in (0.3, 0.5, 0.7)]
BRK = [(mu, ma) for mu in (1.5, 2, 3) for ma in (60, 180, 600)]
COPY = [(w, a) for w in (3600, 21600) for a in (10, 30, 60)]
BASE = (30, 120)
HOT, RUNNER = 100.0, 200.0
SIZE = 0.1
STAKE, START, STOP = 20.0, 200.0, 40.0
FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}
G = {}


def files(data_dir):
    d = os.path.join(data_dir, "rec")
    return [os.path.join(d, f) for f in sorted(os.listdir(d))] if os.path.isdir(d) else []


def norm(sym):
    s = re.sub(r"[^a-z0-9]", "", str(sym or "").lower())
    return s if len(s) >= 2 else ""


def bad(r):
    return any(s[FI["inflow_sol"]] == 0 and s[FI["growth"]] > 1.05 for s in r["snaps"])


def pass1(fp):
    hot, run = [], []
    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
                t0 = float(r["t0"])
                if bad(r):
                    continue
                th = tr = None
                for c in r["c"]:
                    if th is None and c[1] >= HOT:
                        th = t0 + ms.rec_bucket_end(c[0])
                    if c[1] >= RUNNER:
                        tr = t0 + ms.rec_bucket_end(c[0])
                        break
            except (ValueError, KeyError, TypeError, IndexError):
                continue
            if th:
                hot.append(th)
            if tr and norm(r.get("s")):
                run.append((norm(r.get("s")), tr, r.get("m")))
    return hot, run


def trades(cs, end, A, m, cfg):
    out = []
    for tp, sl, T in EXITS:
        x = ms.res_trade(cs, end, A, m, tp, sl, T, cfg, SIZE)
        out.append((x[0], x[1] - A) if x else (np.nan, np.nan))
    return out


def pass2(fp):
    cfg, hot, runs = G["cfg"], G["hot"], G["runs"]
    res = {}

    def add(key, t0, A, cs, end, m, hour, reg):
        if A + cfg["EXEC_DELAY"] >= end:
            return
        res.setdefault(key, []).append((t0 + A, hour, reg, trades(cs, end, A, m, cfg)))

    with open(fp) as f:
        for line in f:
            try:
                r = json.loads(line)
                if bad(r):
                    continue
                t0, end = float(r["t0"]), float(r["end"])
                m0 = float(r.get("m0") or r["snaps"][0][1])
                cs = [(ms.rec_bucket_start(c[0]), ms.rec_bucket_end(c[0]), c[1], c[2], c[3]) for c in r["c"]]
                snaps = {s[0]: s[1] for s in r["snaps"]}
            except (ValueError, KeyError, TypeError, IndexError):
                continue
            if not cs or m0 <= 0:
                continue
            hour = time.gmtime(t0).tm_hour // 6
            reg = bisect.bisect_left(hot, t0) - bisect.bisect_left(hot, t0 - 3600)
            for A in BASE:
                if A in snaps:
                    add(("semua", A), t0, A, cs, end, snaps[A], hour, reg)
            for thr in GRAD:
                k = next((i for i, c in enumerate(cs) if c[2] >= thr), None)
                if k is not None and cs[k][1] < 1700:
                    add(("grad", thr), t0, cs[k][1], cs, end, cs[k][4], hour, reg)
            for pk, dr in DIP:
                peak, armed = 0.0, False
                for c in cs:
                    if armed and c[3] <= peak * (1 - dr):
                        if c[1] < 1700:
                            add(("dip", pk, dr), t0, c[1], cs, end, c[4], hour, reg)
                        break
                    peak = max(peak, c[2])
                    armed = armed or peak >= m0 * pk
            for mu, ma in BRK:
                hi = 0.0
                for c in cs:
                    if c[0] >= ma and c[2] >= m0 * mu and hi < m0 * mu:
                        if c[1] < 1700:
                            add(("breakout", mu, ma), t0, c[1], cs, end, c[4], hour, reg)
                        break
                    hi = max(hi, c[2])
            s = norm(r.get("s"))
            if s in runs:
                for w, A in COPY:
                    if A in snaps and any(t0 - w <= tr < t0 and mm != r.get("m") for tr, mm in runs[s]):
                        add(("copycat", w, A), t0, A, cs, end, snaps[A], hour, reg)
    return res


def sim200(tr):
    bal, busy, n, w = START, -1.0, 0, 0
    for t, m, h in sorted(tr):
        if t < busy or bal < STOP:
            continue
        bal += min(STAKE, bal) * (m - 1)
        busy, n, w = t + h, n + 1, w + (m > 1)
    return bal, n, w


def stat(v):
    v = np.asarray(v, dtype=float)
    n = len(v)
    if n < 2:
        return n, float("nan"), float("nan"), float("nan")
    m, sd = float(v.mean()), float(v.std(ddof=1))
    return n, m, m - 1.96 * sd / math.sqrt(n), float((v > 1).mean())


def fmt(st):
    n, m, lo, w = st
    return f"n={n}, menang {w:.0%}, rata {m:.3f}x (CI bawah {lo:.3f})" if n >= 2 else f"n={n}"


def lab_key(k):
    if k[0] == "semua":
        return f"beli semua di umur {k[1]} dtk"
    if k[0] == "grad":
        return f"beli saat mcap tembus {k[1]} SOL"
    if k[0] == "dip":
        return f"beli turun {k[2]:.0%} dari puncak setelah naik {k[1]}x"
    if k[0] == "breakout":
        return f"beli tembus {k[1]}x setelah umur {k[2] // 60} mnt"
    return f"copycat simbol koin yang tembus 200 SOL dalam {k[1] // 3600} jam, masuk umur {k[2]} dtk"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    fs = files(a.data)
    G["cfg"] = ms.load_config(a.data)
    with Pool(min(4, os.cpu_count() or 1)) as p:
        r1 = p.map(pass1, fs)
    G["hot"] = sorted(t for h, _ in r1 for t in h)
    runs = {}
    for _, rr in r1:
        for s, tr, m in rr:
            runs.setdefault(s, []).append((tr, m))
    G["runs"] = runs
    print(f"== Lintasan 1: {len(G['hot']):,} koin tembus {HOT:g} SOL, {sum(map(len, runs.values())):,} tembus {RUNNER:g} SOL "
          f"({time.time() - t_start:.0f} dtk)")
    with Pool(min(4, os.cpu_count() or 1)) as p:
        r2 = p.map(pass2, fs)
    data = {}
    for d in r2:
        for k, v in d.items():
            data.setdefault(k, []).extend(v)
    print(f"== Lintasan 2 selesai ({time.time() - t_start:.0f} dtk). Kejadian per keluarga:")
    for k in sorted(data, key=str):
        print(f"   {lab_key(k):<75} {len(data[k]):>8,} koin")

    T_all = np.array(sorted(t for v in data[("semua", 30)] for t in [v[0]]))
    t_cut = float(np.quantile(T_all, 0.7))
    reg_all = np.array([v[2] for v in data[("semua", 30)] if v[0] < t_cut])
    reg_med = float(np.median(reg_all))
    print(f"   Data lama (pilih) s/d {time.strftime('%d/%m %H:%M', time.gmtime(t_cut))} UTC. "
          f"Pasar 'ramai' = >{reg_med:g} koin tembus {HOT:g} SOL dalam 1 jam terakhir.")

    HOURS = (None, 0, 1, 2, 3)
    REGS = (None, "ramai", "sepi")
    arr = {}
    for k, v in data.items():
        t = np.array([x[0] for x in v])
        h = np.array([x[1] for x in v])
        g = np.array([x[2] for x in v])
        M = np.array([[y[0] for y in x[3]] for x in v], dtype=float).T
        H = np.array([[y[1] for y in x[3]] for x in v], dtype=float).T
        arr[k] = (t, h, g, M, H)

    def sel(k, hr, rg, new):
        t, h, g, _, _ = arr[k]
        s = (t >= t_cut) if new else (t < t_cut)
        if hr is not None:
            s &= h == hr
        if rg == "ramai":
            s &= g > reg_med
        elif rg == "sepi":
            s &= g <= reg_med
        return s

    cands = []
    for k in arr:
        for hr in HOURS:
            for rg in REGS:
                s_old = sel(k, hr, rg, False)
                M = arr[k][3]
                for e in range(NE):
                    v = M[e][s_old]
                    v = v[~np.isnan(v)]
                    if len(v) >= 30:
                        cands.append(((v.mean() - 1) * len(v) * STAKE, float(v.mean()), len(v), k, hr, rg, e))
    n_strat = len(arr) * len(HOURS) * len(REGS) * NE
    cands.sort(key=lambda x: -x[0])
    print(f"\n== {n_strat:,} strategi, {len(cands):,} punya >=30 trade di data lama, "
          f"{sum(c[1] > 1 for c in cands):,} untung di data lama.")

    def lab(k, hr, rg, e):
        tp, sl, T = EXITS[e]
        return (f"{lab_key(k)}, jam {'semua' if hr is None else f'{hr * 6:02d}-{hr * 6 + 6:02d} UTC'}, "
                f"pasar {rg or 'semua'}, TP {tp:g}x SL -{sl:.0%} maks {T // 60} mnt")

    def test(k, hr, rg, e):
        t, _, _, M, H = arr[k]
        s = sel(k, hr, rg, True) & ~np.isnan(M[e])
        tr = list(zip(t[s].tolist(), M[e][s].tolist(), H[e][s].tolist()))
        return stat([x[1] for x in tr]), sim200(tr)

    top = cands[:500]
    ok = 0
    for c in top:
        st, _ = test(*c[3:])
        ok += st[0] >= 30 and st[1] > 1
    print(f"   Dari 500 terbaik di data lama, {ok} tetap untung di data baru (>=30 trade).")
    print("\n== TOP 3 (dipilih di data lama, diuji sekali di data baru)")
    seen = set()
    rank = 0
    for c in top:
        if c[3] in seen:
            continue
        seen.add(c[3])
        rank += 1
        st, (bal, n, w) = test(*c[3:])
        lo, hi = ms.wilson(w, n) if n else (0, 0)
        print(f"\n #{rank} {lab(*c[3:])}")
        print(f"    data lama: n={c[2]}, rata {c[1]:.3f}x")
        print(f"    DATA BARU: {fmt(st)} -> {'TERBUKTI' if st[0] >= 30 and st[2] > 1 else 'TIDAK terbukti'}")
        print(f"    SIMULASI $200: {n} trade, menang {w}{f' ({w / n:.0%}, CI {lo:.0%}-{hi:.0%})' if n else ''}, "
              f"akhir ${bal:.2f} ({bal - START:+.2f})" + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))
        if rank == 3:
            break
    print("\n== TERBAIK PER KELUARGA (data lama -> data baru)")
    for fam in ("grad", "dip", "breakout", "copycat", "semua"):
        c = next((c for c in cands if c[3][0] == fam), None)
        if c:
            st, (bal, n, w) = test(*c[3:])
            print(f"   {lab(*c[3:])}\n      lama {c[1]:.3f}x (n={c[2]}) | baru {fmt(st)} | $200 -> ${bal:.2f} ({n} trade)")
    print(f"\n   Selesai {time.time() - t_start:.0f} dtk. Data rekaman mulai 14 Okt 2026, jadi Jan 2026 - sekarang tidak bisa disimulasikan.")


if __name__ == "__main__":
    main()

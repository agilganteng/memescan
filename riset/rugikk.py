"""Backtest bot dari post X @rugikkk "Grok Bot pump.fun app $1.000 -> $6.840 dalam 18 detik" (28 Okt 2026).
Post-nya sendiri menulis "illustrative build, numbers simulated". Yang diuji di sini adalah ATURANNYA:
  1. dev pegang > 10% -> skip
  2. dev yang sama dengan rug lama -> skip
  3. masuk di "30 pembeli pertama" (snapshot umur awal dengan unique_buyers <= 30)
  4. dev atau bundle bergerak (jual) -> keluar SEKARANG
  5. jual otomatis (TP/SL tidak disebut -> diuji beberapa, dipilih di A, diuji di B)
  Tidak bisa diuji: "X trend reader" (tidak ada data X) dan "graduated" (rekaman kita hanya kurva pump.fun;
  token setelah graduate sudah diuji di rugdesk: 0,39x).

Data  : koin pump.fun dengan data wallet (dev & bundler terlihat, 5 menit pertama), sampel 1 dari 3 koin.
Aturan PRA-DAFTAR ("aturan dia"): masuk umur 10 dtk kalau dev <= 10%, dev bukan perug, pembeli <= 30, kurva standar,
  dev & bundler belum jual; keluar saat dev/bundler jual, TP +100%, tanpa SL, maks 10 menit.
Jeda   : 1-3 dtk (bot cepat, optimis) dan 3-8 dtk. Biaya fee 1,25%/sisi + priority fee 0,0005 SOL x2 + dampak kurva.
Ukuran : 10% saldo, maks 1 posisi (varian maks 5). Modal $100 / $200 / $1000.
Variasi: umur masuk {10,20,30,45,60} x batas pembeli {30, bebas} x dev {<=10%, bebas} x rug {buang, abaikan}
  x jual-saat-dev/bundler {ya, tidak} x TP {30,50,100,200%, tanpa} x SL {15,30,50%, tanpa} x maks tahan {1,5,10,30 mnt}
  = 40 x 2 x 80 = 6.400 strategi. Pilih di A (50% koin pertama), uji sekali di B.

Pakai: python3 riset/rugikk.py --data data
"""
import argparse
import bisect
import math
import os
import random
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import insider4 as i4  # noqa: E402
import hybrid as hy  # noqa: E402

ms = i4.ms
FI = i4.FI
CAPS = (100.0, 200.0, 1000.0)
FRAC = 0.10
FEE = 0.0125
PRIO = 0.0005
AGES = (10, 20, 30, 45, 60)
EXITS = [(tp, sl, tm) for tp in (0.3, 0.5, 1.0, 2.0, math.inf) for sl in (0.15, 0.30, 0.50, 1.0)
         for tm in (60.0, 300.0, 600.0, 1800.0)]
TP = np.array([e[0] for e in EXITS])
SL = np.array([e[1] for e in EXITS])
TM = np.array([e[2] for e in EXITS])
RULE_EXIT = EXITS.index((1.0, 1.0, 600.0))


def ename(k):
    tp, sl, tm = EXITS[k]
    return (f"TP +{tp:.0%}" if tp < math.inf else "tanpa TP") + (f", SL {sl:.0%}" if sl < 1 else ", tanpa SL") + \
        f", maks {tm / 60:.0f} mnt"


def trade(c, t_sig, size_sol, lat, force):
    """Semua cara jual sekaligus. force = umur dev/bundler jual (inf kalau tidak dipakai/tidak ada)."""
    rng = random.Random(zlib.crc32(f"{c.i}:{t_sig}:{lat}".encode()))
    d_in, d_out = rng.uniform(*lat), rng.uniform(*lat)
    te = t_sig + d_in
    if te >= c.end - 1:
        return None
    p_in = i4.price_at(c, te)
    if p_in <= 0:
        return None
    entry = p_in * (1 + size_sol / ms.v_sol_at(p_in)) / (1 - FEE)
    n = len(EXITS)
    done = np.zeros(n, bool)
    out = np.zeros(n)
    tout = np.full(n, c.end)
    k = bisect.bisect_right(c.starts, te)
    last = p_in
    f_on = force > te
    for a, b, h, lo, cl in c.cs[k:]:
        act = ~done
        if not act.any():
            break
        tm = act & (a >= te + TM)
        if tm.any():
            out[tm] = i4.price_at(c, min(c.end, a + d_out))
            tout[tm] = a
            done |= tm
            act = ~done
        hit = act & (lo <= entry * (1 - SL))
        if hit.any():
            out[hit] = np.minimum(entry * (1 - SL[hit]), i4.price_at(c, min(c.end, a + d_out)))
            tout[hit] = a
            done |= hit
            act = ~done
        tp = act & (h >= entry * (1 + TP))
        if tp.any():
            out[tp] = np.minimum(entry * (1 + TP[tp]), max(i4.price_at(c, min(c.end, a + d_out)), cl))
            tout[tp] = a
            done |= tp
            act = ~done
        if f_on and force < b and act.any():
            out[act] = i4.price_at(c, min(c.end, force + d_out))
            tout[act] = force
            done |= act
        last = cl
    out[~done] = last
    sell = out * (1 - FEE) / (1 + size_sol / np.array([ms.v_sol_at(max(p, 1e-9)) for p in out]))
    return sell / entry - 2 * PRIO / size_sol, tout, te


def sim(trades, cap, max_pos=1):
    eq, open_, rows, peak, mdd = cap, [], [], cap, 0.0
    for t, x, tx in sorted(trades):
        keep = []
        for te_, st, xx in open_:
            if te_ <= t:
                eq += st * xx
            else:
                keep.append((te_, st, xx))
        open_ = keep
        if len(open_) >= max_pos or eq <= 0.01:
            continue
        st = eq * FRAC
        eq -= st
        open_.append((tx, st, x))
        rows.append(x)
        tot = eq + sum(s for _, s, _ in open_)
        peak = max(peak, tot)
        mdd = max(mdd, 1 - tot / peak)
    eq += sum(s * xx for _, s, xx in open_)
    return eq, rows, mdd


def summ(label, trades, cap, max_pos=1):
    eq, rows, mdd = sim(trades, cap, max_pos)
    n = len(rows)
    if not n:
        return f"   {label}: 0 trade"
    k = sum(x > 1 for x in rows)
    lo, hi = ms.wilson(k, n)
    w = [x - 1 for x in rows if x > 1]
    l_ = [x - 1 for x in rows if x <= 1]
    return (f"   {label}: ${cap:,.0f} -> ${eq:,.2f} ({eq / cap - 1:+.0%}) | {n} trade{' (<30!)' if n < 30 else ''} | "
            f"menang {k / n:.0%} [{lo:.0%}-{hi:.0%}] | rata menang {np.mean(w) if w else 0:+.1%} kalah "
            f"{np.mean(l_) if l_ else 0:+.1%} | MDD {mdd:.0%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t0 = time.time()
    hs, ps, src = hy.sol_prices(time.time() - 40 * 86400, time.time())
    su = float(np.median(ps))
    coins, wid, n_all, n_bug = i4.load(a.data, math.inf, every=3, need_w=True)
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))  # noqa: E731
    half = coins[len(coins) // 2].t0
    print(f"== {n_all:,} koin terekam; diuji {len(coins):,} koin (punya data wallet, sampel 1 dari 3) "
          f"{ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC. A < {ts(half)} <= B. Harga SOL {src} median ${su:.0f}.")
    print("   Batas data: rekaman mulai Okt 2026, wallet hanya 5 menit pertama. Jan 2026 - sekarang tidak bisa.")
    nd = sum(c.dev_sell < math.inf for c in coins)
    nb = sum(c.bund_sell < math.inf for c in coins)
    print(f"   Dev terlihat jual (5 menit pertama): {nd / len(coins):.0%} koin; bundler jual: {nb / len(coins):.0%} koin")

    def signal(c, age, bcap, dmax, rugk):
        s = c.snaps.get(age)
        if s is None or age > c.end or not (c.kfrom <= age < c.kbad):
            return False
        if bcap and s[FI["unique_buyers"]] > bcap:
            return False
        if dmax and s[FI["dev_pct"]] > dmax:
            return False
        if rugk and s[FI["creator_prev_rugs"]] > 0:
            return False
        return min(c.dev_sell, c.bund_sell, c.dev_snap) > age

    cache = {}

    def res(c, age, cap, lat, force_on):
        key = (c.i, age, cap, lat, force_on)
        if key not in cache:
            f = min(c.dev_sell, c.bund_sell, c.dev_snap) if force_on else math.inf
            cache[key] = trade(c, age, cap * FRAC / su, lat, f)
        return cache[key]

    def run(cfg, k, cap, lat, part=None):
        age, bcap, dmax, rugk, force = cfg
        tr = []
        for c in coins:
            if part == "A" and c.t0 >= half or part == "B" and c.t0 < half:
                continue
            if signal(c, age, bcap, dmax, rugk):
                r = res(c, age, cap, lat, force)
                if r is not None:
                    tr.append((c.t0 + r[2], float(r[0][k]), c.t0 + float(r[1][k])))
        return tr

    rule = (10, 30, 0.10, True, True)
    print("\n######## 1. ATURAN DIA (pra-daftar): umur 10 dtk, pembeli <= 30, dev <= 10%, buang perug, "
          f"jual saat dev/bundler jual, {ename(RULE_EXIT)}")
    for lat in ((1.0, 3.0), (3.0, 8.0)):
        for cap in CAPS:
            tr = run(rule, RULE_EXIT, cap, lat)
            print(summ(f"jeda {lat[0]:.0f}-{lat[1]:.0f} dtk, maks 1 posisi", tr, cap, 1))
            if cap == 200.0:
                print(summ(f"jeda {lat[0]:.0f}-{lat[1]:.0f} dtk, maks 5 posisi", tr, cap, 5))
                xs = np.array([x for _, x, _ in tr])
                if len(xs):
                    print(f"      semua sinyal: n={len(xs):,}, rata {xs.mean():.3f}x, median {np.median(xs):.3f}x, "
                          f"menang {np.mean(xs > 1):.0%}")
    tr_nf = run((10, 30, 0.10, True, False), RULE_EXIT, 200.0, (1.0, 3.0))
    print(summ("tanpa jual-saat-dev/bundler (pembanding), jeda 1-3", tr_nf, 200.0))
    tr_all = run((10, None, None, False, False), RULE_EXIT, 200.0, (1.0, 3.0))
    print(summ("tanpa filter apa pun (beli semua umur 10 dtk), jeda 1-3", tr_all, 200.0))

    print(f"\n######## 2. VARIASI: {len(AGES) * 2 * 2 * 2 * 2} filter x {len(EXITS)} cara jual, jeda 1-3 dtk, $200")
    rows = []
    for age in AGES:
        for bcap in (30, None):
            for dmax in (0.10, None):
                for rugk in (True, False):
                    for force in (True, False):
                        cfg = (age, bcap, dmax, rugk, force)
                        XA, XB = [], []
                        for c in coins:
                            if signal(c, age, bcap, dmax, rugk):
                                r = res(c, age, 200.0, (1.0, 3.0), force)
                                if r is not None:
                                    (XA if c.t0 < half else XB).append(r[0])
                        XA = np.array(XA) if XA else np.zeros((0, len(EXITS)))
                        XB = np.array(XB) if XB else np.zeros((0, len(EXITS)))
                        for k in range(len(EXITS)):
                            rows.append((cfg, k, len(XA), XA[:, k].mean() if len(XA) else np.nan,
                                         len(XB), XB[:, k].mean() if len(XB) else np.nan))
    ok = [r for r in rows if r[2] >= 30 and r[4] >= 30]
    print(f"   {len(ok):,} strategi dengan >= 30 sinyal di A dan B. Untung di A: {sum(r[3] > 1 for r in ok):,}, "
          f"di B: {sum(r[5] > 1 for r in ok):,}, keduanya: {sum(r[3] > 1 and r[5] > 1 for r in ok):,}. "
          f"({time.time() - t0:.0f} dtk)")
    fx = [r for r in ok if r[0][4]]
    nf = [r for r in ok if not r[0][4]]
    if fx and nf:
        print(f"   Pengaruh jual-saat-dev/bundler (rata semua strategi di B): pakai {np.nanmean([r[5] for r in fx]):.3f}x "
              f"vs tidak {np.nanmean([r[5] for r in nf]):.3f}x")

    def cdesc(cfg):
        age, bcap, dmax, rugk, force = cfg
        return (f"umur {age}s" + (f", pembeli<={bcap}" if bcap else "") + (", dev<=10%" if dmax else "") +
                (", buang perug" if rugk else "") + (", jual saat dev/bundler jual" if force else ""))

    best = sorted(ok, key=lambda r: -r[3])[:5]
    print("\n   5 TERBAIK DI A -> UJI SEKALI DI B:")
    for cfg, k, na, ma, nb_, mb in best:
        print(f"\n   * {cdesc(cfg)} | {ename(k)} | A {ma:.3f}x (n={na}) -> B {mb:.3f}x (n={nb_})")
        for lat in ((1.0, 3.0), (3.0, 8.0)):
            for cap in CAPS:
                print(summ(f"B jeda {lat[0]:.0f}-{lat[1]:.0f}", run(cfg, k, cap, lat, "B"), cap))
    print(f"\nSelesai {time.time() - t0:.0f} dtk. Paper saja.")


if __name__ == "__main__":
    main()

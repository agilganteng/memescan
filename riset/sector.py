"""Backtest "Grok Bot Terminal" dari post X @sector_sol ($44,82 -> $11.643,21 semalam) (28 Okt 2026).
Post-nya sendiri bilang hasilnya tidak terverifikasi, dan videonya menulis "trade-level detail illustrative".
Yang diuji di sini ATURAN yang terlihat di log video:
  scanner : pair baru + lonjakan volume ("spike 3.0x", "volume 7.8x in 5m"), "breakout over 1h high"
  rug     : freeze authority / LP locked (di kurva pump.fun selalu lolos) + dev wallet <= 2% + dev bukan perug
  sizer   : 29-39% equity per trade (dipakai 33%), 1 posisi
  exit    : stop 15%, take-profit 2R (+30%) / 3R (+45%), keluar saat "volume faded 60%"
Aturan PRA-DAFTAR: lonjakan volume 5 menit >= 3x rata-rata sebelumnya (min 2 SOL), dev <= 2%, bukan perug,
  kurva standar; TP +30%, SL 15%, keluar saat volume 60 dtk turun >= 60% dari laju lonjakan, maks 30 mnt.
Variasi: jendela {60, 300 dtk} x kelipatan {3, 5} x breakout {wajib, tidak} x dev<=2% {ya, tidak}
  x holders>=100 {ya, tidak} x volume-fade {ya, tidak} = 64 filter x 36 cara jual (TP 30/45/100%/tanpa x
  SL 15/30%/tanpa x maks 5/15/30 mnt) = 2.304 strategi. Pilih di A (50% koin pertama), uji sekali di B.
Jeda 1-3 dtk dan 3-8 dtk. Biaya fee 1,25%/sisi + priority fee 0,0005 SOL x2 + dampak kurva. Modal $100/$200/$1000.
Batas: hanya koin dengan >= 2 SOL volume di 10 menit pertama dimuat; holders/dev dari snapshot <= 10 menit.

Pakai: python3 riset/sector.py --data data
"""
import argparse
import bisect
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import insider4 as i4  # noqa: E402
import hybrid as hy  # noqa: E402
import rugikk as rk  # noqa: E402

FI = i4.FI
CAPS = (100.0, 200.0, 1000.0)
# rugikk.trade/sim membaca tabel cara-jual dan ukuran posisi dari modulnya sendiri: ganti ke aturan bot ini.
rk.FRAC = 0.33
rk.EXITS = [(tp, sl, tm) for tp in (0.30, 0.45, 1.0, math.inf) for sl in (0.15, 0.30, 1.0)
            for tm in (300.0, 900.0, 1800.0)]
rk.TP = np.array([e[0] for e in rk.EXITS])
rk.SL = np.array([e[1] for e in rk.EXITS])
rk.TM = np.array([e[2] for e in rk.EXITS])
EXITS = rk.EXITS
RULE_EXIT = EXITS.index((0.30, 0.15, 1800.0))
MIN_SOL = 2.0
WINS = (60, 300)
MULTS = (3.0, 5.0)


def features(c):
    """Per waktu keputusan (akhir candle, 30 dtk - 30 mnt): rasio lonjakan per jendela, breakout, dev, holders."""
    ends = [e for e in c.ends if 30 <= e <= min(c.end, 1800)]
    if not ends:
        return None
    t = np.array(ends)
    snap_ages = sorted(c.snaps)
    dev = np.empty(len(t))
    hold = np.empty(len(t))
    rug = np.empty(len(t))
    for j, x in enumerate(t):
        k = bisect.bisect_right(snap_ages, x) - 1
        s = c.snaps[snap_ages[k]] if k >= 0 else None
        dev[j] = s[FI["dev_pct"]] if s is not None else 1.0
        hold[j] = s[FI["holders"]] if s is not None else 0.0
        rug[j] = s[FI["creator_prev_rugs"]] if s is not None else 1.0
    curve = (t >= c.kfrom) & (t < c.kbad)
    out = dict(t=t, dev=dev <= 0.02, hold=hold >= 100, rug=rug == 0, curve=curve)
    highs = np.array([x[2] for x in c.cs])
    cends = np.array(c.ends)
    for w in WINS:
        ratio = np.zeros(len(t))
        recent = np.zeros(len(t))
        brk = np.zeros(len(t), bool)
        for j, x in enumerate(t):
            if x < w + 30:
                continue
            v_now, v_w = i4.vol_until(c, x), i4.vol_until(c, x - w)
            rec = v_now - v_w
            base = v_w / (x - w) * w
            recent[j] = rec
            ratio[j] = rec / base if base > 0 else 0.0
            prior = highs[cends <= x - w]
            brk[j] = prior.size > 0 and i4.price_at(c, x) > prior.max()
        out[f"r{w}"] = ratio
        out[f"v{w}"] = recent
        out[f"b{w}"] = brk
    return out


def fade_time(c, te, rate):
    """Pertama kali volume 60 dtk terakhir < 40% laju lonjakan (per 60 dtk) setelah masuk."""
    for e in c.ends:
        if e < te + 60:
            continue
        if e > c.end:
            break
        if i4.vol_until(c, e) - i4.vol_until(c, e - 60) < 0.4 * rate * 60:
            return e
    return math.inf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t0 = time.time()
    hs, ps, src = hy.sol_prices(time.time() - 40 * 86400, time.time())
    su = float(np.median(ps))
    coins, _, n_all, n_bug = i4.load(a.data, MIN_SOL, every=10 ** 12)
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))  # noqa: E731
    half = coins[len(coins) // 2].t0
    print(f"== {n_all:,} koin terekam; dimuat {len(coins):,} koin dengan >= {MIN_SOL} SOL volume 10 menit pertama, "
          f"{ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC. A < {ts(half)} <= B. Harga SOL {src} median ${su:.0f}.")
    print("   Batas data: rekaman mulai 14 Okt 2026. Jan 2026 - sekarang tidak bisa.", flush=True)

    feats = {}
    for c in coins:
        f = features(c)
        if f is not None:
            feats[c.i] = f
    print(f"   fitur selesai ({time.time() - t0:.0f} dtk)", flush=True)

    def first_sig(c, cfg):
        w, mult, brk, devf, holdf = cfg
        f = feats.get(c.i)
        if f is None:
            return None
        m = f["curve"] & f["rug"] & (f[f"r{w}"] >= mult) & (f[f"v{w}"] >= MIN_SOL)
        if brk:
            m &= f[f"b{w}"]
        if devf:
            m &= f["dev"]
        if holdf:
            m &= f["hold"]
        j = int(np.argmax(m))
        if not m[j]:
            return None
        return float(f["t"][j]), float(f[f"v{w}"][j]) / w

    cache = {}

    def res(c, sig, cap, lat, fade):
        key = (c.i, sig[0], cap, lat, fade)
        if key not in cache:
            force = fade_time(c, sig[0] + lat[0], sig[1]) if fade else math.inf
            cache[key] = rk.trade(c, sig[0], cap * rk.FRAC / su, lat, force)
        return cache[key]

    def run(cfg, fade, k, cap, lat, part=None):
        tr = []
        for c in coins:
            if part == "A" and c.t0 >= half or part == "B" and c.t0 < half:
                continue
            sig = first_sig(c, cfg)
            if sig is None:
                continue
            r = res(c, sig, cap, lat, fade)
            if r is not None:
                tr.append((c.t0 + r[2], float(r[0][k]), c.t0 + float(r[1][k])))
        return tr

    rule = (300, 3.0, False, True, False)
    print("\n######## 1. ATURAN DIA (pra-daftar): volume 5 mnt >= 3x, dev <= 2%, bukan perug, ukuran 33%, "
          "TP +30% (2R), SL 15%, keluar saat volume pudar 60%, maks 30 mnt")
    for lat in ((1.0, 3.0), (3.0, 8.0)):
        for cap in CAPS:
            tr = run(rule, True, RULE_EXIT, cap, lat)
            print(rk.summ(f"jeda {lat[0]:.0f}-{lat[1]:.0f} dtk", tr, cap, 1))
        xs = np.array([x for _, x, _ in run(rule, True, RULE_EXIT, 200.0, lat)])
        if len(xs):
            print(f"      semua sinyal (tanpa batas 1 posisi): n={len(xs):,}, rata {xs.mean():.3f}x, "
                  f"median {np.median(xs):.3f}x, menang {np.mean(xs > 1):.0%}, rugi > 15%: {np.mean(xs < 0.85):.0%}")
    tr3 = run(rule, True, EXITS.index((0.45, 0.15, 1800.0)), 200.0, (1.0, 3.0))
    print(rk.summ("varian TP +45% (3R), jeda 1-3", tr3, 200.0))
    trb = run((300, 3.0, True, True, False), True, RULE_EXIT, 200.0, (1.0, 3.0))
    print(rk.summ("+ wajib breakout di atas high sebelumnya, jeda 1-3", trb, 200.0))
    print(f"   ({time.time() - t0:.0f} dtk)", flush=True)

    n_cfg = len(WINS) * len(MULTS) * 2 * 2 * 2 * 2
    print(f"\n######## 2. VARIASI: {n_cfg} filter x {len(EXITS)} cara jual, jeda 1-3 dtk, $200")
    rows = []
    for w in WINS:
        for mult in MULTS:
            for brk in (True, False):
                for devf in (True, False):
                    for holdf in (True, False):
                        for fade in (True, False):
                            cfg = (w, mult, brk, devf, holdf)
                            XA, XB = [], []
                            for c in coins:
                                sig = first_sig(c, cfg)
                                if sig is None:
                                    continue
                                r = res(c, sig, 200.0, (1.0, 3.0), fade)
                                if r is not None:
                                    (XA if c.t0 < half else XB).append(r[0])
                            XA = np.array(XA) if XA else np.zeros((0, len(EXITS)))
                            XB = np.array(XB) if XB else np.zeros((0, len(EXITS)))
                            for k in range(len(EXITS)):
                                rows.append(((cfg, fade), k, len(XA), XA[:, k].mean() if len(XA) else np.nan,
                                             len(XB), XB[:, k].mean() if len(XB) else np.nan))
    ok = [r for r in rows if r[2] >= 30 and r[4] >= 30]
    print(f"   {len(ok):,} strategi dengan >= 30 sinyal di A dan B. Untung di A: {sum(r[3] > 1 for r in ok):,}, "
          f"di B: {sum(r[5] > 1 for r in ok):,}, keduanya: {sum(r[3] > 1 and r[5] > 1 for r in ok):,}. "
          f"({time.time() - t0:.0f} dtk)")

    def cdesc(cf_):
        (w, mult, brk, devf, holdf), fade = cf_
        return (f"volume {w}s >= {mult:.0f}x" + (", breakout" if brk else "") + (", dev<=2%" if devf else "") +
                (", holders>=100" if holdf else "") + (", keluar saat volume pudar" if fade else ""))

    def ename(k):
        tp, sl, tm = EXITS[k]
        return (f"TP +{tp:.0%}" if tp < math.inf else "tanpa TP") + (f", SL {sl:.0%}" if sl < 1 else ", tanpa SL") + \
            f", maks {tm / 60:.0f} mnt"

    best = sorted(ok, key=lambda r: -r[3])[:5]
    print("\n   5 TERBAIK DI A -> UJI SEKALI DI B (ukuran 33%, maks 1 posisi):")
    for cf_, k, na, ma, nb_, mb in best:
        print(f"\n   * {cdesc(cf_)} | {ename(k)} | A {ma:.3f}x (n={na}) -> B {mb:.3f}x (n={nb_})")
        for lat in ((1.0, 3.0), (3.0, 8.0)):
            for cap in CAPS:
                print(rk.summ(f"B jeda {lat[0]:.0f}-{lat[1]:.0f}", run(cf_[0], cf_[1], k, cap, lat, "B"), cap))
    print(f"\nSelesai {time.time() - t0:.0f} dtk. Paper saja.")


if __name__ == "__main__":
    main()

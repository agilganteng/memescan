"""Uji strategi koin SETELAH LULUS (PumpSwap), candle 15 menit sampai 10 hari (7 Nov 2026).

Aturan ditulis SEBELUM melihat hasil. Sumber aturan:
  Bevan (Pintu, Leon): swing koin umur 1-3 hari yang masih hidup, MC > $1M, target 2x, cut -30%.
  Bevan/Theresa: "di atas $1M MC = swing berhari-hari". "Cuan bungkus": tarik modal di 2x, sisa dibiarkan.
  Zav: exit CRT terbalik = jual saat low rentang candle sebelumnya jebol (1 jam / 4 jam).
  Insentos & host: beli dip koin bagus yang sudah besar; quick flip koin yang baru migrasi.
  Ide sendiri: momentum 24 jam, beli saat lulus.

DATA: daftar koin lulus dari RPC (sampel merata per hari sejak 10 Jun 2026, tanpa seleksi harga), candle 15 menit
GeckoTerminal (USD) sampai 1000 candle (~10,4 hari) setelah lulus. MC = harga x 1 miliar (supply pump.fun).
PEMBAGIAN: urut waktu lulus; PILIH = 60% pertama, UJI = 40% terakhir (sekali).
MASUK: di harga buka candle SESUDAH candle sinyal ditutup.
BIAYA: fee 1,25%/sisi + slippage 1%/sisi. Stop: kalau candle buka di bawah stop (gap) -> isi di harga buka;
  kalau tidak -> isi di stop x 0,97. Dalam satu candle kena SL dan TP sekaligus -> anggap SL dulu.
SINYAL (satu trade per koin per strategi, sinyal pertama):
  LULUS        : beli di candle pertama setelah lulus
  MC>=X        : candle pertama yang tutup dengan MC >= $300k / $1M / $3M (umur <= 7 hari)
  SWING        : umur 24-72 jam, MC >= $300k / $1M, tutup > high tertinggi 16 / 48 candle sebelumnya (breakout 4j/12j),
                 volume 24 jam >= $0 / $200k
  DIP          : puncak MC sejauh ini >= $1M / $5M, harga tutup <= 50% / 30% dari puncak, umur >= 6 jam
  MOMENTUM     : naik >= 100% / 300% dalam 24 jam, MC >= $300k
JUAL:
  X1 TP 2x SL 30% maks 3 hari | X2 TP 2x SL 30% maks 7 hari | X3 trailing 30% (aktif setelah +30%) SL 30% maks 7 hari |
  X4 CRT 4 jam (tutup < low 16 candle sebelumnya) SL 50% | X5 CRT 1 jam (4 candle) SL 50% | X6 tahan 24 jam |
  X7 tahan sampai data habis (~10 hari) | X8 TP +50% SL 20% maks 1 hari |
  X9 cuan bungkus: jual setengah di 2x, sisanya trailing 40%, SL 30% maks 7 hari
TAMBAHAN 8 Nov (ditulis sebelum data selesai diambil, dari video yang ditonton):
  LANTAI (Crash Trading): puncak >= $1M / $3M, harga <= 40% puncak, dan 24 / 48 jam terakhir "flored out"
                 (high/low rentang <= 1,6x), beli. = pola run-up -> layu -> double bottom.
  X10 baca candle (Zaf): jual saat bearish engulfing (candle merah menelan badan candle hijau sebelumnya), SL 50%.
  X11 = X10 tapi candle merah >= 10%.  X12 Maurits: jual 50% di 2x, sisa trailing 30%, SL 25%, maks 1 hari.
  X13 Ros: tarik modal di 2x, sisa moonbag sampai data habis (tanpa SL).
  LP (ide sendiri): jadi penyedia likuiditas di pool PumpSwap. Nilai posisi = sqrt(harga akhir/awal) + fee,
     fee per candle = 0,20% x volume / TVL saat setor, TVL = 2 x 0,207 x sqrt(MC_lulus x MC_setor) (pool constant
     product tanpa LP lain, bagian kita tetap). Fee LP diuji 0,20% dan 0,02% (aturan fee PumpSwap berubah-ubah). Ini BATAS ATAS (LP lain ikut menambah likuiditas -> fee kita lebih kecil; harga dalam USD).
MODAL: $100/$200/$1000, 2%/trade (maks 20 posisi) dan 10%/trade (maks 5).
BATAS: GeckoTerminal gratis hanya ~180 hari ke belakang, jadi Jan - awal Jun 2026 TIDAK bisa diuji. Koin tanpa trade
  (mati) tidak punya candle -> jual di candle terakhir yang ada (bisa sedikit optimistis untuk koin yang benar-benar mati).

Pakai: python3 riset/swing.py --dir data/swing
"""
import argparse
import glob
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

FEE, SLIP = 0.0125, 0.01
SUP = 1e9
CAPS = (100.0, 200.0, 1000.0)
H = 4          # candle per jam
EXITS = {
    "X1 TP2x SL30% 3h": dict(tp=2.0, sl=0.3, T=3 * 24 * H),
    "X2 TP2x SL30% 7h": dict(tp=2.0, sl=0.3, T=7 * 24 * H),
    "X3 trail30% SL30% 7h": dict(sl=0.3, trail=0.3, arm=0.3, T=7 * 24 * H),
    "X4 CRT 4jam SL50%": dict(sl=0.5, crt=16, T=10 ** 6),
    "X5 CRT 1jam SL50%": dict(sl=0.5, crt=4, T=10 ** 6),
    "X6 tahan 24jam": dict(T=24 * H),
    "X7 tahan ~10hari": dict(T=10 ** 6),
    "X8 TP+50% SL20% 1h": dict(tp=1.5, sl=0.2, T=24 * H),
    "X9 cuan bungkus": dict(half=2.0, sl=0.3, trail=0.4, arm=1.0, T=7 * 24 * H),
    "X10 baca candle (Zaf)": dict(sl=0.5, engulf=0.0, T=7 * 24 * H),
    "X11 baca candle besar": dict(sl=0.5, engulf=0.10, T=7 * 24 * H),
    "X12 Maurits 50%@2x SL25%": dict(half=2.0, sl=0.25, trail=0.3, arm=1.0, T=24 * H),
    "X13 Ros modal@2x moonbag": dict(half=2.0, T=10 ** 6),
}
LP_FEE = 0.002      # bagian fee untuk LP di PumpSwap (0,20% volume) -- optimistis
LP_R0 = 0.207       # porsi supply token di pool saat lulus (~206,9 jt dari 1 miliar)
LP_COST = 1 - 0.5 * (0.0025 + 0.01)   # setengah modal di-swap ke token (fee DEX + slippage), tiap sisi
LP_HOLD = {"LP tahan 1h": 24 * H, "LP tahan 3h": 3 * 24 * H, "LP tahan 7h": 7 * 24 * H, "LP tahan ~10h": 10 ** 6}
EXN = list(EXITS)


def load(d):
    coins = []
    for fn in sorted(glob.glob(os.path.join(d, "shard*.json"))):
        for x in json.load(open(fn)):
            c = x.get("c") or []
            c = [r for r in c if r[0] >= x["t"] - 900]
            if len(c) < 2:
                continue
            a = np.array(c, dtype=float)
            coins.append({"mint": x["mint"], "t": x["t"], "ts": a[:, 0], "o": a[:, 1] * SUP, "h": a[:, 2] * SUP,
                          "l": a[:, 3] * SUP, "c": a[:, 4] * SUP, "v": a[:, 5]})
    coins.sort(key=lambda k: k["t"])
    return coins


def signals(k):
    """Return dict nama sinyal -> indeks candle sinyal (masuk di candle berikutnya)."""
    ts, h, l, c, v, t0 = k["ts"], k["h"], k["l"], k["c"], k["v"], k["t"]
    n = len(c)
    age = (ts + 900 - t0) / 3600.0
    out = {"LULUS": -1}
    for x in (3e5, 1e6, 3e6):
        i = np.where((c >= x) & (age <= 168))[0]
        if len(i):
            out[f"MC>={x / 1e6:g}M"] = int(i[0])
    vol24 = np.convolve(v, np.ones(96), "full")[:n]
    for x in (3e5, 1e6):
        for L in (16, 48):
            hh = np.array([h[max(0, i - L):i].max() if i > 0 else np.inf for i in range(n)])
            for vmin in (0, 2e5):
                m = (age >= 24) & (age <= 72) & (c >= x) & (c > hh) & (vol24 >= vmin)
                i = np.where(m)[0]
                if len(i):
                    out[f"SWING mc>={x / 1e6:g}M bo{L // 4}j vol>={vmin / 1e3:g}k"] = int(i[0])
    peak = np.maximum.accumulate(h)
    for p in (1e6, 5e6):
        for keep in (0.5, 0.3):
            m = (peak >= p) & (c <= keep * peak) & (age >= 6)
            i = np.where(m)[0]
            if len(i):
                out[f"DIP puncak>={p / 1e6:g}M sisa<={keep:.0%}"] = int(i[0])
    for p in (1e6, 3e6):
        for W in (96, 192):
            fl = np.array([(h[i - W + 1:i + 1].max() / max(l[i - W + 1:i + 1].min(), 1e-9)) if i >= W - 1 else np.inf
                           for i in range(n)])
            m = (peak >= p) & (c <= 0.4 * peak) & (fl <= 1.6)
            i = np.where(m)[0]
            if len(i):
                out[f"LANTAI puncak>={p / 1e6:g}M {W // 4}j"] = int(i[0])
    for g in (2.0, 4.0):
        prev = np.array([c[max(0, i - 96)] for i in range(n)])
        m = (c >= g * prev) & (c >= 3e5) & (np.arange(n) >= 4)
        i = np.where(m)[0]
        if len(i):
            out[f"MOMENTUM +{(g - 1):.0%} 24j"] = int(i[0])
    return out


def trade(k, si, cfg):
    """Masuk di open candle si+1. Return (multiple setelah biaya, umur jam masuk, jam keluar relatif) atau None."""
    o, h, l, c = k["o"], k["h"], k["l"], k["c"]
    n = len(c)
    e = si + 1
    if e >= n:
        return None
    p_in = o[e] if o[e] > 0 else c[e]
    if p_in <= 0:
        return None
    sl = p_in * (1 - cfg["sl"]) if cfg.get("sl") else -1.0
    tp = p_in * cfg["tp"] if cfg.get("tp") else math.inf
    half = p_in * cfg["half"] if cfg.get("half") else None
    T = cfg["T"]
    peak, armed, got_half = p_in, False, None
    p_out, j_out = None, None
    for j in range(e, n):
        stop = sl
        if cfg.get("trail") and armed:
            stop = max(stop, peak * (1 - cfg["trail"]))
        if l[j] <= stop:
            p_out = o[j] if o[j] < stop else stop * 0.97
            j_out = j
            break
        if half is not None and got_half is None and h[j] >= half:
            got_half = max(half, o[j])
        if h[j] >= tp:
            p_out, j_out = max(tp, o[j]), j
            break
        if cfg.get("crt") and j - cfg["crt"] >= e and c[j] < l[j - cfg["crt"]:j].min():
            p_out, j_out = (o[j + 1] if j + 1 < n else c[j]), j
            break
        if cfg.get("engulf") is not None and j > e and c[j] < o[j] and c[j - 1] > o[j - 1] \
                and o[j] >= c[j - 1] and c[j] <= o[j - 1] and (o[j] - c[j]) / o[j] >= cfg["engulf"]:
            p_out, j_out = (o[j + 1] if j + 1 < n else c[j]), j
            break
        if j - e + 1 >= T:
            p_out, j_out = c[j], j
            break
        peak = max(peak, h[j])
        if cfg.get("trail"):
            armed = armed or peak >= p_in * (1 + cfg["arm"])
    if p_out is None:
        p_out, j_out = c[n - 1], n - 1
    cost = (1 - FEE) * (1 - SLIP)
    x = p_out * cost / (p_in / cost)
    if got_half is not None:
        x = 0.5 * (got_half * cost / (p_in / cost)) + 0.5 * x
    return x, k["ts"][e], k["ts"][j_out] + 900


def lp_trade(k, si, T, lpfee=LP_FEE):
    """Setor likuiditas di open candle si+1, tarik setelah T candle. Return (multiple, t masuk, t keluar)."""
    o, c, v = k["o"], k["c"], k["v"]
    n = len(c)
    e = si + 1
    if e >= n or o[e] <= 0 or o[0] <= 0:
        return None
    tvl_e = 2 * LP_R0 * math.sqrt(o[0] * o[e])     # TVL saat setor (tanpa LP lain); bagian kita tetap
    fee = 0.0
    j = e
    for j in range(e, min(n, e + T)):
        fee += lpfee * v[j] / max(tvl_e, 1.0)      # fee dibayar ke kita, dinilai saat itu (tidak ikut IL)
    x = (math.sqrt(max(c[j], 0.0) / o[e]) + fee) * LP_COST * LP_COST
    return x, k["ts"][e], k["ts"][j] + 900


def sim(tr, cap, frac, mp):
    eq, op = cap, []
    for t, x, tx in sorted(tr):
        st_ = []
        for te, s, xx in op:
            if te <= t:
                eq += s * xx
            else:
                st_.append((te, s, xx))
        op = st_
        tot = eq + sum(s for _, s, _ in op)
        if len(op) >= mp or tot <= 1:
            continue
        s = min(eq, tot * frac)
        if s <= 0.05:
            continue
        eq -= s
        op.append((tx, s, x))
    return eq + sum(s * xx for _, s, xx in op)


def line(label, tr):
    xs = np.array([x for _, x, _ in tr])
    if not len(xs):
        return f"   {label}: 0 trade"
    k = int((xs > 1).sum())
    lo, hi = ms.wilson(k, len(xs))
    wo = (xs.sum() - xs.max()) / max(1, len(xs) - 1)
    s = (f"   {label}: n={len(xs)}{' (<30!)' if len(xs) < 30 else ''} rata {xs.mean():.3f}x median {np.median(xs):.3f}x "
         f"menang {k / len(xs):.0%} [{lo:.0%}-{hi:.0%}] tanpa-terbaik {wo:.3f}x")
    for frac, mp, nm in ((0.02, 20, "2%"), (0.10, 5, "10%")):
        s += f"\n      modal {nm}/trade: " + "  ".join(f"${cap:.0f}->${sim(tr, cap, frac, mp):,.0f}" for cap in CAPS)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/swing")
    a = ap.parse_args()
    t0 = time.time()
    coins = load(a.dir)
    if not coins:
        print("tidak ada data")
        return
    cut = coins[int(len(coins) * 0.6)]["t"]
    ts = lambda t: time.strftime("%d/%m/%Y", time.gmtime(t))  # noqa: E731
    days = np.array([(k["ts"][-1] - k["t"]) / 86400 for k in coins])
    print(f"== {len(coins):,} koin lulus pump.fun dengan candle ({ts(coins[0]['t'])} - {ts(coins[-1]['t'])}), "
          f"PILIH < {ts(cut)} <= UJI. Median data per koin {np.median(days):.1f} hari.")
    peak = np.array([k["h"].max() for k in coins])
    print(f"   Puncak MC setelah lulus: median ${np.median(peak) / 1e3:,.0f}k; >= $1M {np.mean(peak >= 1e6):.0%}; "
          f">= $10M {np.mean(peak >= 1e7):.1%}; >= $100M {np.mean(peak >= 1e8):.2%}")
    res = {}
    for k in coins:
        part = "P" if k["t"] < cut else "U"
        for sname, si in signals(k).items():
            for ename, cfg in EXITS.items():
                r = trade(k, si, cfg)
                if r:
                    res.setdefault((sname, ename), {"P": [], "U": []})[part].append((r[1], r[0], r[2]))
    lpres = {}
    for k in coins:
        part = "P" if k["t"] < cut else "U"
        sg = signals(k)
        for sname in ("LULUS", "MC>=1M", "LANTAI puncak>=1M 24j"):
            if sname not in sg:
                continue
            for lname, T in LP_HOLD.items():
                for lf in (LP_FEE, 0.0002):
                    r = lp_trade(k, sg[sname], T, lf)
                    if r:
                        lpres.setdefault((sname, f"{lname} fee {lf:.2%}"), {"P": [], "U": []})[part].append(
                            (r[1], r[0], r[2]))
    rows = []
    for key, d in res.items():
        if len(d["P"]) >= 30:
            rows.append((float(np.mean([x for _, x, _ in d["P"]])), key))
    rows.sort(key=lambda r: -r[0])
    nP = sum(r[0] > 1 for r in rows)
    nPU = sum(r[0] > 1 and len(res[r[1]]["U"]) >= 30 and np.mean([x for _, x, _ in res[r[1]]["U"]]) > 1 for r in rows)
    nU = sum(len(res[r[1]]["U"]) >= 30 and np.mean([x for _, x, _ in res[r[1]]["U"]]) > 1 for r in rows)
    print(f"   {len(rows)} strategi (>= 30 trade di PILIH); untung di PILIH: {nP}; untung di UJI: {nU}; di KEDUANYA: {nPU}. "
          f"({time.time() - t0:.0f} dtk)")
    print("\n## TABEL SEMUA STRATEGI (rata per trade PILIH -> UJI, n)")
    for xp, key in rows:
        u = res[key]["U"]
        xu = np.mean([x for _, x, _ in u]) if u else float("nan")
        print(f"   {key[0]:42s} {key[1]:22s} {xp:.3f}x n={len(res[key]['P']):4d} -> {xu:.3f}x n={len(u)}")
    print("\n## 10 TERBAIK DI PILIH, DIUJI SEKALI:")
    for xp, key in rows[:10]:
        print(f"  * [{key[0]} | {key[1]}] PILIH {xp:.3f}x n={len(res[key]['P'])}")
        print(line("UJI", res[key]["U"]))
    print("\n## Aturan persis dari video (tanpa pilih-pilih):")
    for key in (("SWING mc>=1M bo12j vol>=0k", "X1 TP2x SL30% 3h"), ("MC>=1M", "X2 TP2x SL30% 7h"),
                ("MC>=1M", "X9 cuan bungkus"), ("MC>=1M", "X4 CRT 4jam SL50%"), ("LULUS", "X8 TP+50% SL20% 1h"),
                ("DIP puncak>=5M sisa<=30%", "X8 TP+50% SL20% 1h"), ("LANTAI puncak>=1M 48j", "X7 tahan ~10hari"),
                ("LANTAI puncak>=3M 48j", "X7 tahan ~10hari"), ("MC>=1M", "X10 baca candle (Zaf)"),
                ("LULUS", "X12 Maurits 50%@2x SL25%"), ("LULUS", "X13 Ros modal@2x moonbag")):
        if key in res:
            print(f"  * {key[0]} | {key[1]}")
            print(line("PILIH+UJI", res[key]["P"] + res[key]["U"]))
    print("\n## LP (penyedia likuiditas PumpSwap, BATAS ATAS fee) PILIH -> UJI:")
    for key, d in lpres.items():
        xp = np.mean([x for _, x, _ in d["P"]]) if d["P"] else float("nan")
        print(f"  * {key[0]} | {key[1]}: PILIH {xp:.3f}x n={len(d['P'])}")
        print(line("UJI", d["U"]))
    print(f"\nSelesai {time.time() - t0:.0f} dtk. Paper saja, tidak ada transaksi.")


if __name__ == "__main__":
    main()

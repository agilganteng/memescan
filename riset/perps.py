"""Trading LEVERAGE memecoin perps di Hyperliquid: untung atau tidak? (28 Okt 2026)

Data   : candle 1 jam dari API publik Hyperliquid (tanpa key), 1 Jan 2026 - sekarang, + histori funding.
Koin   : memecoin perps yang tersedia (WIF, kPEPE, POPCAT, FARTCOIN, kBONK, PENGU, TRUMP, ...).
Strategi (ditulis sebelum lihat hasil):
  tren   : MA cepat/lambat (10/50, 20/100, 50/200), long kalau cepat > lambat, short kalau sebaliknya
  breakout: Donchian N (20/55/100 jam) masuk saat tembus, keluar di kebalikan N/2
  revert : RSI14 < 25 long / > 75 short, keluar saat RSI kembali ke 50
  + tiap strategi versi long-only, dan pembanding buy & hold.
Leverage 1/2/3/5/10x. Biaya taker 0,045% + slippage 0,05% per sisi dari nilai posisi, funding per jam,
likuidasi kalau harga bergerak melawan >= 90% dari 1/leverage dalam satu candle (pakai high/low) -> margin hilang.
Pilih (strategi, parameter, leverage) di TRAIN = Jan-Jun 2026 (rata hasil semua koin), uji SEKALI di TEST = Jul-sekarang.
Simulasi $200: modal dibagi rata ke semua koin, tiap koin dijalankan sendiri, lalu dijumlah.

Pakai: python3 riset/perps.py
"""
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

API = "https://api.hyperliquid.xyz/info"
START = int(time.mktime(time.strptime("2026-01-01", "%Y-%m-%d"))) * 1000
SPLIT = int(time.mktime(time.strptime("2026-07-01", "%Y-%m-%d"))) * 1000
WANT = ["WIF", "kPEPE", "POPCAT", "FARTCOIN", "kBONK", "PENGU", "TRUMP", "MEW", "PNUT", "GOAT", "MOODENG", "SPX",
        "PUMP", "kSHIB", "DOGE", "kFLOKI", "BRETT", "MOG", "TURBO", "AI16Z", "CHILLGUY", "kNEIRO", "MELANIA", "VINE"]
FEE = 0.00045 + 0.0005
LEVS = (1, 2, 3, 5, 10)
CAP = 200.0


def post(body):
    for a in range(6):
        try:
            req = urllib.request.Request(API, json.dumps(body).encode(), {"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            time.sleep(2 ** a)
            err = e
    raise RuntimeError(f"API gagal: {err}")


def candles(coin, now):
    out, t = [], START
    while t < now:
        d = post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "1h", "startTime": t, "endTime": now}})
        if not d:
            break
        out += d
        nt = d[-1]["t"] + 3600_000
        if nt <= t or len(d) < 10:
            break
        t = nt
    seen, rows = set(), []
    for c in out:
        if c["t"] in seen:
            continue
        seen.add(c["t"])
        rows.append((c["t"], float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])))
    rows.sort()
    return np.array(rows) if rows else None


def funding(coin, now, ts):
    out, t = [], START
    while t < now:
        d = post({"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": now})
        if not d:
            break
        out += d
        nt = d[-1]["time"] + 1
        if nt <= t or len(d) < 10:
            break
        t = nt
    f = np.zeros(len(ts))
    if out:
        ft = np.array([x["time"] for x in out], dtype=float)
        fr = np.array([float(x["fundingRate"]) for x in out])
        idx = np.searchsorted(ts, ft, side="right") - 1
        ok = idx >= 0
        np.add.at(f, idx[ok], fr[ok])
    return f


# ---------------------------------------------------------------- sinyal: posisi target -1/0/+1 di akhir tiap candle
def ma(x, n):
    c = np.cumsum(np.insert(x, 0, 0.0))
    out = np.full(len(x), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def rsi(x, n=14):
    d = np.diff(x, prepend=x[0])
    up, dn = np.maximum(d, 0), np.maximum(-d, 0)
    au, ad = np.zeros(len(x)), np.zeros(len(x))
    for i in range(1, len(x)):
        au[i] = (au[i - 1] * (n - 1) + up[i]) / n
        ad[i] = (ad[i - 1] * (n - 1) + dn[i]) / n
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-12))


def sig_ma(h, l, c, f, s):
    a, b = ma(c, f), ma(c, s)
    p = np.where(a > b, 1.0, -1.0)
    p[np.isnan(b)] = 0
    return p


def sig_donch(h, l, c, n):
    m = n // 2
    p = np.zeros(len(c))
    cur = 0.0
    for i in range(n, len(c)):
        hh, ll = h[i - n:i].max(), l[i - n:i].min()
        xh, xl = h[i - m:i].max(), l[i - m:i].min()
        if c[i] > hh:
            cur = 1.0
        elif c[i] < ll:
            cur = -1.0
        elif cur > 0 and c[i] < xl:
            cur = 0.0
        elif cur < 0 and c[i] > xh:
            cur = 0.0
        p[i] = cur
    return p


def sig_rsi(h, l, c, lo, hi):
    r = rsi(c)
    p = np.zeros(len(c))
    cur = 0.0
    for i in range(15, len(c)):
        if cur == 0 and r[i] < lo:
            cur = 1.0
        elif cur == 0 and r[i] > hi:
            cur = -1.0
        elif cur > 0 and r[i] >= 50:
            cur = 0.0
        elif cur < 0 and r[i] <= 50:
            cur = 0.0
        p[i] = cur
    return p


STRATS = {}
for f_, s_ in ((10, 50), (20, 100), (50, 200)):
    STRATS[f"tren MA{f_}/{s_}"] = (lambda f_, s_: lambda h, l, c: sig_ma(h, l, c, f_, s_))(f_, s_)
for n_ in (20, 55, 100):
    STRATS[f"breakout {n_}j"] = (lambda n_: lambda h, l, c: sig_donch(h, l, c, n_))(n_)
for lo_, hi_ in ((25, 75), (20, 80)):
    STRATS[f"revert RSI {lo_}/{hi_}"] = (lambda lo_, hi_: lambda h, l, c: sig_rsi(h, l, c, lo_, hi_))(lo_, hi_)
for k in list(STRATS):
    STRATS[k + " (long saja)"] = (lambda g: lambda h, l, c: np.maximum(g(h, l, c), 0))(STRATS[k])
STRATS["buy & hold"] = lambda h, l, c: np.ones(len(c))


def run(o, h, l, c, fr, pos, lev, cap):
    """Simulasi satu koin. pos[i] = posisi target yang diputuskan di close candle i, dieksekusi di open candle i+1.
    Return equity per candle, jumlah trade, jumlah likuidasi."""
    n = len(c)
    eq = np.full(n, cap)
    e, cur, entry, ntr, nliq = cap, 0.0, 0.0, 0, 0
    notional = 0.0
    for i in range(1, n):
        tgt = pos[i - 1]
        if e <= 1e-6:
            eq[i:] = 0.0
            break
        if tgt != cur:
            if cur != 0:
                e += notional * cur * (o[i] / entry - 1) - notional * FEE
                ntr += 1
            cur = tgt
            if cur != 0:
                notional = e * lev
                entry = o[i]
                e -= notional * FEE
        if cur != 0:
            adverse = (l[i] / entry - 1) if cur > 0 else (h[i] / entry - 1) * -1
            if adverse <= -0.9 / lev:
                e -= notional / lev          # margin habis
                e = max(e, 0.0)
                nliq += 1
                cur = 0.0
                eq[i] = e
                continue
            e -= notional * cur * fr[i]      # funding: long bayar kalau rate positif
            eq[i] = e + notional * cur * (c[i] / entry - 1)
        else:
            eq[i] = e
    return eq, ntr, nliq


def main():
    t0 = time.time()
    now = int(time.time() * 1000)
    meta = post({"type": "meta"})
    uni = {u["name"]: u for u in meta["universe"]}
    coins = [k for k in WANT if k in uni and not uni[k].get("isDelisted")]
    print(f"== Hyperliquid perps, candle 1 jam {time.strftime('%d/%m/%Y', time.gmtime(START / 1000))} - "
          f"{time.strftime('%d/%m/%Y', time.gmtime(now / 1000))}. TRAIN Jan-Jun, TEST Jul-sekarang.")
    print(f"   Biaya {FEE:.3%} per sisi (taker+slippage) + funding; likuidasi ~{0.9:.0%}/leverage. "
          f"Koin: {', '.join(coins)}")
    data = {}
    for k in coins:
        a = candles(k, now)
        if a is None or len(a) < 500:
            print(f"   {k}: data kurang, dilewati")
            continue
        fr = funding(k, now, a[:, 0])
        data[k] = (a, fr)
        print(f"   {k}: {len(a)} candle mulai {time.strftime('%d/%m', time.gmtime(a[0, 0] / 1000))}, "
              f"harga {a[0, 1]:.6g} -> {a[-1, 4]:.6g} ({a[-1, 4] / a[0, 1] - 1:+.0%}), funding rata/jam {fr.mean():+.5%}")
    if not data:
        print("Tidak ada data.")
        return
    # hitung semua hasil per (strategi, lev) per koin, pisah train & test (modal 1 tiap periode)
    res = {}
    for name, fn in STRATS.items():
        for k, (a, fr) in data.items():
            ts, o, h, l, c = a.T
            pos = fn(h, l, c)
            for part, msk in (("train", ts < SPLIT), ("test", ts >= SPLIT)):
                idx = np.where(msk)[0]
                if len(idx) < 200:
                    continue
                for lev in LEVS:
                    eq, ntr, nliq = run(o[idx], h[idx], l[idx], c[idx], fr[idx], pos[idx], lev, 1.0)
                    mdd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
                    res.setdefault((name, lev, part), {})[k] = (eq[-1], ntr, nliq, mdd)
    print("\n==== HASIL PER STRATEGI x LEVERAGE (gabungan semua koin, modal dibagi rata; 1,00 = impas)")
    print(f"   {'strategi':36s} {'lev':>3s} | {'TRAIN akhir':>11s} {'koin untung':>11s} {'likuidasi':>9s} | "
          f"{'TEST akhir':>10s} {'koin untung':>11s} {'likuidasi':>9s} {'trade':>6s}")
    rows = []
    for name in STRATS:
        for lev in LEVS:
            tr, te = res.get((name, lev, "train"), {}), res.get((name, lev, "test"), {})
            if not tr or not te:
                continue
            agr = np.mean([v[0] for v in tr.values()])
            age = np.mean([v[0] for v in te.values()])
            rows.append((agr, name, lev, age))
            print(f"   {name:36s} {lev:3d} | {agr:11.3f} {sum(v[0] > 1 for v in tr.values()):5d}/{len(tr):<5d} "
                  f"{sum(v[2] for v in tr.values()):9d} | {age:10.3f} {sum(v[0] > 1 for v in te.values()):5d}/{len(te):<5d} "
                  f"{sum(v[2] for v in te.values()):9d} {sum(v[1] for v in te.values()):6d}")
    rows.sort(reverse=True)
    print("\n==== PILIHAN DARI TRAIN (3 terbaik), diuji SEKALI di TEST, simulasi $200 (dibagi rata ke semua koin)")
    for agr, name, lev, age in rows[:3]:
        te = res[(name, lev, "test")]
        fin = CAP * np.mean([v[0] for v in te.values()])
        worst = max(v[3] for v in te.values())
        print(f"   {name} {lev}x | TRAIN {agr:.3f}x -> TEST {age:.3f}x | $200 -> ${fin:,.2f} | koin untung "
              f"{sum(v[0] > 1 for v in te.values())}/{len(te)}, likuidasi {sum(v[2] for v in te.values())}, "
              f"trade {sum(v[1] for v in te.values())}, MDD terburuk per koin {worst:.0%}")
    bh = res.get(("buy & hold", 1, "test"), {})
    if bh:
        print(f"   Pembanding buy & hold 1x di TEST: $200 -> ${CAP * np.mean([v[0] for v in bh.values()]):,.2f}")
    # pengaruh leverage: rata semua strategi
    print("\n==== PENGARUH LEVERAGE (rata semua strategi, TEST)")
    for lev in LEVS:
        vals = [np.mean([v[0] for v in res[(n, lev, 'test')].values()]) for n in STRATS if (n, lev, "test") in res]
        liq = sum(sum(v[2] for v in res[(n, lev, 'test')].values()) for n in STRATS if (n, lev, "test") in res)
        print(f"   {lev:2d}x: median akhir {np.median(vals):.3f}, strategi yang untung {sum(x > 1 for x in vals)}/{len(vals)}, "
              f"total likuidasi {liq}")
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk.")


if __name__ == "__main__":
    main()

"""Uji ketahanan "RSI 25/75 long saja" dari riset/perps.py (28 Okt 2026).

Aturan yang diuji (DIBEKUKAN, tidak diubah): candle 1 jam, RSI14 < 25 -> beli (long) di open candle berikutnya,
jual saat RSI14 >= 50. Tanpa short. Biaya 0,095% per sisi (taker+slippage) + funding.
Aturan ini dipilih di riset/perps.py pakai data Hyperliquid 3 Apr - 30 Jun 2026, jadi SEMUA data di luar periode itu
belum pernah dipakai untuk memilih (out-of-sample, termasuk mundur ke 2023-2025).

Data : arsip publik Binance USDT-M futures (data.binance.vision, tanpa key) candle 1 jam + funding, 2023 - sekarang.
       Kalau arsip Binance tidak bisa diambil, cadangan: Hyperliquid candle 4 jam (5000 terakhir).
Koin : memecoin + kelompok pembanding non-meme (BTC, ETH, SOL, ...).
Uji  : per trade (n, win% + Wilson CI, rata + CI bootstrap per hari), per tahun, per bulan, biaya 1x/2x/3x,
       pembanding beli di waktu ACAK dengan lama tahan yang sama (apakah RSI memberi timing atau cuma ikut pasar naik),
       variasi angka RSI (masuk 15-35, keluar 40-60), timeframe 4 jam, simulasi $200 leverage 1/2/3x per periode.

Pakai: python3 riset/perps2.py
"""
import concurrent.futures as cf
import csv
import io
import math
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import perps  # noqa: E402

BV = "https://data.binance.vision/data/futures/um"
MEME = {"WIF": "WIFUSDT", "PEPE": "1000PEPEUSDT", "POPCAT": "POPCATUSDT", "FARTCOIN": "FARTCOINUSDT",
        "BONK": "1000BONKUSDT", "PENGU": "PENGUUSDT", "TRUMP": "TRUMPUSDT", "PNUT": "PNUTUSDT", "GOAT": "GOATUSDT",
        "MOODENG": "MOODENGUSDT", "SPX": "SPXUSDT", "PUMP": "PUMPUSDT", "SHIB": "1000SHIBUSDT", "DOGE": "DOGEUSDT",
        "FLOKI": "1000FLOKIUSDT", "BRETT": "BRETTUSDT", "TURBO": "TURBOUSDT", "NEIRO": "NEIROUSDT", "MEW": "MEWUSDT",
        "MELANIA": "MELANIAUSDT", "BOME": "BOMEUSDT", "CHILLGUY": "CHILLGUYUSDT", "ACT": "ACTUSDT",
        "MEME": "MEMEUSDT", "PEOPLE": "PEOPLEUSDT", "CHEEMS": "1000CHEEMSUSDT"}
NONMEME = {k: k + "USDT" for k in ("BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "AVAX", "LINK", "LTC", "DOT", "SUI",
                                   "APT", "NEAR", "ARB", "OP", "INJ", "TIA", "AAVE", "UNI", "ATOM")}
HL_MEME = ["WIF", "kPEPE", "POPCAT", "FARTCOIN", "kBONK", "PENGU", "TRUMP", "PNUT", "GOAT", "MOODENG", "SPX", "PUMP",
           "kSHIB", "DOGE", "kFLOKI", "BRETT", "TURBO", "kNEIRO", "MELANIA", "MEW"]
HL_NON = list(NONMEME)
FIRST = (2023, 1)
FEE = perps.FEE
SEL_A = time.mktime(time.strptime("2026-04-01", "%Y-%m-%d")) * 1000   # periode yang dipakai memilih aturan
SEL_B = time.mktime(time.strptime("2026-07-01", "%Y-%m-%d")) * 1000
RULE = (14, 25, 50)
CAP = 200.0
rng = np.random.default_rng(11)


# ------------------------------------------------------------------ data
def get(url):
    for a in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** a)
        except Exception:  # noqa: BLE001
            time.sleep(2 ** a)
    return None


def rows_zip(b):
    if not b:
        return []
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        txt = z.read(z.namelist()[0]).decode()
    return [r for r in csv.reader(io.StringIO(txt)) if r and r[0][:1].isdigit()]


def months(now):
    y, m = FIRST
    ny, nm = time.gmtime(now).tm_year, time.gmtime(now).tm_mon
    out = []
    while (y, m) < (ny, nm):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def binance(sym, now):
    jobs = [f"{BV}/monthly/klines/{sym}/1h/{sym}-1h-{mo}.zip" for mo in months(now)]
    g = time.gmtime(now)
    for d in range(1, g.tm_mday):
        jobs.append(f"{BV}/daily/klines/{sym}/1h/{sym}-1h-{g.tm_year}-{g.tm_mon:02d}-{d:02d}.zip")
    fjobs = [f"{BV}/monthly/fundingRate/{sym}/{sym}-fundingRate-{mo}.zip" for mo in months(now)]
    with cf.ThreadPoolExecutor(16) as ex:
        kl = list(ex.map(lambda u: rows_zip(get(u)), jobs))
        fu = list(ex.map(lambda u: rows_zip(get(u)), fjobs))
    rows = {}
    for part in kl:
        for r in part:
            t = int(r[0])
            t = t // 1000 if t > 1e14 else t
            rows[t] = (t, float(r[1]), float(r[2]), float(r[3]), float(r[4]))
    if len(rows) < 2000:
        return None
    a = np.array(sorted(rows.values()))
    fr = np.zeros(len(a))
    ft, fv = [], []
    for part in fu:
        for r in part:
            t = int(r[0])
            ft.append(t // 1000 if t > 1e14 else t)
            fv.append(float(r[-1]))
    if ft:
        idx = np.searchsorted(a[:, 0], np.array(ft, float), side="right") - 1
        ok = (idx >= 0) & (idx < len(a))
        np.add.at(fr, idx[ok], np.array(fv)[ok])
    return a, fr


def hyperliquid4h(coin, now):
    perps.START = int(time.mktime(time.strptime("2023-01-01", "%Y-%m-%d"))) * 1000
    out, t = [], perps.START
    while t < now:
        d = perps.post({"type": "candleSnapshot", "req": {"coin": coin, "interval": "4h", "startTime": t, "endTime": now}})
        if not d:
            break
        out += d
        nt = d[-1]["t"] + 4 * 3600_000
        if nt <= t or len(d) < 10:
            break
        t = nt
    rows = sorted({c["t"]: (c["t"], float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])) for c in out}.values())
    if len(rows) < 500:
        return None
    a = np.array(rows)
    return a, perps.funding(coin, now, a[:, 0])


def resample(a, fr, k):
    """1 jam -> k jam (blok mulai di jam UTC kelipatan k)."""
    blk = (a[:, 0] // (k * 3600_000)).astype(np.int64)
    cut = np.flatnonzero(np.diff(blk)) + 1
    starts = np.r_[0, cut]
    ends = np.r_[cut, len(a)]
    o = a[starts, 1]
    h = np.maximum.reduceat(a[:, 2], starts)
    l = np.minimum.reduceat(a[:, 3], starts)
    c = a[ends - 1, 4]
    f = np.add.reduceat(fr, starts)
    return np.c_[blk[starts] * k * 3600_000, o, h, l, c], f


# ------------------------------------------------------------------ strategi & trade
def sig(r, lo, ex):
    p = np.zeros(len(r))
    cur = 0.0
    for i in range(15, len(r)):
        if cur == 0 and r[i] < lo:
            cur = 1.0
        elif cur > 0 and r[i] >= ex:
            cur = 0.0
        p[i] = cur
    return p


def trades(ts, o, c, cfund, pos, feem=1.0):
    """pos diputuskan di close i, dieksekusi di open i+1. Return list (t_masuk, ret, lama, i_masuk, i_keluar)."""
    n = len(o)
    d = np.diff(np.r_[0.0, pos])
    ent = np.flatnonzero(d > 0) + 1
    ext = np.flatnonzero(d < 0) + 1
    out = []
    for e in ent:
        if e >= n:
            continue
        j = ext[np.searchsorted(ext, e)] if np.searchsorted(ext, e) < len(ext) else n
        if j < n:
            px = o[j]
        else:
            j, px = n - 1, c[-1]
        r = px / o[e] - 1 - 2 * FEE * feem - (cfund[j] - cfund[e])
        out.append((ts[e], r, j - e, e, j))
    return out


def rand_ctrl(o, c, cfund, tl, draws=50, win=2160):
    """Beli di waktu acak (+-90 hari dari trade asli, satuan candle 1 jam) dengan lama tahan sama."""
    n = len(o)
    res = []
    for x in tl:
        H, e = max(x[2], 1), x[3]
        lo, hi = max(0, e - win), min(n - 1 - H, e + win)
        if hi <= lo:
            continue
        s = rng.integers(lo, hi, draws)
        r = o[np.minimum(s + H, n - 1)] / o[s] - 1 - 2 * FEE - (cfund[np.minimum(s + H, n - 1)] - cfund[s])
        res.append(r.mean())
    return np.array(res)


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    m = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return m - h, m + h


def boot_day(t, r, it=1000):
    """CI 95% rata per trade, bootstrap per HARI masuk (trade di hari yang sama saling berkaitan)."""
    if len(r) < 2:
        return float("nan"), float("nan")
    day = (np.asarray(t) // 86_400_000).astype(np.int64)
    u, inv = np.unique(day, return_inverse=True)
    s = np.bincount(inv, weights=r)
    k = np.bincount(inv)
    m = []
    for _ in range(it):
        pick = rng.integers(0, len(u), len(u))
        m.append(s[pick].sum() / k[pick].sum())
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


def line(label, tl, ctrl=None):
    if not tl:
        return f"   {label:28s} n=0"
    t = np.array([x[0] for x in tl])
    r = np.array([x[1] for x in tl])
    k = int((r > 0).sum())
    wl, wh = wilson(k, len(r))
    bl, bh = boot_day(t, r)
    s = (f"   {label:28s} n={len(r):5d} win {k / len(r):5.1%} [{wl:.0%}-{wh:.0%}]  rata/trade {r.mean():+.3%} "
         f"[{bl:+.2%} .. {bh:+.2%}]  median {np.median(r):+.2%}  tahan {np.mean([x[2] for x in tl]):.0f} candle")
    if ctrl is not None and len(ctrl):
        s += f"  | acak sama lama {ctrl.mean():+.3%}"
    return s + ("  (<30 trade, jangan disimpulkan)" if len(r) < 30 else "")


def yr(t):
    return time.gmtime(t / 1000).tm_year


def mo(t):
    g = time.gmtime(t / 1000)
    return f"{g.tm_year}-{g.tm_mon:02d}"


def insel(t):
    return SEL_A <= t < SEL_B


# ------------------------------------------------------------------ simulasi $200
def sim(data, names, t_a, t_b, lev, feem=1.0, lo=25, ex=50, bh=False):
    """Modal $200 dibagi rata ke koin yang sudah ada datanya di awal periode (+30 hari). Return (akhir, likuidasi, MDD
    portofolio, koin dipakai)."""
    use = [k for k in names if data[k]["a"][0, 0] <= t_a + 30 * 86_400_000 and data[k]["a"][-1, 0] >= t_b - 7 * 86_400_000]
    if not use:
        return None
    old = perps.FEE
    perps.FEE = FEE * feem
    curves, liq = [], 0
    grid = np.arange(t_a, t_b, 3600_000.0 * 24)
    for k in use:
        d = data[k]
        a, fr = d["a"], d["fr"]
        m = (a[:, 0] >= t_a) & (a[:, 0] < t_b)
        if m.sum() < 50:
            continue
        ts, o, h, l, c = a[m].T
        pos = np.ones(m.sum()) if bh else d["pos"][(lo, ex)][m]
        eq, _, nl = perps.run(o, h, l, c, fr[m], pos, lev, CAP / len(use))
        liq += nl
        idx = np.clip(np.searchsorted(ts, grid, side="right") - 1, 0, len(eq) - 1)
        v = eq[idx]
        v[grid < ts[0]] = CAP / len(use)
        curves.append(v)
    perps.FEE = old
    tot = np.sum(curves, axis=0)
    mdd = float(np.max(1 - tot / np.maximum.accumulate(tot)))
    return float(tot[-1]), liq, mdd, len(use)


# ------------------------------------------------------------------ utama
def analyse(data, tf_h, title):
    print(f"\n######## {title}")
    meme = [k for k in data if data[k]["g"] == "meme"]
    non = [k for k in data if data[k]["g"] == "non"]
    los, exs = (15, 20, 25, 30, 35), (40, 45, 50, 55, 60)
    win = int(2160 / tf_h)
    for k, d in data.items():
        a = d["a"]
        d["cf"] = np.r_[0.0, np.cumsum(d["fr"])][1:]
        r = perps.rsi(a[:, 4])
        d["pos"] = {(lo, ex): sig(r, lo, ex) for lo in los for ex in exs}

    def tl_of(names, lo=25, ex=50, feem=1.0):
        out = []
        for k in names:
            d = data[k]
            ts, o, h, l, c = d["a"].T
            for x in trades(ts, o, c, d["cf"], d["pos"][(lo, ex)], feem):
                out.append(x + (k,))
        return out

    for gname, names in (("MEMECOIN", meme), ("NON-MEME (pembanding)", non)):
        if not names:
            continue
        tl = tl_of(names)
        ctrl = []
        for k in names:
            d = data[k]
            ts, o, h, l, c = d["a"].T
            sub = [x for x in tl if x[5] == k]
            ctrl.append(rand_ctrl(o, c, d["cf"], sub, win=win))
        ctrl = np.concatenate(ctrl) if ctrl else np.array([])
        ok = [not insel(x[0]) for x in tl]
        print(f"\n== {gname}: aturan RSI14 <25 beli, >=50 jual, long saja, 1x, biaya {FEE:.3%}/sisi + funding")
        print(line("SEMUA data", tl, ctrl))
        print(line("di luar periode pemilihan", [x for x, g in zip(tl, ok) if g], ctrl[np.array(ok)] if len(ctrl) == len(tl) else None))
        print(line("periode pemilihan Apr-Jun 26", [x for x, g in zip(tl, ok) if not g]))
        for y in sorted({yr(x[0]) for x in tl}):
            sel = [i for i, x in enumerate(tl) if yr(x[0]) == y]
            print(line(f"tahun {y}", [tl[i] for i in sel], ctrl[sel] if len(ctrl) == len(tl) else None))
        for fm in (2.0, 3.0):
            print(line(f"biaya {fm:.0f}x lipat (semua)", tl_of(names, feem=fm)))
        if gname == "MEMECOIN":
            print("\n   Per bulan (memecoin, 1x): n trade | rata/trade | win% | rata hasil per koin sebulan: strategi vs "
                  "beli-tahan")
            mret = {}
            for k in names:
                d = data[k]
                ts, o, h, l, c = d["a"].T
                eq, _, _ = perps.run(o, h, l, c, d["fr"], d["pos"][(25, 50)], 1, 1.0)
                lab = np.array([mo(t) for t in ts])
                cut = np.r_[0, np.flatnonzero(lab[1:] != lab[:-1]) + 1, len(ts)]
                for s_, e_ in zip(cut[:-1], cut[1:]):
                    a0 = eq[s_ - 1] if s_ > 0 else 1.0
                    p0 = c[s_ - 1] if s_ > 0 else o[s_]
                    mret.setdefault(lab[s_], []).append((eq[e_ - 1] / a0 - 1 if a0 > 0 else 0.0, c[e_ - 1] / p0 - 1))
            for m_ in sorted(mret):
                rr = np.array([x[1] for x in tl if mo(x[0]) == m_])
                sv = np.mean([x[0] for x in mret[m_]])
                bv = np.mean([x[1] for x in mret[m_]])
                print(f"   {m_}: {len(rr):4d} | {rr.mean() if len(rr) else 0:+7.2%} | "
                      f"{np.mean(rr > 0) if len(rr) else 0:5.0%} | {sv:+7.1%} vs {bv:+7.1%} ({len(mret[m_])} koin)"
                      f"{'  <- periode pemilihan' if m_ in ('2026-04', '2026-05', '2026-06') else ''}")
            print("\n   Variasi angka RSI (memecoin, semua data DI LUAR periode pemilihan): rata/trade (n)")
            print("   masuk\\keluar " + "".join(f"{e:>16d}" for e in exs))
            for lo in los:
                cells = []
                for ex in exs:
                    t2 = [x for x in tl_of(names, lo, ex) if not insel(x[0])]
                    rr = np.array([x[1] for x in t2]) if t2 else np.array([0.0])
                    cells.append(f"{rr.mean():+8.2%} ({len(t2):5d})")
                print(f"   RSI <{lo:<2d}       " + "".join(f"{c:>16s}" for c in cells))

    # simulasi $200
    now = max(data[k]["a"][-1, 0] for k in data)
    per = []
    for y in (2023, 2024, 2025):
        per.append((f"{y}", time.mktime(time.strptime(f"{y}-01-01", "%Y-%m-%d")) * 1000,
                    time.mktime(time.strptime(f"{y + 1}-01-01", "%Y-%m-%d")) * 1000))
    per.append(("Jan 2026-sekarang", time.mktime(time.strptime("2026-01-01", "%Y-%m-%d")) * 1000, now))
    per.append(("Jul 2026-sekarang", SEL_B, now))
    print("\n== Simulasi $200 (modal dibagi rata ke koin yang sudah ada di awal periode), akhir $ | likuidasi | MDD")
    for gname, names in (("memecoin", meme), ("non-meme", non)):
        for pn, a_, b_ in per:
            s_bh = sim(data, names, a_, b_, 1, bh=True)
            if not s_bh:
                continue
            cells = []
            for lev in (1, 2, 3):
                s = sim(data, names, a_, b_, lev)
                cells.append(f"{lev}x ${s[0]:8,.2f} liq {s[1]:2d} MDD {s[2]:4.0%}")
            s2 = sim(data, names, a_, b_, 1, feem=2.0)
            print(f"   {gname:9s} {pn:18s} ({s_bh[3]:2d} koin): " + " | ".join(cells) +
                  f" | 1x biaya 2x ${s2[0]:,.2f} | beli-tahan 1x ${s_bh[0]:,.2f}")


def main():
    t0 = time.time()
    now = time.time()
    print(f"== Ambil arsip Binance futures 1 jam {FIRST[0]}-{FIRST[1]:02d} .. {time.strftime('%d/%m/%Y', time.gmtime(now))}")
    data = {}
    for grp, mp in (("meme", MEME), ("non", NONMEME)):
        for k, sym in mp.items():
            x = binance(sym, now)
            if x is None:
                print(f"   {k} ({sym}): tidak ada / kurang data")
                continue
            a, fr = x
            data[k] = {"g": grp, "a": a, "fr": fr}
            print(f"   {k:9s} {len(a):6d} candle {time.strftime('%d/%m/%y', time.gmtime(a[0, 0] / 1000))}-"
                  f"{time.strftime('%d/%m/%y', time.gmtime(a[-1, 0] / 1000))}  harga {a[0, 1]:.5g} -> {a[-1, 4]:.5g} "
                  f"({a[-1, 4] / a[0, 1] - 1:+.0%})  funding rata/jam {fr.mean():+.5%}")
    print(f"   ({time.time() - t0:.0f} dtk)")
    if sum(d["g"] == "meme" for d in data.values()) >= 5:
        analyse(data, 1, "TIMEFRAME 1 JAM (aturan asli), arsip Binance")
        d4 = {}
        for k, d in data.items():
            a4, f4 = resample(d["a"], d["fr"], 4)
            d4[k] = {"g": d["g"], "a": a4, "fr": f4}
        analyse(d4, 4, "TIMEFRAME 4 JAM (aturan sama di candle 4 jam), arsip Binance")
    else:
        print("\n!! Arsip Binance gagal. Cadangan: Hyperliquid candle 4 jam.")
        hl = {}
        nowms = int(now * 1000)
        for grp, lst in (("meme", HL_MEME), ("non", HL_NON)):
            for k in lst:
                x = hyperliquid4h(k, nowms)
                if x is None:
                    continue
                hl[k] = {"g": grp, "a": x[0], "fr": x[1]}
                print(f"   {k}: {len(x[0])} candle 4j mulai {time.strftime('%d/%m/%y', time.gmtime(x[0][0, 0] / 1000))}")
        analyse(hl, 4, "TIMEFRAME 4 JAM, Hyperliquid")
    print(f"\nSelesai dalam {time.time() - t0:.0f} dtk.")


if __name__ == "__main__":
    main()

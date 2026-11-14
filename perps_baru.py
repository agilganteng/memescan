#!/usr/bin/env python3
"""perps_baru: dua keluarga strategi di luar pump.fun, data publik Binance USDT-M futures (data.binance.vision).

F1  SHORT koin yang baru listing di Binance futures. Alasan ekonomi: koin baru listing biasanya float kecil, FDV besar,
    jadwal unlock, hype memudar -> cenderung turun minggu-minggu setelah listing.
    Grid kecil: masuk hari ke 1/3/7/14 setelah candle pertama, tahan 7/14/30/60 hari, stop +30/+50/+100%/tanpa.
    Biaya 0,1%/sisi, funding dihitung (short MENERIMA funding positif, MEMBAYAR funding negatif).
    Stop dicek di high harian; isi stop = max(level stop, open hari itu) (gap ikut rugi).
    Pembanding: short koin yang sama tapi di umur acak 120-400 hari (apakah efek khusus listing?), dan long.
F2  Panen funding (delta-neutral: long spot + short perp, harga saling meniadakan). Masuk kalau funding rata 3 hari
    > ambang, keluar kalau < 0,005%/8 jam. Biaya 4 sisi x 0,1%. Selisih basis spot-perp TIDAK dihitung (batas atas).

Pembagian: listing / periode 2023-01..2024-12 = A (pilih), 2025-01..sekarang = B (uji sekali).
Simulasi saldo awal $100/$200/$500/$1000/$5000: tiap trade 10% saldo (maks 10% saldo awal, minimal order $5), urut waktu masuk, saldo dihitung per trade berurutan.

Pakai: python3 perps_baru.py --out out
"""
import argparse
import concurrent.futures as cf
import csv
import io
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
import zipfile

BV = "https://data.binance.vision/data/futures/um"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
FEE = 0.001
DAY = 86400
T_SPLIT = time.mktime(time.strptime("2025-01-01", "%Y-%m-%d")) - time.timezone
T_FIRST = time.mktime(time.strptime("2023-01-01", "%Y-%m-%d")) - time.timezone


def get(url, tries=4):
    for a in range(tries):
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
    try:
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            txt = z.read(z.namelist()[0]).decode()
    except zipfile.BadZipFile:
        return []
    return [r for r in csv.reader(io.StringIO(txt)) if r and r[0][:1].isdigit()]


def list_symbols():
    out, marker = [], ""
    while True:
        url = f"{S3}?prefix=data/futures/um/monthly/klines/&delimiter=/" + (f"&marker={marker}" if marker else "")
        b = get(url)
        if not b:
            break
        txt = b.decode()
        pre = re.findall(r"<Prefix>data/futures/um/monthly/klines/([^/<]+)/</Prefix>", txt)
        out += pre
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", txt)
        if "<IsTruncated>true</IsTruncated>" in txt and (nm or pre):
            marker = nm.group(1) if nm else f"data/futures/um/monthly/klines/{pre[-1]}/"
        else:
            break
    return sorted({s for s in out if s.endswith("USDT")})


def months(now):
    y, m = 2023, 1
    ny, nm = time.gmtime(now).tm_year, time.gmtime(now).tm_mon
    out = []
    while (y, m) < (ny, nm):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def ts(x):
    t = int(x)
    return t // 1000000 if t > 1e15 else t // 1000 if t > 1e12 else t


def load(sym, now):
    jobs = [f"{BV}/monthly/klines/{sym}/1d/{sym}-1d-{mo}.zip" for mo in months(now)]
    g = time.gmtime(now)
    jobs += [f"{BV}/daily/klines/{sym}/1d/{sym}-1d-{g.tm_year}-{g.tm_mon:02d}-{d:02d}.zip" for d in range(1, g.tm_mday)]
    days = {}
    for u in jobs:
        for r in rows_zip(get(u)):
            t = ts(r[0])
            days[t] = (t, float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[7]) if len(r) > 7 else 0.0)
    if len(days) < 20:
        return None
    k = sorted(days.values())
    fund = {}
    for mo in months(now):
        for r in rows_zip(get(f"{BV}/monthly/fundingRate/{sym}/{sym}-fundingRate-{mo}.zip")):
            t = ts(r[0])
            fund[t - t % DAY] = fund.get(t - t % DAY, 0.0) + float(r[-1])
    return {"sym": sym, "k": k, "f": [fund.get(x[0], 0.0) for x in k]}


def short_trade(d, i0, hold, stop):
    """Short dari open hari i0, tahan `hold` hari. Return (mult, t_masuk) atau None."""
    k, f = d["k"], d["f"]
    if i0 >= len(k):
        return None
    p0 = k[i0][1]
    if p0 <= 0:
        return None
    fsum = 0.0
    end = min(len(k) - 1, i0 + hold - 1)
    if i0 + hold - 1 > len(k) - 1 and k[-1][0] < time.time() - 3 * DAY:
        pass   # delisting: tutup di close terakhir
    elif i0 + hold - 1 > len(k) - 1:
        return None   # belum selesai
    for j in range(i0, end + 1):
        o, hi, cl = k[j][1], k[j][2], k[j][4]
        if stop is not None and hi >= p0 * (1 + stop):
            px = max(p0 * (1 + stop), o) * 1.002
            r = (p0 - px) / p0 + fsum
            return max(0.0, 1 + r - 2 * FEE), k[i0][0]
        fsum += f[j]
    r = (p0 - k[end][4]) / p0 + fsum
    return max(0.0, 1 + r - 2 * FEE), k[i0][0]


def stat(trades):
    trades = sorted(t for t in trades if t is not None)
    xs = [m for _, m in trades]
    n = len(xs)
    if not n:
        return {"n": 0}
    s = sorted(xs)
    sims = {}
    for S in (100.0, 200.0, 500.0, 1000.0, 5000.0):
        bal = S
        for x in xs:
            st = min(S / 10, bal * 0.10)
            if st < 5.0:            # minimal order Binance futures ~$5
                break
            bal += st * (x - 1)
        sims[f"${int(S)}"] = round(bal, 2)
    w = sum(x > 1 for x in xs)
    mean = sum(xs) / n
    sd = (sum((x - mean) ** 2 for x in xs) / max(1, n - 1)) ** 0.5
    return {"n": n, "mean": round(mean, 4), "median": round(s[n // 2], 4), "win": round(w / n, 3),
            "ci_lo": round(mean - 1.96 * sd / math.sqrt(n), 4), "mean_wo_best": round((sum(xs) - s[-1]) / (n - 1), 4)
            if n > 1 else None, "sim": sims}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--max", type=int, default=0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    T = time.time()
    syms = list_symbols()
    print(f"[simbol] {len(syms)} USDT-M ({time.time() - T:.0f}s)", flush=True)
    if a.max:
        syms = syms[:a.max]
    now = time.time()
    data = []
    with cf.ThreadPoolExecutor(24) as ex:
        for i, d in enumerate(ex.map(lambda s: load(s, now), syms)):
            if d:
                data.append(d)
            if i % 100 == 0:
                print(f"  {i}/{len(syms)} dimuat ({time.time() - T:.0f}s)", flush=True)
    new = [d for d in data if d["k"][0][0] > T_FIRST + 20 * DAY]
    print(f"[data] {len(data)} simbol punya candle; listing baru sejak 2023: {len(new)} "
          f"(A {sum(d['k'][0][0] < T_SPLIT for d in new)}, B {sum(d['k'][0][0] >= T_SPLIT for d in new)})", flush=True)

    # ---------------- F1
    grid = [(dl, h, st) for dl in (1, 3, 7, 14) for h in (7, 14, 30, 60) for st in (0.3, 0.5, 1.0, None)]
    res = []
    for dl, h, st in grid:
        A, B = [], []
        for d in new:
            t = short_trade(d, dl, h, st)
            if t is None:
                continue
            (A if d["k"][0][0] < T_SPLIT else B).append((t[1], t[0]))
        res.append({"masuk_hari": dl, "tahan": h, "stop": st, "A": stat(A), "B": stat(B)})
    res.sort(key=lambda r: -(r["A"].get("mean_wo_best") or 0))
    print("[F1 short listing baru] 64 varian. Top 10 dipilih di A (2023-2024), lalu B (2025-sekarang):", flush=True)
    for r in res[:10]:
        print(f"  masuk h{r['masuk_hari']} tahan {r['tahan']}h stop {r['stop']}: A {r['A']} | B {r['B']}", flush=True)
    okA = [r for r in res if r["A"].get("n", 0) >= 30 and (r["A"].get("mean_wo_best") or 0) > 1.0]
    okAB = [r for r in okA if (r["B"].get("mean_wo_best") or 0) > 1.0 and r["B"].get("n", 0) >= 30]
    print(f"[F1] untung di A: {len(okA)}/64; untung di A DAN B: {len(okAB)}", flush=True)
    pick = res[0]
    # pembanding: short koin baru yang sama di umur acak 120-400 hari, varian terpilih
    rnd = random.Random(5)
    ctl = {"A": [], "B": []}
    for d in new:
        if len(d["k"]) < 420:
            continue
        i0 = rnd.randint(120, min(400, len(d["k"]) - pick["tahan"] - 1))
        t = short_trade(d, i0, pick["tahan"], pick["stop"])
        if t:
            ctl["A" if d["k"][i0][0] < T_SPLIT else "B"].append((t[1], t[0]))
    print(f"[F1 kontrol umur acak 120-400 hari, varian terpilih] A {stat(ctl['A'])} | B {stat(ctl['B'])}", flush=True)
    # per tahun listing untuk varian terpilih
    by_y = {}
    for d in new:
        t = short_trade(d, pick["masuk_hari"], pick["tahan"], pick["stop"])
        if t:
            by_y.setdefault(time.gmtime(d["k"][0][0]).tm_year, []).append((t[1], t[0]))
    print("[F1 varian terpilih per tahun listing] " + " | ".join(f"{y}: {stat(v)}" for y, v in sorted(by_y.items())),
          flush=True)
    # leverage 2x untuk varian terpilih (kerugian 2x, likuidasi di -100%)
    lev = {"A": [], "B": []}
    for d in new:
        t = short_trade(d, pick["masuk_hari"], pick["tahan"], pick["stop"])
        if t:
            lev["A" if d["k"][0][0] < T_SPLIT else "B"].append((t[1], max(0.0, 1 + 2 * (t[0] - 1))))
    print(f"[F1 terpilih 2x] A {stat(lev['A'])} | B {stat(lev['B'])}", flush=True)

    # ---------------- F2 panen funding (batas atas, basis tidak dihitung)
    f2 = []
    for thr in (0.0003, 0.0005, 0.001):
        A, B = [], []
        for d in data:
            f, k = d["f"], d["k"]
            i, n = 3, len(k)
            while i < n:
                avg = sum(f[i - 3:i]) / 3 / 3      # per 8 jam (3x sehari)
                if avg > thr:
                    j, got = i, 0.0
                    while j < n and sum(f[j - 3:j]) / 9 > 0.00005:
                        got += f[j]
                        j += 1
                    m = 1 + got - 4 * FEE
                    (A if k[i][0] < T_SPLIT else B).append((k[i][0], m))
                    i = j + 1
                else:
                    i += 1
        f2.append({"ambang_per8j": thr, "A": stat(A), "B": stat(B)})
        print(f"[F2 funding > {thr * 100:.2f}%/8j] A {stat(A)} | B {stat(B)}", flush=True)
    out = {"simbol": len(data), "listing_baru": len(new), "F1": res, "F1_lolos_A": len(okA), "F1_lolos_AB": len(okAB),
           "F1_kontrol": {k: stat(v) for k, v in ctl.items()}, "F2": f2, "durasi_s": round(time.time() - T)}
    with open(os.path.join(a.out, "perps_baru.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"[selesai] {time.time() - T:.0f}s", flush=True)


if __name__ == "__main__":
    main()

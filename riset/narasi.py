"""Riset sniper narasi: apakah koin pump.fun yang namanya cocok dengan topik yang lagi rame
lebih untung daripada koin lain? Ide dari video "Grok Bot" (sniper yang scan X untuk narasi).

1. Cek sumber data tren mana yang bisa diakses gratis dari GitHub Actions (X, nitter,
   Wikipedia, Google Trends, Reddit, GDELT).
2. Tren harian = 1000 artikel Wikipedia (Inggris) paling banyak dibaca KEMARIN (jadi tidak
   bocor ke masa depan: koin hari D hanya dicocokkan dengan tren hari D-1). Wikipedia dipakai
   karena satu-satunya sumber gratis yang punya riwayat harian; ini pengganti kasar untuk X.
3. Koin "narasi" = simbol koin (huruf saja, >=3 huruf) sama dengan kata dari judul artikel
   tren, atau dengan judul utuh tanpa spasi (contoh TAYLORSWIFT).
4. Strategi = umur masuk x aturan jual, hanya untuk koin narasi. Dipilih di 70% data lama,
   diuji sekali di 30% data baru + simulasi $200, dibandingkan dengan beli semua koin.

Pakai: python3 riset/narasi.py --data data
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from array import array

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

AGES = (10, 30, 60, 120)
EXITS = ms.RES_EXITS
SIZE = 0.1
STAKE, START, STOP = 20.0, 200.0, 40.0
UA = {"User-Agent": "memescan-riset/1.0 (github.com/agilganteng/memescan)"}
STOP_WORDS = set("""the and for with from that this was were are his her their they them about after before
into over under than then when where which while who whom whose what also have has had not but its
list deaths film season series episode team world state states united city county league cup
women men national election war battle football club university school""".split())


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def probe():
    print("== CEK SUMBER DATA TREN (dari GitHub Actions)")
    srcs = [
        ("X API v2 (tanpa kunci)", "https://api.x.com/2/tweets/search/recent?query=pumpfun"),
        ("x.com", "https://x.com/explore"),
        ("nitter.net", "https://nitter.net/search?q=pumpfun"),
        ("xcancel.com", "https://xcancel.com/search?q=pumpfun"),
        ("Wikipedia top harian", "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/2026/10/20"),
        ("Google Trends RSS", "https://trends.google.com/trending/rss?geo=US"),
        ("Reddit r/all", "https://www.reddit.com/r/all/top.json?t=day&limit=5"),
        ("GDELT berita", "https://api.gdeltproject.org/api/v2/doc/doc?query=memecoin&mode=artlist&format=json&maxrecords=3"),
    ]
    ok = {}
    for name, url in srcs:
        try:
            code, body = get(url)
            note = f"{len(body)} byte"
        except urllib.error.HTTPError as e:
            code, note = e.code, e.reason
        except Exception as e:   # noqa: BLE001
            code, note = 0, type(e).__name__
        ok[name] = code == 200
        print(f"  {name:<24} HTTP {code} ({note})")
    return ok


def wiki_terms(day):
    """Kata dan judul dari 1000 artikel Wikipedia teratas di hari itu."""
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/"
           f"{day.year}/{day.month:02d}/{day.day:02d}")
    for _ in range(3):
        try:
            _, body = get(url)
            arts = json.loads(body)["items"][0]["articles"]
            break
        except Exception:   # noqa: BLE001
            time.sleep(3)
    else:
        return None
    words, titles = set(), set()
    for a in arts:
        t = a["article"]
        if ":" in t or t in ("Main_Page",):
            continue
        t = urllib.parse.unquote(t)
        titles.add(re.sub(r"[^a-z]", "", t.lower()))
        for w in re.split(r"[^A-Za-z]+", t):
            w = w.lower()
            if len(w) >= 3 and w not in STOP_WORDS:
                words.add(w)
    return words, {t for t in titles if len(t) >= 3}


def rec_files(data_dir):
    d = os.path.join(data_dir, "rec")
    return [os.path.join(d, fn) for fn in sorted(os.listdir(d))] if os.path.isdir(d) else []


def simulate(files, cfg, trends):
    """Baca rekaman baris per baris, langsung simulasikan semua umur x aturan jual, simpan hasilnya
    saja (hemat memori). Return per umur: t0, cocok-narasi, simbol, M[exit, koin], H[exit, koin]."""
    acc = {A: ([], [], [], array("f"), array("f")) for A in AGES}
    n_rec = 0
    for fp in files:
        with open(fp) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    sn = {x[0]: x[1] for x in r["snaps"] if x[0] in AGES}
                    t0, sym, end = float(r["t0"]), str(r.get("s") or ""), float(r["end"])
                    cs = [(ms.rec_bucket_start(c[0]), ms.rec_bucket_end(c[0]), c[1], c[2], c[3]) for c in r["c"]]
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
                n_rec += 1
                tr = trends.get(dt.datetime.utcfromtimestamp(t0).date())
                key = re.sub(r"[^a-z]", "", sym.lower())
                hit = bool(tr) and len(key) >= 3 and (key in tr[0] or key in tr[1])
                for A, m0 in sn.items():
                    ms_, hs = [], []
                    for tp, sl, T in EXITS:
                        x = ms.res_trade(cs, end, A, m0, tp, sl, T, cfg, SIZE)
                        ms_.append(x[0] if x else np.nan)
                        hs.append(x[1] - A if x else np.nan)
                    L = acc[A]
                    L[0].append(t0)
                    L[1].append(hit)
                    L[2].append(sym if hit else "")
                    L[3].extend(ms_)
                    L[4].extend(hs)
    out = {}
    for A, (t, h, sy, M, H) in acc.items():
        if t:
            k = len(EXITS)
            out[A] = (np.array(t), np.array(h), sy, np.frombuffer(M, dtype=np.float32).reshape(-1, k).T,
                      np.frombuffer(H, dtype=np.float32).reshape(-1, k).T)
    return out, n_rec


def sim200(trades):
    bal, busy, n, w = START, -1.0, 0, 0
    for t, m, h in sorted(trades):
        if t < busy or bal < STOP:
            continue
        bal += min(STAKE, bal) * (m - 1)
        busy, n, w = t + h, n + 1, w + (m > 1)
    return bal, n, w


def stat(v):
    v = np.array(v, dtype=float)
    n = len(v)
    if n < 2:
        return n, float("nan"), float("nan"), float("nan")
    m, sd = float(v.mean()), float(v.std(ddof=1))
    return n, m, m - 1.96 * sd / math.sqrt(n), float((v > 1).mean())


def fmt(st):
    n, m, lo, w = st
    return f"n={n}, menang {w:.0%}, rata {m:.3f}x (CI bawah {lo:.3f})" if n >= 2 else f"n={n}"


def ex_lab(e):
    tp, sl, T = EXITS[e]
    return f"TP {tp:g}x, SL -{sl:.0%}, maks {T / 60:g} menit"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    ok = probe()
    if not ok.get("Wikipedia top harian"):
        print("\nWikipedia tidak bisa diakses, uji riwayat tidak bisa dibuat.")
        return
    cfg = ms.load_config(a.data)
    files = rec_files(a.data)
    days = sorted(dt.datetime.strptime(os.path.basename(f)[4:12], "%Y%m%d").date() for f in files
                  if re.match(r"rec-\d{8}\.jsonl$", os.path.basename(f)))
    if not days:
        print("Belum ada rekaman.")
        return
    trends = {d: wiki_terms(d - dt.timedelta(days=1)) for d in days}     # tren KEMARIN
    miss = [str(k) for k, v in trends.items() if v is None]
    print(f"\n== TREN: Wikipedia top 1000 per hari, {days[0] - dt.timedelta(days=1)} s/d {days[-1] - dt.timedelta(days=1)}"
          f"{' (gagal: ' + ', '.join(miss) + ')' if miss else ''}")
    t_start = time.time()
    per_age, n_rec = simulate(files, cfg, trends)
    T0, HIT, SYM = per_age[AGES[0]][0], per_age[AGES[0]][1], per_age[AGES[0]][2]
    t_cut = float(np.quantile(T0, 0.7))
    print(f"   {n_rec:,} koin terekam; di umur {AGES[0]} dtk {len(T0):,} koin, {HIT.sum():,} cocok narasi ({HIT.mean():.1%}). "
          f"Simulasi {time.time() - t_start:.0f} dtk.")
    common = {}
    for sy in SYM:
        if sy:
            common[sy.upper()] = common.get(sy.upper(), 0) + 1
    print("   simbol narasi terbanyak: " + ", ".join(f"{k} ({v})" for k, v in sorted(common.items(), key=lambda x: -x[1])[:25]))
    print(f"   Data lama (pilih): s/d {time.strftime('%d/%m %H:%M', time.gmtime(t_cut))} UTC, data baru (uji): sesudahnya")

    def trades(A, e, grp, new):
        t, h, _, M, H = per_age[A]
        sel = ((t >= t_cut) if new else (t < t_cut)) & ~np.isnan(M[e])
        if grp == "narasi":
            sel &= h
        return list(zip((t[sel] + A + cfg["EXEC_DELAY"]).tolist(), M[e][sel].astype(float).tolist(),
                        H[e][sel].astype(float).tolist()))

    print("\n== HASIL PER UMUR MASUK (aturan jual terbaik di data lama, angka dari DATA BARU)")
    best_all = None
    for A in AGES:
        if A not in per_age:
            continue
        for g in ("narasi", "semua"):
            cands = []
            for e in range(len(EXITS)):
                old = trades(A, e, g, False)
                if len(old) >= 30:
                    cands.append((float(np.mean([x[1] for x in old])), e))
            if not cands:
                print(f"  umur {A:>3} dtk · {g:<6}: kurang dari 30 trade di data lama")
                continue
            m_tr, e = max(cands)
            new = trades(A, e, g, True)
            bal, n, w = sim200(new)
            print(f"  umur {A:>3} dtk · {g:<6} · {ex_lab(e):<30} lama {m_tr:.3f}x | baru {fmt(stat([x[1] for x in new]))}"
                  f" | $200 -> ${bal:.2f} ({n} trade)")
            if g == "narasi" and (best_all is None or m_tr > best_all[0]):
                best_all = (m_tr, A, e)

    if best_all:
        m_tr, A, e = best_all
        new = trades(A, e, "narasi", True)
        st = stat([x[1] for x in new])
        bal, n, w = sim200(new)
        lo, hi = ms.wilson(w, n) if n else (0, 0)
        proven = st[0] >= 30 and st[2] > 1.0
        print(f"\n== STRATEGI NARASI TERBAIK (dipilih di data lama): umur {A} dtk · {ex_lab(e)}")
        print(f"   data baru: {fmt(st)} -> {'TERBUKTI' if proven else 'TIDAK terbukti'}")
        print(f"   SIMULASI $200 data baru: {n} trade, menang {w}"
              f"{f' ({w / n:.0%}, CI {lo:.0%}-{hi:.0%})' if n else ''}, modal akhir ${bal:.2f} ({bal - START:+.2f})"
              + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))
    print("\n   Data rekaman mulai 14 Okt 2026, jadi Jan 2026 - sekarang tidak bisa disimulasikan.")


if __name__ == "__main__":
    main()

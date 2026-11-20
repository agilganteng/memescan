#!/usr/bin/env python3
"""Uji "N whale beli dalam rentang waktu singkat" (permintaan user 20 Nov 2026).

Sinyal: N wallet BERBEDA dari daftar whale melakukan beli pertama di koin yang sama dalam rentang W detik.
Beli 3 detik setelah whale ke-N. N = 2,3,4,5; W = 10,20,30,60,120 detik dan "bebas" (seluruh rekaman ~300 dtk).
Daftar wallet: ketat (kriteria bot), longgar top 1000 / top 5000 PnL, dan kontrol acak seukuran daftar ketat.
Out-of-sample: P3 pakai daftar dari P1-2, P4 pakai daftar dari P1-3. Tidak ada parameter yang dipilih dari P3/P4.
LOLOS = n>=30 dan rata-rata tanpa koin terbaik > 1 di P3 DAN P4. Biaya, slip, telat 3 dtk = sama dengan whale_scan.
"""
import argparse
import collections
import math
import random
import time

import whale_scan as ws

NS = (2, 3, 4, 5)
WINS = (10, 20, 30, 60, 120, 1e9)
EXITS = ("bot", "tahan60", "tahan5m", "savip")


def wname(w):
    return "bebas" if w > 1e6 else f"{int(w)}dtk"


def sig(data, files, t_from, t_to, lists):
    out = {k: {(n, w): {e: [] for e in EXITS} for n in NS for w in WINS} for k in lists}
    age = {k: {(n, w): [] for n in NS for w in WINS} for k in lists}
    for c in ws.iter_coins(data, files):
        if not (t_from <= c.t0 < t_to):
            continue
        cw = ws.coin_wallets(c)
        order = sorted((v[0], w) for w, v in cw.items())
        for k, L in lists.items():
            hit = [a for a, w in order if w in L]
            if len(hit) < 2:
                continue
            for n in NS:
                if len(hit) < n:
                    break
                for w in WINS:
                    te = None
                    for i in range(n - 1, len(hit)):
                        if hit[i] - hit[i - n + 1] <= w:
                            te = hit[i] + ws.LAT
                            break
                    if te is None or te >= c.end:
                        continue
                    d = out[k][(n, w)]
                    d["bot"].append(ws.bot_exit(c, te))
                    d["tahan60"].append(ws.hold_exit(c, te, 60))
                    d["tahan5m"].append(ws.hold_exit(c, te, 300))
                    d["savip"].append(ws.savip_exit(c, te))
                    age[k][(n, w)].append(te)
    return out, age


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    files = ws.rec_files(a.data)
    cnt, dev_n = collections.Counter(), collections.Counter()
    t_lo, t_hi, n_coins = math.inf, -math.inf, 0
    for c in ws.iter_coins(a.data, files):
        n_coins += 1
        t_lo, t_hi = min(t_lo, c.t0), max(t_hi, c.t0)
        if c.dev:
            dev_n[c.dev] += 1
        seen = set()
        for ag, w, isb, sol in c.w:
            if isb and w not in seen and ag <= c.cov:
                seen.add(w)
                cnt[w] += 1
    cand = {w for w, n in cnt.items() if n >= ws.CRIT["MIN_COINS"]}
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))  # noqa: E731
    print(f"[data] {n_coins} koin kurva standar, {fmt(t_lo)} s/d {fmt(t_hi)}, {len(cand)} wallet >= 10 koin "
          f"({time.time() - t_start:.0f}s)", flush=True)
    del cnt
    span = (t_hi - t_lo) / ws.NPER

    def period_of(t):
        return min(ws.NPER - 1, int((t - t_lo) // span)) if span > 0 else 0

    acc = {}
    ws.scan(a.data, files, t_lo, t_hi, cand, dev_n, acc, period_of)
    print(f"[data] statistik {len(acc)} wallet ({time.time() - t_start:.0f}s)", flush=True)

    def lists(pers, seed):
        lst, _, elig, _ = ws.build_list(acc, dev_n, pers)
        ketat = {w for w, _ in lst}
        ll = ws.loose_list(acc, dev_n, pers, 0.5)
        pool = [w for w in elig if w not in ketat]
        rnd = random.Random(seed)
        L = {"ketat": ketat,
             "top1000 PnL": {w for _, w in ll[:1000]},
             "top5000 PnL": {w for _, w in ll[:5000]},
             "KONTROL acak": set(rnd.sample(pool, min(len(pool), len(ketat)))) if pool else set()}
        return L

    t3, t4 = t_lo + 2 * span, t_lo + 3 * span
    L12, L123 = lists(range(2), 5), lists(range(3), 7)
    print("[daftar] P1-2: " + ", ".join(f"{k}={len(v)}" for k, v in L12.items()), flush=True)
    print("[daftar] P1-3: " + ", ".join(f"{k}={len(v)}" for k, v in L123.items()), flush=True)
    print(f"[periode] P3 {fmt(t3)} - {fmt(t4)} | P4 {fmt(t4)} - {fmt(t_hi)}", flush=True)
    r3, a3 = sig(a.data, files, t3, t4, L12)
    print(f"[P3 selesai] {time.time() - t_start:.0f}s", flush=True)
    r4, a4 = sig(a.data, files, t4, math.inf, L123)
    print(f"[P4 selesai] {time.time() - t_start:.0f}s", flush=True)

    def f(st):
        if not st.get("n"):
            return "n=0"
        return (f"n={st['n']} rata {st['mean']:.3f}x tanpa-terbaik {st['mean_wo_best'] if st['mean_wo_best'] is not None else float('nan'):.3f}x "
                f"median {st['median']:.3f}x menang {st['win'] * 100:.0f}% $200->${st['sim200']:.0f}")

    lolos, sel = [], 0
    for k in L123:
        print(f"\n## Daftar: {k}", flush=True)
        for n in NS:
            for w in WINS:
                ag = sorted(a4[k][(n, w)])
                med = f"umur sinyal median {ag[len(ag) // 2]:.0f} dtk" if ag else ""
                print(f"- {n} whale dalam {wname(w)} {med}", flush=True)
                for e in EXITS:
                    s3, s4 = ws.mstat(r3[k][(n, w)][e]), ws.mstat(r4[k][(n, w)][e])
                    print(f"    {e:8s} P3 {f(s3)} | P4 {f(s4)}", flush=True)
                    if s3.get("n", 0) >= 30 and s4.get("n", 0) >= 30:
                        sel += 1
                        if s3["mean_wo_best"] > 1 and s4["mean_wo_best"] > 1:
                            lolos.append((k, n, wname(w), e, s3, s4))
    print(f"\n[ringkas] sel dengan n>=30 di P3 dan P4: {sel}; LOLOS (tanpa-terbaik >1 di P3 dan P4): {len(lolos)}",
          flush=True)
    for k, n, w, e, s3, s4 in lolos:
        print(f"  LOLOS {k} | {n} whale {w} | {e} | P3 {f(s3)} | P4 {f(s4)}", flush=True)
    print(f"[selesai] {time.time() - t_start:.0f}s", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Uji "1 whale beli besar saat harga di bawah rata-rata" (permintaan user 20 Nov 2026).

Sinyal: SATU wallet dari daftar whale beli >= S SOL dalam satu transaksi, saat harga sebelum transaksi itu
<= R x rata-rata harga koin sejauh ini (atau <= R x puncak sejauh ini). Sinyal pertama per koin. Beli 3 dtk kemudian.
S = 0,5 / 1 / 2 / 3 / 5 SOL. Posisi harga: semua, <=1,0 / 0,9 / 0,8 / 0,7 x rata-rata, <=0,7 / 0,5 x puncak.
Daftar: ketat (kriteria bot), top 1000 / top 5000 PnL, dan KONTROL "wallet mana pun" (bukan whale).
Batas data: perekam hanya menyimpan transaksi 300 dtk pertama (maks 150 transaksi) tiap koin, jadi "rata-rata" =
rata-rata harga sejak koin lahir sampai saat itu, dan syarat posisi harga butuh minimal 5 transaksi sebelumnya.
Out-of-sample: P3 pakai daftar dari P1-2, P4 pakai daftar dari P1-3. LOLOS = n>=30 dan tanpa-terbaik >1 di P3 DAN P4.
"""
import argparse
import bisect
import collections
import math
import random
import time

import whale_scan as ws

SIZES = (0.5, 1.0, 2.0, 3.0, 5.0)
POS = (("semua", None, None), ("<=1,0x rata2", "a", 1.0), ("<=0,9x rata2", "a", 0.9), ("<=0,8x rata2", "a", 0.8),
       ("<=0,7x rata2", "a", 0.7), ("<=0,7x puncak", "p", 0.7), ("<=0,5x puncak", "p", 0.5))
EXITS = ("bot", "tahan60", "tahan5m", "savip")
ALL = "KONTROL wallet mana pun"


def sig(data, files, t_from, t_to, lists):
    cells = [(s, p[0]) for s in SIZES for p in POS]
    out = {k: {cl: {e: [] for e in EXITS} for cl in cells} for k in lists}
    age = {k: {cl: [] for cl in cells} for k in lists}
    for c in ws.iter_coins(data, files):
        if not (t_from <= c.t0 < t_to):
            continue
        if c.tt is None:
            ws.build_path(c)
        pre, run, pk, peak = [0.0], 0.0, [0.0], 0.0
        for p in c.tp:
            run += p
            peak = max(peak, p)
            pre.append(run)
            pk.append(peak)
        cache = {}
        done = {k: set() for k in lists}
        for ag, w, isb, sol in c.w:
            if ag > c.cov:
                break
            if not isb or sol < SIZES[0]:
                continue
            ks = [k for k, L in lists.items() if (L is None or w in L) and len(done[k]) < len(cells)]
            if not ks:
                continue
            te = ag + ws.LAT
            if te >= c.end:
                continue
            k0 = bisect.bisect_left(c.tt, ag)
            pb = c.tp[k0 - 1] if k0 > 0 else c.m0
            ra = pb / (pre[k0] / k0) if k0 >= 5 else None
            rp = pb / pk[k0] if k0 >= 5 and pk[k0] > 0 else None
            ok = []
            for s in SIZES:
                if sol < s:
                    break
                for name, kind, thr in POS:
                    if kind is None or (kind == "a" and ra is not None and ra <= thr) or \
                            (kind == "p" and rp is not None and rp <= thr):
                        ok.append((s, name))
            if not ok:
                continue
            for k in ks:
                new = [cl for cl in ok if cl not in done[k]]
                if not new:
                    continue
                if te not in cache:
                    cache[te] = (ws.bot_exit(c, te), ws.hold_exit(c, te, 60), ws.hold_exit(c, te, 300),
                                 ws.savip_exit(c, te))
                r = cache[te]
                for cl in new:
                    done[k].add(cl)
                    for e, x in zip(EXITS, r):
                        out[k][cl][e].append(x)
                    age[k][cl].append(te)
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

    def lists(pers):
        lst = ws.build_list(acc, dev_n, pers)[0]
        ll = ws.loose_list(acc, dev_n, pers, 0.5)
        return {"ketat": {w for w, _ in lst}, "top1000 PnL": {w for _, w in ll[:1000]},
                "top5000 PnL": {w for _, w in ll[:5000]}, ALL: None}

    t3, t4 = t_lo + 2 * span, t_lo + 3 * span
    L12, L123 = lists(range(2)), lists(range(3))
    print("[daftar] P1-2: " + ", ".join(f"{k}={len(v) if v is not None else 'semua'}" for k, v in L12.items()))
    print("[daftar] P1-3: " + ", ".join(f"{k}={len(v) if v is not None else 'semua'}" for k, v in L123.items()))
    print(f"[periode] P3 {fmt(t3)} - {fmt(t4)} | P4 {fmt(t4)} - {fmt(t_hi)}", flush=True)
    r3, _ = sig(a.data, files, t3, t4, L12)
    print(f"[P3 selesai] {time.time() - t_start:.0f}s", flush=True)
    r4, a4 = sig(a.data, files, t4, math.inf, L123)
    print(f"[P4 selesai] {time.time() - t_start:.0f}s", flush=True)

    def f(st):
        if not st.get("n"):
            return "n=0"
        wb = st["mean_wo_best"] if st["mean_wo_best"] is not None else float("nan")
        return (f"n={st['n']} rata {st['mean']:.3f}x tb {wb:.3f}x med {st['median']:.3f}x "
                f"menang {st['win'] * 100:.0f}% $200->${st['sim200']:.0f}")

    lolos, sel = [], 0
    for k in L123:
        print(f"\n## Daftar: {k}", flush=True)
        for s in SIZES:
            for name, _, _ in POS:
                cl = (s, name)
                ag = sorted(a4[k][cl])
                med = f"umur median {ag[len(ag) // 2]:.0f} dtk" if ag else ""
                print(f"- beli >= {s} SOL, harga {name} | {med}", flush=True)
                for e in EXITS:
                    s3, s4 = ws.mstat(r3[k][cl][e]), ws.mstat(r4[k][cl][e])
                    print(f"    {e:8s} P3 {f(s3)} | P4 {f(s4)}", flush=True)
                    if s3.get("n", 0) >= 30 and s4.get("n", 0) >= 30:
                        sel += 1
                        if s3["mean_wo_best"] > 1 and s4["mean_wo_best"] > 1:
                            lolos.append((k, s, name, e, s3, s4))
    print(f"\n[ringkas] sel dengan n>=30 di P3 dan P4: {sel}; LOLOS (tanpa-terbaik >1 di P3 dan P4): {len(lolos)}",
          flush=True)
    for k, s, name, e, s3, s4 in lolos:
        print(f"  LOLOS {k} | >= {s} SOL {name} | {e} | P3 {f(s3)} | P4 {f(s4)}", flush=True)
    print(f"[selesai] {time.time() - t_start:.0f}s", flush=True)


if __name__ == "__main__":
    main()

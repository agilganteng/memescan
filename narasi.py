#!/usr/bin/env python3
"""narasi: gabungan dua arah whale x narasi (ide user 14 Nov).

  A  whale dulu: koin dibeli >= N whale (daftar ketat / top 500 / top 2000), lalu cek narasinya ramai -> masuk.
  B  narasi dulu: koin lahir dengan narasi ramai, lalu cek wallet whale: sudah ada >= 1 / >= 2 whale beli
     sampai umur 10 / 30 / 60 dtk -> masuk di umur itu.
  C  pembanding: narasi saja (masuk umur 10/30 dtk) dan whale saja.

Narasi (proksi yang ada di rekaman, dihitung hanya dari koin SEBELUM saat masuk):
  gelombang  >= 3 koin lain dengan simbol sama lahir dalam 1 jam terakhir (nama lagi musim / hype wave)
  ramai6j    >= 10 koin simbol sama dalam 6 jam terakhir
  terbukti   ada koin simbol sama dalam 6 jam terakhir yang sudah pernah >= 3x (narasi terbukti laku)
  salahsatu  gelombang ATAU terbukti
Data X/Twitter tidak ada di rekaman GitHub (x.com diblok dari server); tes narasi X dulu (lewat Chrome) sudah rugi.

Daftar wallet untuk koin di periode p dibangun dari periode < p saja. Pilih di P3 (n >= 30, rata-rata tanpa
koin terbaik > 1), uji SEKALI di P4. Latency 3 dtk, biaya sama dengan whale_scan.

Pakai: python3 narasi.py --data data --out out
"""
import argparse
import bisect
import collections
import json
import math
import os
import time

import memescan as ms  # noqa: F401
import whale_scan as ws
from gabungan import tp_exit

EXITS = ("bot", "tp2", "savip", "tahan300")
CONDS = ("semua", "gelombang", "ramai6j", "terbukti", "salahsatu")


def norm_sym(s):
    return "".join(ch for ch in str(s).upper() if ch.isalpha())[:12]


def exits(c, te):
    return {"bot": ws.bot_exit(c, te), "tp2": tp_exit(c, te), "savip": ws.savip_exit(c, te),
            "tahan300": ws.hold_exit(c, te, 300)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    T = time.time()
    os.makedirs(a.out, exist_ok=True)
    files = ws.rec_files(a.data)
    cnt, dev_n = collections.Counter(), collections.Counter()
    t_lo, t_hi, n_coins = math.inf, -math.inf, 0
    sym_t, sym_hit = collections.defaultdict(list), collections.defaultdict(list)
    for c in ws.iter_coins(a.data, files):
        n_coins += 1
        t_lo, t_hi = min(t_lo, c.t0), max(t_hi, c.t0)
        if c.dev:
            dev_n[c.dev] += 1
        s = norm_sym(c.s)
        if s:
            sym_t[s].append(c.t0)
            if max(x[2] for x in c.cs) / c.m0 >= 3.0:
                sym_hit[s].append(c.t0)
        seen = set()
        for ag, w, isb, sol in c.w:
            if isb and w not in seen and ag <= c.cov:
                seen.add(w)
                cnt[w] += 1
    for d in (sym_t, sym_hit):
        for v in d.values():
            v.sort()
    cand = {w for w, n in cnt.items() if n >= ws.CRIT["MIN_COINS"]}
    del cnt
    span = (t_hi - t_lo) / ws.NPER

    def period_of(t):
        return min(ws.NPER - 1, int((t - t_lo) // span))

    acc = {}
    ws.scan(a.data, files, t_lo, t_hi, cand, dev_n, acc, period_of)
    lists = {}
    for p in (1, 2, 3):
        ll = ws.loose_list(acc, dev_n, range(p), 0.2)
        lists[p] = {"ketat": {w for w, _ in ws.build_list(acc, dev_n, range(p))[0]},
                    "top500": {w for _, w in ll[:500]}, "top2000": {w for _, w in ll[:2000]}}
        print(f"[daftar P{p + 1}] " + ", ".join(f"{k} {len(v)}" for k, v in lists[p].items()), flush=True)
    del acc

    def cnt_in(arr, lo, hi):
        return bisect.bisect_right(arr, hi) - bisect.bisect_left(arr, lo)

    def narr(s, t0, tq):
        if not s:
            return {"semua": True, "gelombang": False, "ramai6j": False, "terbukti": False, "salahsatu": False}
        ts = sym_t.get(s, [])
        n1 = cnt_in(ts, tq - 3600, tq) - (1 if t0 >= tq - 3600 else 0)
        n6 = cnt_in(ts, tq - 6 * 3600, tq) - 1
        hit = cnt_in(sym_hit.get(s, []), tq - 6 * 3600, tq - 1800)   # koin lama yang rekamannya sudah selesai
        g, r, b = n1 >= 3, n6 >= 10, hit >= 1
        return {"semua": True, "gelombang": g, "ramai6j": r, "terbukti": b, "salahsatu": g or b}

    R = collections.defaultdict(list)    # (p, fam, list, param, cond, exit) -> [mult]
    n_nar = collections.Counter()
    for c in ws.iter_coins(a.data, files):
        p = period_of(c.t0)
        if p == 0:
            continue
        ws.build_path(c)
        s = norm_sym(c.s)
        cw = ws.coin_wallets(c)
        order = sorted((v[0], w) for w, v in cw.items())
        nb = narr(s, c.t0, c.t0)
        for k, v in nb.items():
            n_nar[(p, k)] += v
        # C: narasi saja
        for age in (10.0, 30.0):
            te = age + ws.LAT
            if te >= c.end:
                continue
            nq = narr(s, c.t0, c.t0 + age)
            ex = None
            for cd in CONDS:
                if nq[cd]:
                    ex = ex or exits(c, te)
                    for e in EXITS:
                        R[(p, "C narasi saja", "-", f"umur{int(age)}", cd, e)].append(ex[e])
        for ln, L in lists[p].items():
            hit = [ag for ag, w in order if w in L]
            # A: whale dulu, lalu cek narasi saat whale ke-N beli
            for n in (1, 2, 3):
                if len(hit) < n:
                    continue
                t_n = hit[n - 1]
                te = t_n + ws.LAT
                if te >= c.end:
                    continue
                nq = narr(s, c.t0, c.t0 + t_n)
                ex = None
                for cd in CONDS:
                    if nq[cd]:
                        ex = ex or exits(c, te)
                        for e in EXITS:
                            R[(p, "A whale dulu", ln, f"N{n}", cd, e)].append(ex[e])
            # B: narasi ramai saat lahir, cek whale sudah beli sampai umur X
            for age in (10.0, 30.0, 60.0):
                te = age + ws.LAT
                if te >= c.end:
                    continue
                k = bisect.bisect_right(hit, age)
                for need in (1, 2):
                    if k < need:
                        continue
                    ex = None
                    for cd in CONDS[1:]:
                        if nb[cd]:
                            ex = ex or exits(c, te)
                            for e in EXITS:
                                R[(p, "B narasi dulu", ln, f">={need}whale@{int(age)}s", cd, e)].append(ex[e])
        c.tt = c.tp = None
    print(f"[narasi] koin dengan narasi ramai saat lahir: " +
          ", ".join(f"P{p + 1} {k} {n_nar[(p, k)]}" for p in (1, 2, 3) for k in CONDS), flush=True)
    print(f"[selesai hitung] {time.time() - T:.0f}s, {len(R)} sel", flush=True)

    keys = sorted({k[1:] for k in R})
    rows = []
    for k in keys:
        s3, s4 = ws.mstat(R.get((2,) + k, [])), ws.mstat(R.get((3,) + k, []))
        rows.append(dict(fam=k[0], daftar=k[1], param=k[2], narasi=k[3], exit=k[4], P3=s3, P4=s4))
    print("[tabel] keluarga | daftar | param | narasi | exit : P3 rata/n | P4 rata/n/$200", flush=True)
    for r in rows:
        if r["exit"] != "savip" and r["exit"] != "tp2":
            continue
        f = lambda s: f"{s['mean']:.3f}/n{s['n']}" if s.get("n") else "-"  # noqa: E731
        sim = f"/${r['P4']['sim200']}" if r["P4"].get("n") else ""
        print(f"  {r['fam']} | {r['daftar']} | {r['param']} | {r['narasi']} | {r['exit']} : {f(r['P3'])} | "
              f"{f(r['P4'])}{sim}", flush=True)
    ok = [r for r in rows if r["P3"].get("n", 0) >= 30 and (r["P3"].get("mean_wo_best") or 0) > 1.0]
    elig = [r for r in rows if r["P3"].get("n", 0) >= 30]
    print(f"[pilih] strategi n>=30 di P3: {len(elig)}; untung tanpa koin terbaik: {len(ok)}", flush=True)
    top = sorted(elig, key=lambda r: -(r["P3"].get("mean_wo_best") or 0))[:15]
    for r in top:
        print(f"  TOP P3 {r['fam']} | {r['daftar']} | {r['param']} | {r['narasi']} | {r['exit']}: P3 {r['P3']} "
              f"=> P4 {r['P4']}", flush=True)
    out = {"lolos_P3": len(ok), "strategi_n30": len(elig), "lolos": ok, "top15": top, "semua": rows,
           "durasi_s": round(time.time() - T)}
    with open(os.path.join(a.out, "narasi.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    print(f"[selesai] {time.time() - T:.0f}s", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""dev_uji: uji dari sisi DEV pump.fun (ide user 15 Nov): bikin koin, beli di awal, jual ke pembeli.

Data: rekaman memescan (kurva standar saja). Dev = field `dev` (10 huruf awal wallet pembuat), trade 5 menit pertama.
  D1  untung NYATA wallet dev per koin: SOL jual - SOL beli (5 mnt pertama), sisa token dinilai harga akhir rekaman
      atau 0. Biaya: fee 1,25% per sisi + 0,02 SOL biaya bikin koin + 0,001 SOL per transaksi.
      Dikelompokkan: jumlah koin dev itu di data (1 / 2-5 / 6-20 / >20) dan besar beli awal.
  D2  simulasi "dev sederhana": beli awal B SOL (B = beli nyata dev di koin itu, umur <= 2 dtk), lalu jual SEMUA
      pada umur T dtk atau saat harga >= X kali harga setelah beli sendiri (kalau tidak tercapai jual umur 120 dtk).
      Hitung persis dari rumus kurva (jual sendiri ikut menurunkan harga). Pilih aturan di paruh waktu A, uji di B.
  D3  perkiraan fee kreator: 0,30% x volume trade 5 menit pertama (angka fee perlu dicek, hanya perkiraan).
Batas: wallet samping/bundle milik dev tidak terlihat; dev serial sering pakai wallet baru, jadi kelompok "1 koin"
tercampur dev serial. Rekaman trade maksimal 150 trade / 5 menit per koin.

Pakai: python3 dev_uji.py --data data --out out
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

FEE = 0.0125
CREATE = 0.02
PRIO = 0.001
K = ws.K_CURVE
TS = (3, 5, 10, 20, 30, 60, 120, 300)
TPS = (1.2, 1.5, 2.0, 3.0)
CREATOR_FEE = 0.003


def vres(mcap):
    return math.sqrt(K * max(mcap, 1e-9))


def sell_out(v_t, b):
    """SOL keluar kalau jual semua token hasil beli b SOL di awal, saat cadangan SOL virtual = v_t."""
    inv = 1.0 / v_t + 1.0 / 30.0 - 1.0 / (30.0 + b)
    return v_t - 1.0 / inv


def bsize(b):
    return "0" if b <= 0 else "<0.5" if b < 0.5 else "0.5-2" if b < 2 else "2-5" if b < 5 else ">=5"


def ngrp(n):
    return "1 koin" if n <= 1 else "2-5" if n <= 5 else "6-20" if n <= 20 else ">20"


def agg(rows):
    """rows: list (beli, net_sol). -> ringkasan."""
    n = len(rows)
    if not n:
        return dict(n=0)
    nets = sorted(r[1] for r in rows)
    tb = sum(r[0] for r in rows)
    tot = sum(nets)
    return dict(n=n, untung=round(sum(1 for x in nets if x > 0) / n, 3), rata_sol=round(tot / n, 4),
                median_sol=round(nets[n // 2], 4), total_sol=round(tot, 1),
                roi=round(tot / tb, 3) if tb > 0 else None,
                rata_tanpa_1pct_terbaik=round(sum(nets[:max(1, n - max(1, n // 100))]) / max(1, n - max(1, n // 100)), 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    T0 = time.time()
    os.makedirs(a.out, exist_ok=True)
    files = ws.rec_files(a.data)
    recs = []
    dev_n = collections.Counter()
    for c in ws.iter_coins(a.data, files):
        if not c.dev:
            continue
        dev_n[c.dev] += 1
        ws.build_path(c)
        b0 = buy = sell = tok = 0.0
        nb, nsell_tx, ntx, vol, first_sell = set(), 0, 0, 0.0, None
        for ag, w, isb, sol in c.w:
            if ag > c.cov:
                break
            vol += sol
            if w != c.dev:
                if isb:
                    nb.add(w)
                continue
            ntx += 1
            p = ws.price_at(c, ag) / ms.SUPPLY
            if isb:
                buy += sol
                tok += sol / p if p > 0 else 0.0
                if ag <= 2.0:
                    b0 += sol
            else:
                sell += sol
                tok = max(0.0, tok - (sol / p if p > 0 else 0.0))
                nsell_tx += 1
                if first_sell is None:
                    first_sell = ag
        pe = ws.end_price(c) / ms.SUPPLY
        cost = buy * (1 + FEE) + CREATE + PRIO * max(1, ntx)
        net0 = sell * (1 - FEE) - cost                       # sisa token dinilai 0
        net1 = net0 + tok * pe * (1 - FEE)                   # sisa token dinilai harga akhir rekaman
        sims = None
        if 0.05 <= b0 <= 20:
            base = b0 * (1 + FEE) + CREATE + 2 * PRIO
            sims = {}
            for t in TS:
                if t >= c.end:
                    continue
                sims[f"T{t}"] = sell_out(vres(ws.price_at(c, t)), b0) * (1 - FEE) / base
            p_post = (30.0 + b0) ** 2 / K
            for x in TPS:
                hit = None
                for ag, pr in zip(c.tt, c.tp):
                    if ag > 120:
                        break
                    if ag >= 1.0 and pr >= x * p_post:
                        hit = ag
                        break
                te = min((hit + 1.0) if hit is not None else 120.0, c.end)
                sims[f"TP{x}"] = sell_out(vres(ws.price_at(c, te)), b0) * (1 - FEE) / base
        recs.append((c.t0, c.dev, b0, buy, sell, net0, net1, len(nb), vol, first_sell, sims))
        c.tt = c.tp = None
    n = len(recs)
    print(f"[data] {n} koin kurva standar, {len(dev_n)} dev ({time.time() - T0:.0f}s)", flush=True)
    recs.sort(key=lambda r: r[0])
    t_mid = recs[n // 2][0]
    hasb = [r for r in recs if r[3] > 0]
    print(f"[dev] dev ikut beli di 5 mnt pertama: {len(hasb)} ({len(hasb) / n:.1%}); beli di umur <=2 dtk: "
          f"{sum(1 for r in recs if r[2] > 0)}; dev yang jual di 5 mnt: {sum(1 for r in recs if r[4] > 0)}", flush=True)
    fs = sorted(r[9] for r in recs if r[9] is not None)
    if fs:
        print(f"[dev] umur jual pertama dev: p25 {fs[len(fs) // 4]:.0f}s, median {fs[len(fs) // 2]:.0f}s, "
              f"p75 {fs[3 * len(fs) // 4]:.0f}s", flush=True)
    out = {"n_koin": n, "n_dev": len(dev_n)}

    # D1: untung nyata
    print("[D1] untung NYATA wallet dev (SOL per koin). net0 = sisa token dinilai 0, net1 = dinilai harga akhir", flush=True)
    d1 = {}
    for label, key in (("semua", lambda r: "semua"), ("jumlah koin dev", lambda r: ngrp(dev_n[r[1]])),
                       ("beli awal", lambda r: bsize(r[3]))):
        g = collections.defaultdict(list)
        for r in recs:
            g[key(r)].append(r)
        for k in sorted(g):
            rows = g[k]
            s0, s1 = agg([(r[3], r[5]) for r in rows]), agg([(r[3], r[6]) for r in rows])
            pb = sorted(r[7] for r in rows)
            d1[f"{label}: {k}"] = dict(net0=s0, net1=s1, pembeli_lain_median=pb[len(pb) // 2],
                                       tanpa_pembeli=round(sum(1 for x in pb if x == 0) / len(pb), 3))
            print(f"  {label}: {k} | n {s0['n']} | untung {s0['untung']:.1%} | rata {s0['rata_sol']} SOL | median "
                  f"{s0['median_sol']} | ROI {s0['roi']} | total {s0['total_sol']} SOL | tanpa 1% terbaik "
                  f"{s0['rata_tanpa_1pct_terbaik']} || net1 rata {s1['rata_sol']} ROI {s1['roi']} | pembeli lain median "
                  f"{pb[len(pb) // 2]}, tanpa pembeli {d1[f'{label}: {k}']['tanpa_pembeli']:.1%}", flush=True)
    # paruh A vs B untuk dev yang beli
    for nm, part in (("A", [r for r in hasb if r[0] < t_mid]), ("B", [r for r in hasb if r[0] >= t_mid])):
        s = agg([(r[3], r[5]) for r in part])
        d1[f"dev yang beli, paruh {nm}"] = s
        print(f"  dev yang beli, paruh {nm}: {s}", flush=True)
    # konsentrasi: berapa dev yang total untung
    per = collections.defaultdict(float)
    for r in recs:
        per[r[1]] += r[5]
    v = sorted(per.values())
    pos = [x for x in v if x > 0]
    top = sorted(pos, reverse=True)
    d1["per_dev"] = dict(n=len(v), untung=round(len(pos) / len(v), 3), median=round(v[len(v) // 2], 4),
                         total_untung=round(sum(pos), 1), total_rugi=round(sum(x for x in v if x < 0), 1),
                         top1pct_share=round(sum(top[:max(1, len(v) // 100)]) / max(1e-9, sum(pos)), 3))
    print(f"[D1] per dev (total semua koinnya): {d1['per_dev']}", flush=True)
    out["D1"] = d1

    # D2: simulasi aturan jual
    print("[D2] simulasi dev sederhana: beli awal B nyata, jual semua di T / TP. kelipatan modal (termasuk biaya)", flush=True)
    d2 = {}
    sim_rows = [r for r in recs if r[10]]
    keys = [f"T{t}" for t in TS] + [f"TP{x}" for x in TPS]
    for grp, sel in (("semua", lambda r: True), ("beli 0.5-2", lambda r: 0.5 <= r[2] < 2),
                     ("beli 2-5", lambda r: 2 <= r[2] < 5), ("beli <0.5", lambda r: r[2] < 0.5),
                     ("dev 1 koin", lambda r: dev_n[r[1]] <= 1), ("dev >20 koin", lambda r: dev_n[r[1]] > 20)):
        rows = [r for r in sim_rows if sel(r)]
        for k in keys:
            A = ws.mstat([r[10].get(k) for r in rows if r[0] < t_mid])
            B = ws.mstat([r[10].get(k) for r in rows if r[0] >= t_mid])
            d2[f"{grp} | {k}"] = dict(A=A, B=B)
            f = lambda s: (f"{s['mean']:.3f} med {s['median']:.3f} win {s['win']:.0%} n{s['n']} tanpaTerbaik "  # noqa: E731
                           f"{s['mean_wo_best']} $200->{s['sim200']}") if s.get("n") else "-"
            print(f"  {grp} | {k} : A {f(A)} | B {f(B)}", flush=True)
    elig = [(k, v) for k, v in d2.items() if v["A"].get("n", 0) >= 30]
    best = sorted(elig, key=lambda kv: -(kv[1]["A"].get("mean_wo_best") or 0))[:5]
    print("[D2] 5 teratas di A (tanpa koin terbaik) dan hasilnya di B:", flush=True)
    for k, v in best:
        print(f"  {k}: A {v['A']} => B {v['B']}", flush=True)
    out["D2"] = d2
    out["D2_top_A"] = [k for k, _ in best]

    # D3: fee kreator
    vols = sorted(r[8] for r in recs)
    mv = sum(vols) / n
    d3 = dict(volume_5mnt_rata_sol=round(mv, 3), median=round(vols[n // 2], 3), p90=round(vols[int(n * 0.9)], 3),
              p99=round(vols[int(n * 0.99)], 3), fee_kreator_rata_sol=round(mv * CREATOR_FEE, 5),
              fee_kreator_p99_sol=round(vols[int(n * 0.99)] * CREATOR_FEE, 4), biaya_bikin_sol=CREATE)
    print(f"[D3] perkiraan fee kreator 0,30% x volume 5 mnt pertama: {d3}", flush=True)
    out["D3"] = d3
    with open(os.path.join(a.out, "dev_uji.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    print(f"[selesai] {time.time() - T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

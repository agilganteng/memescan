#!/usr/bin/env python3
"""lulus_jalan: uji JALAN-MAJU (walk-forward) untuk bot yang mencari ulang aturannya tiap hari (19 Nov 2026).

Pertanyaan: kalau bot tiap tengah malam UTC mencari sendiri aturan terbaik dari data yang SUDAH selesai, lalu memakai
aturan itu untuk koin yang lulus hari berikutnya, untung atau tidak? Ini menguji PROSEDUR pencarian, bukan satu aturan,
jadi tiap hari uji benar-benar belum terlihat saat aturan dipilih.

Ditetapkan sebelum dijalankan (tidak disetel):
  - Hari uji d (UTC). Data latih = koin yang semua hasilnya sudah diketahui sebelum d (lulus + 6 jam + horizon <= d).
  - Data latih dibagi waktu: W = 60% awal, P = 40% akhir. Kandidat: n_W >= 40, rata_W > 1,05, n_P >= 25, rata_P > 1.
  - Nilai = min(rata_W, rata_P), hasil dipotong 10x. Ambil K teratas dari SEMUA cara masuk dan keluar (K = 1, 5, 20).
  - Hari d: beli semua koin yang cocok (satu koin sekali saja), hasil ASLI, biaya 1,5% per sisi (sudah di sim).
  - Utama: K = 5. Lulus: n >= 30, rata > 1, rata tanpa koin terbaik > 1, dan lebih dari separuh hari uji untung.
  - Kontrol: prosedur sama tetapi hasil data latih diacak (aturan terpilih jadi acak), 5 kali.
"""
import argparse
import time

import numpy as np

import lulus_cari as lc
import lulus_cari2 as c2

DAY = 86400
KS = (1, 5, 20)


def pilih(D, t_d, rng=None):
    """Kembalikan daftar (nilai, en, e, i, j, li, lj, M) untuk hari uji yang mulai di t_d."""
    cand = []
    for en, d in D.items():
        s = d["seen"]
        tr = s + 21600 + lc.HOR + 600 <= t_d
        if tr.sum() < 400:
            continue
        cut = np.sort(s[tr])[int(tr.sum() * 0.6)]
        masks = {"W": tr & (s < cut), "P": tr & (s >= cut)}
        M, labs = lc.rules(d["X"], d["names"], masks["W"])
        if not len(labs):
            continue
        g = lc.grid(M, np.minimum(d["Y"], 10.0), masks, shuffle=rng)
        with np.errstate(invalid="ignore", divide="ignore"):
            NW, MW = g["W"][0], g["W"][1] / g["W"][0]
            NP, MP = g["P"][0], g["P"][1] / g["P"][0]
        ok = (NW >= 40) & (MW > 1.05) & (NP >= 25) & (MP > 1.0) & np.triu(np.ones(NW.shape[1:], bool))[None]
        idx = np.argwhere(ok)
        if not len(idx):
            continue
        sc = np.minimum(MW[ok], MP[ok])
        for k in np.argsort(-sc)[:max(KS)]:
            e, i, j = idx[k]
            cand.append((float(sc[k]), en, int(e), int(i), int(j), labs[i], labs[j], M))
    cand.sort(key=lambda c: -c[0])
    return cand[:max(KS)]


def dagang(D, picks, t_d, t_e):
    """Trade hari uji: (seen, hasil asli) tanpa koin ganda."""
    out, used = [], set()
    for sc, en, e, i, j, li, lj, M in picks:
        d = D[en]
        s = d["seen"]
        mk = (M[i] > 0) & (M[j] > 0) & (s >= t_d) & (s < t_e) & ~np.isnan(d["Y"][:, e])
        for r in np.where(mk)[0]:
            if s[r] in used:
                continue
            used.add(s[r])
            out.append((float(s[r]), float(d["Y"][r, e])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--set", type=int, default=3)
    ap.add_argument("--null", type=int, default=5)
    a = ap.parse_args()
    lc.HOR, lc.EXITS = c2.SETS[a.set]
    exn = list(lc.EXITS)
    toks, px, t_last = lc.load(a.data)
    toks = {m: x for m, x in toks.items() if not (lc.num(x.get("gt_fdv")) > 1e6)}
    D = lc.build(toks, px, t_last)
    t_min = min(d["seen"].min() for d in D.values())
    d0 = int(t_min // DAY) * DAY + DAY
    days = list(range(d0, int(t_last) + 1, DAY))
    f = lambda t: time.strftime("%d/%m", time.gmtime(t))
    print(f"\n## JALAN-MAJU set {a.set}: data {f(t_min)} - {f(t_last)}, {len(exn)} cara keluar, {len(D)} cara masuk", flush=True)
    allr = {K: [] for K in KS}
    nulr = [{K: [] for K in KS} for _ in range(a.null)]
    base = []
    nuji = 0
    for t_d in days:
        picks = pilih(D, t_d)
        if not picks:
            print(f"  {f(t_d)}: belum ada aturan yang lolos data latih, bot tidak beli", flush=True)
            continue
        nuji += 1
        d1 = D.get("M10") or next(iter(D.values()))
        bm = (d1["seen"] >= t_d) & (d1["seen"] < t_d + DAY) & ~np.isnan(d1["Y"][:, 0])
        base += [(float(s), float(y)) for s, y in zip(d1["seen"][bm], d1["Y"][bm, 0])]
        line = []
        for K in KS:
            tr = dagang(D, picks[:K], t_d, t_d + DAY)
            allr[K] += tr
            y = np.array([v for _, v in tr])
            line.append(f"K{K} n={len(y)} rata {y.mean():.3f}x" if len(y) else f"K{K} n=0")
        print(f"  {f(t_d)}: " + " | ".join(line) + f" | semua koin n={int(bm.sum())} rata "
              f"{d1['Y'][bm, 0].mean() if bm.sum() else float('nan'):.3f}x ({time.time() - lc.T0:.0f}s)", flush=True)
        for sc, en, e, i, j, li, lj, M in picks[:5]:
            print(f"       pilihan: {en} | {exn[e]} | {li if i == j else li + ' & ' + lj} | nilai latih {sc:.3f}x", flush=True)
        for q in range(a.null):
            pn = pilih(D, t_d, rng=np.random.default_rng(7000 + 100 * a.set + q))
            for K in KS:
                nulr[q][K] += dagang(D, pn[:K], t_d, t_d + DAY)
    print(f"\n## HASIL set {a.set} ({nuji} hari uji, hasil ASLI, urut waktu)", flush=True)
    base.sort()
    print(f"  dasar: beli SEMUA koin, masuk +10 menit | {exn[0]}: {lc.stat([v for _, v in base])}", flush=True)
    for K in KS:
        tr = sorted(allr[K])
        y = np.array([v for _, v in tr])
        if not len(y):
            print(f"  K={K}: tidak ada trade", flush=True)
            continue
        hari = {}
        for s, v in tr:
            hari.setdefault(int(s // DAY), []).append(v)
        up = sum(np.mean(v) > 1 for v in hari.values())
        ok = len(y) >= 30 and y.mean() > 1 and (y.sum() - y.max()) / (len(y) - 1) > 1 and up > len(hari) / 2
        print(f"  K={K}: {lc.stat(y)} | hari untung {up}/{len(hari)}{'  <== LULUS' if ok else ''}", flush=True)
        nl = []
        for q in range(a.null):
            yn = np.array([v for _, v in nulr[q][K]])
            nl.append(f"{yn.mean():.3f}x(n{len(yn)})" if len(yn) else "n0")
        print(f"       kontrol acak: {nl}", flush=True)
    print(f"[selesai] {time.time() - lc.T0:.0f}s", flush=True)


if __name__ == "__main__":
    main()

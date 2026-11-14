#!/usr/bin/env python3
"""gabungan: eksperimen gabungan semua sinyal kita, target koin yang bisa 2x. Uji jujur 4 periode waktu.

Data: rekaman memescan (data/rec), koin pump.fun kurva standar, trade 5 menit pertama + candle 30 menit.
Periode dibagi 4 sama panjang. Daftar wallet untuk koin di periode p SELALU dibangun dari periode < p saja
(tidak ada intip masa depan). P2 = latih model, P3 = pilih strategi, P4 = uji SEKALI.

E1  Kurva latency copy whale: sinyal >= N whale (daftar ketat whale_scan + daftar longgar top 2000 PnL),
    masuk 0 / 0,4 / 1 / 2 / 3 dtk setelah whale ke-N. Menjawab: secepat apa harus masuk biar untung.
E2  Jual ikut whale: keluar saat whale pemicu pertama jual (+latency), atau setengah whale pemicu sudah jual,
    plus pengaman SL -35%.
E3  Model gabungan (gradient boosting) di 4 titik umur (10/30/60/120 dtk) + saat sinyal whale 1-3:
    fitur aliran (beli/jual, SOL masuk, pembeli unik, pembeli terbesar, sniper awal, dev jual, momentum 10 dtk),
    harga (naik dari awal, jarak dari puncak), whale (ketat/longgar: jumlah, SOL, skor PnL), jam UTC.
    Target: hasil tiap cara jual (bot, TP 2x penuh, savip, tahan 60 dtk / 5 mnt) dan peluang tembus 2x.
    Ambil top 0,5-20% skor, satu trade per koin. Kontrol: label diacak (3 seed), pipeline sama.
Semua: latency default 3 dtk, fee 1,25%/sisi, slip 2%/sisi, priority 0,0005 SOL x2, isi stop haircut 0,72.
Lulus = di P4 n >= 30, rata-rata > 1 DAN rata-rata tanpa koin terbaik > 1, lebih baik dari null.

Pakai: python3 gabungan.py --data data --out out
"""
import argparse
import bisect
import collections
import json
import math
import os
import random
import time

import numpy as np

import memescan as ms
import whale_scan as ws

LATS = (0.0, 0.4, 1.0, 2.0, 3.0)
NS = (1, 2, 3, 5)
AGES = (10.0, 30.0, 60.0, 120.0)
QS = (0.005, 0.01, 0.02, 0.05, 0.10, 0.20)
EXITS = ("bot", "tp2", "savip", "tahan60", "tahan300")


def tp_exit(c, te, tp=2.0, sl=0.65, tmax=600):
    """Jual semua di TP 2x, SL -35% (isi haircut), time stop 10 mnt."""
    p_in = ws.price_at(c, te) * (1 + ws.SLIP)
    if p_in <= 0:
        return None
    for t, cl, hi, lo in ws.points(c, te):
        if t > c.end:
            break
        if lo / p_in <= sl:
            px = ws.price_at(c, t + ws.LAT)
            if t > c.cov:
                px = min(px, p_in * sl * 0.72)
            return ws.net(px / p_in)
        if hi / p_in >= tp:
            return ws.net(ws.price_at(c, t + ws.LAT) / p_in)
        if t - te >= tmax:
            return ws.net(ws.price_at(c, t + ws.LAT) / p_in)
    return ws.net(ws.end_price(c) / p_in)


def hit2(c, te, tmax=1800):
    p_in = ws.price_at(c, te) * (1 + ws.SLIP)
    if p_in <= 0:
        return 0
    for t, cl, hi, lo in ws.points(c, te):
        if t - te > tmax or t > c.end:
            break
        if hi / p_in >= 2.0:
            return 1
    return 0


def all_exits(c, te):
    return {"bot": ws.bot_exit(c, te), "tp2": tp_exit(c, te), "savip": ws.savip_exit(c, te),
            "tahan60": ws.hold_exit(c, te, 60), "tahan300": ws.hold_exit(c, te, 300)}


def mirror_exit(c, te, sells, frac):
    """Keluar setelah `frac` dari whale pemicu sudah jual (waktu jual + latency); SL -35% tetap jalan."""
    p_in = ws.price_at(c, te) * (1 + ws.SLIP)
    if p_in <= 0:
        return None
    known = sorted(s for s in sells if s is not None)
    need = max(1, math.ceil(len(sells) * frac))
    t_sell = known[need - 1] + ws.LAT if len(known) >= need else None
    for t, cl, hi, lo in ws.points(c, te):
        if t > c.end:
            break
        if t_sell is not None and t >= t_sell:
            return ws.net(ws.price_at(c, t_sell) / p_in)
        if lo / p_in <= 0.65:
            px = ws.price_at(c, t + ws.LAT)
            if t > c.cov:
                px = min(px, p_in * 0.65 * 0.72)
            return ws.net(px / p_in)
    if t_sell is not None and t_sell <= c.end:
        return ws.net(ws.price_at(c, t_sell) / p_in)
    return ws.net(ws.end_price(c) / p_in)


FEATS = ["umur", "naik_log", "dari_puncak", "n_beli", "n_jual", "pembeli_unik", "sol_beli", "sol_jual",
         "sol_bersih", "pembeli_terbesar", "sniper_awal", "dev_jual", "sol_beli_10s", "n_trade_10s",
         "diam_s", "wk_n", "wk_sol", "wl_n", "wl_sol", "wl_skor", "jam_utc", "titik_whale"]


def features(c, t, strict, loose, score, kind):
    p_now = ws.price_at(c, t)
    nb = ns_ = 0
    bsol = ssol = 0.0
    per_buyer = collections.Counter()
    snipe = 0.0
    dev_sold = 0
    b10 = 0.0
    n10 = 0
    last = 0.0
    peak = c.m0
    wk, wks, wl, wls, wsc = set(), 0.0, set(), 0.0, 0.0
    dev = (c.dev or "")[:10]
    k = bisect.bisect_right(c.tt, t)
    if k:
        peak = max(peak, max(c.tp[:k]))
    for ag, w, isb, sol in c.w:
        if ag > t or ag > c.cov:
            break
        last = ag
        if ag >= t - 10:
            n10 += 1
        if isb:
            nb += 1
            bsol += sol
            per_buyer[w] += sol
            if ag <= 2:
                snipe += sol
            if ag >= t - 10:
                b10 += sol
            if w in strict:
                wk.add(w)
                wks += sol
            if w in loose:
                if w not in wl:
                    wsc += score.get(w, 0.0)
                wl.add(w)
                wls += sol
        else:
            ns_ += 1
            ssol += sol
            if dev and w == dev:
                dev_sold = 1
    top = max(per_buyer.values()) / bsol if bsol > 0 else 0.0
    return [t, math.log(max(p_now, 1e-9) / c.m0), p_now / peak if peak > 0 else 1.0, nb, ns_, len(per_buyer),
            bsol, ssol, bsol - ssol, top, snipe / bsol if bsol > 0 else 0.0, dev_sold, b10, n10, t - last,
            len(wk), wks, len(wl), wls, wsc, time.gmtime(c.t0).tm_hour, kind]


def mstat(xs):
    return ws.mstat(xs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    T = time.time()
    os.makedirs(a.out, exist_ok=True)
    files = ws.rec_files(a.data)
    # langkah 1-2 seperti whale_scan
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
    del cnt
    span = (t_hi - t_lo) / ws.NPER

    def period_of(t):
        return min(ws.NPER - 1, int((t - t_lo) // span))

    acc = {}
    ws.scan(a.data, files, t_lo, t_hi, cand, dev_n, acc, period_of)
    print(f"[1] {n_coins} koin, {len(acc)} wallet dicek ({time.time() - T:.0f}s)", flush=True)
    # daftar per periode (dibangun dari periode sebelumnya saja)
    strict, loose, score = {}, {}, {}
    for p in (1, 2, 3):
        strict[p] = {w for w, _ in ws.build_list(acc, dev_n, range(p))[0]}
        ll = ws.loose_list(acc, dev_n, range(p), 0.2)[:2000]
        loose[p] = {w for _, w in ll}
        score[p] = {w: math.log1p(max(0.0, pnl)) for pnl, w in ll}
        print(f"[daftar P{p + 1}] ketat {len(strict[p])}, longgar {len(loose[p])}", flush=True)
    del acc

    # E1/E2 hasil: key (periode, daftar, N, lat, exit) -> [mult]
    e1 = collections.defaultdict(list)
    X, Y, H, P, CID = [], {e: [] for e in EXITS}, [], [], []
    coin_i = 0
    for c in ws.iter_coins(a.data, files):
        p = period_of(c.t0)
        if p == 0:
            continue
        coin_i += 1
        ws.build_path(c)
        cw = ws.coin_wallets(c)
        order = sorted((v[0], w) for w, v in cw.items())
        trig_times = {}
        for nm, L in (("ketat", strict[p]), ("longgar", loose[p])):
            hit = [(ag, w) for ag, w in order if w in L]
            for n in NS:
                if len(hit) < n:
                    continue
                t_n = hit[n - 1][0]
                if nm == "longgar" and n <= 3:
                    trig_times[n] = t_n
                for lat in LATS:
                    ws.LAT = lat
                    te = t_n + lat
                    if te >= c.end:
                        continue
                    for e, v in (("bot", ws.bot_exit(c, te)), ("tp2", tp_exit(c, te)),
                                 ("savip", ws.savip_exit(c, te)), ("tahan300", ws.hold_exit(c, te, 300))):
                        e1[(p, nm, n, lat, e)].append(v)
                    if lat in (0.4, 3.0):
                        sells = [cw[w][4] for _, w in hit[:n]]
                        e1[(p, nm, n, lat, "ikut_whale_1")].append(mirror_exit(c, te, sells, 0.01))
                        e1[(p, nm, n, lat, "ikut_whale_50%")].append(mirror_exit(c, te, sells, 0.5))
        ws.LAT = 3.0
        # E3 baris
        pts = [(t, 0) for t in AGES] + [(t, n) for n, t in trig_times.items()]
        for t, kind in pts:
            te = t + ws.LAT
            if te >= c.end or t > c.cov:
                continue
            X.append(features(c, t, strict[p], loose[p], score[p], kind))
            ex = all_exits(c, te)
            for e in EXITS:
                Y[e].append(ex[e] if ex[e] is not None else np.nan)
            H.append(hit2(c, te))
            P.append(p)
            CID.append(coin_i)
        c.tt = c.tp = None
    print(f"[2] E1/E2 selesai, E3 {len(X)} baris ({time.time() - T:.0f}s)", flush=True)

    out = {"data": {"koin": n_coins, "dari": time.strftime("%Y-%m-%d %H:%M", time.gmtime(t_lo)),
                    "sampai": time.strftime("%Y-%m-%d %H:%M", time.gmtime(t_hi)),
                    "batas_periode": [time.strftime("%m-%d %H:%M", time.gmtime(t_lo + i * span)) for i in range(5)]}}

    # ---- E1/E2 laporan + pilih di P3, uji P4
    tab = []
    for (p, nm, n, lat, e), xs in e1.items():
        tab.append(dict(P=p + 1, daftar=nm, N=n, lat=lat, exit=e, **mstat(xs)))
    tab.sort(key=lambda r: (r["daftar"], r["N"], r["exit"], r["lat"], r["P"]))
    out["E1_latency_tabel"] = tab
    print("[E1] kurva latency (rata-rata per trade), P3 | P4:", flush=True)
    by = {(r["P"], r["daftar"], r["N"], r["lat"], r["exit"]): r for r in tab}
    for nm in ("ketat", "longgar"):
        for n in NS:
            for e in ("bot", "tp2", "savip", "tahan300", "ikut_whale_1", "ikut_whale_50%"):
                cells = []
                for lat in LATS:
                    r3, r4 = by.get((3, nm, n, lat, e)), by.get((4, nm, n, lat, e))
                    if r3 or r4:
                        f = lambda r: f"{r['mean']:.3f}/n{r['n']}" if r and r.get("n") else "-"  # noqa: E731
                        cells.append(f"{lat}s {f(r3)} | {f(r4)}")
                if cells:
                    print(f"  {nm} N{n} {e}: " + " ; ".join(cells), flush=True)
    picks = [r for r in tab if r["P"] == 3 and r.get("n", 0) >= 30 and r["lat"] >= 0.4
             and r["mean_wo_best"] is not None and r["mean_wo_best"] > 1.0]
    picks.sort(key=lambda r: -r["mean_wo_best"])
    res = []
    for r in picks[:10]:
        r4 = by.get((4, r["daftar"], r["N"], r["lat"], r["exit"]), {})
        res.append({"P3": r, "P4": r4})
    out["E1E2_pilih_P3_uji_P4"] = res
    print(f"[E1/E2] lolos P3 (n>=30, lat>=0,4 dtk, tanpa koin terbaik >1): {len(picks)}", flush=True)
    for x in res:
        print(f"  {x['P3']['daftar']} N{x['P3']['N']} {x['P3']['exit']} lat {x['P3']['lat']}: "
              f"P3 {x['P3']['mean']} -> P4 {x['P4']}", flush=True)

    # ---- E3 model gabungan
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    X = np.array(X, dtype=float)
    P = np.array(P)
    CID = np.array(CID)
    H = np.array(H)
    Ys = {e: np.array(v, dtype=float) for e, v in Y.items()}
    tr, pk, te_ = P == 1, P == 2, P == 3
    print(f"[E3] baris latih {tr.sum()}, pilih {pk.sum()}, uji {te_.sum()}; tembus 2x: latih "
          f"{H[tr].mean():.3f}, uji {H[te_].mean():.3f}", flush=True)
    base = {e: mstat(list(Ys[e][te_ & (X[:, 0] == 30)])) for e in EXITS}
    out["E3_beli_semua_umur30_P4"] = base
    print(f"[E3] beli semua umur 30 dtk di P4: {base}", flush=True)

    def first_per_coin(mask, s):
        """satu trade per koin: titik pertama (urut umur) yang skornya lolos."""
        idx = np.where(mask)[0]
        idx = idx[np.lexsort((X[idx, 0], CID[idx]))]
        seen, keep = set(), []
        for i in idx:
            if CID[i] in seen:
                continue
            seen.add(CID[i])
            keep.append(i)
        return np.array(sorted(keep, key=lambda i: (CID[i], X[i, 0])), dtype=int)

    def run_models(y_shuffle_seed=None):
        rows = []
        targets = {f"reg_{e}": Ys[e] for e in EXITS}
        targets["kls_2x"] = H
        for tn, y in targets.items():
            m = tr & ~np.isnan(y if tn != "kls_2x" else H.astype(float))
            yt = y[m].copy()
            if y_shuffle_seed is not None:
                np.random.default_rng(y_shuffle_seed).shuffle(yt)
            if tn == "kls_2x":
                mdl = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05, max_leaf_nodes=31,
                                                     min_samples_leaf=300, random_state=1)
                mdl.fit(X[m], yt.astype(int))
                sc = mdl.predict_proba(X)[:, 1]
            else:
                mdl = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05, max_leaf_nodes=31,
                                                    min_samples_leaf=300, random_state=1)
                mdl.fit(X[m], np.minimum(yt, 3.0))
                sc = mdl.predict(X)
            for q in QS:
                thr = np.quantile(sc[pk], 1 - q)
                i3 = first_per_coin(pk & (sc >= thr), sc)
                i4 = first_per_coin(te_ & (sc >= thr), sc)
                for e in EXITS:
                    s3 = mstat([v for v in Ys[e][i3] if not np.isnan(v)])
                    s4 = mstat([v for v in Ys[e][i4] if not np.isnan(v)])
                    rows.append(dict(model=tn, top=q, exit=e, P3=s3, P4=s4,
                                     hit2_P3=round(float(H[i3].mean()), 3) if len(i3) else None,
                                     hit2_P4=round(float(H[i4].mean()), 3) if len(i4) else None))
        return rows

    rows = run_models()
    ok3 = [r for r in rows if r["P3"].get("n", 0) >= 30 and (r["P3"].get("mean_wo_best") or 0) > 1.0]
    ok3.sort(key=lambda r: -r["P3"]["mean_wo_best"])
    best_by_p3 = sorted([r for r in rows if r["P3"].get("n", 0) >= 30],
                        key=lambda r: -(r["P3"].get("mean_wo_best") or 0))[:10]
    out["E3_jumlah_strategi"] = len(rows)
    out["E3_lolos_P3"] = len(ok3)
    out["E3_top10_P3_dan_P4"] = best_by_p3
    print(f"[E3] {len(rows)} strategi model; lolos P3: {len(ok3)}", flush=True)
    for r in best_by_p3:
        print(f"  {r['model']} top{r['top']} {r['exit']}: P3 {r['P3']} hit2 {r['hit2_P3']} | P4 {r['P4']} "
              f"hit2 {r['hit2_P4']}", flush=True)
    nulls = []
    for seed in (1, 2, 3):
        nr = run_models(seed)
        b = sorted([r for r in nr if r["P3"].get("n", 0) >= 30], key=lambda r: -(r["P3"].get("mean_wo_best") or 0))
        nulls.append({"lolos_P3": sum(1 for r in b if (r["P3"].get("mean_wo_best") or 0) > 1.0),
                      "top3": [dict(model=r["model"], top=r["top"], exit=r["exit"], P3=r["P3"], P4=r["P4"])
                               for r in b[:3]]})
        print(f"[E3 null seed {seed}] lolos P3 {nulls[-1]['lolos_P3']}; top: "
              + " ; ".join(f"{x['model']} {x['exit']} P3 {x['P3'].get('mean')} P4 {x['P4'].get('mean')}"
                           for x in nulls[-1]["top3"]), flush=True)
    out["E3_null"] = nulls
    # peluang 2x per desil skor model kls_2x di P4 (deskriptif)
    out["durasi_s"] = round(time.time() - T)
    with open(os.path.join(a.out, "gabungan.json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    print(f"[selesai] {time.time() - T:.0f}s", flush=True)


if __name__ == "__main__":
    main()

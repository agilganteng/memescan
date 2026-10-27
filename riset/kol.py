"""Uji besar copy KOL (27 Okt 2026): kalau kita beli SETELAH wallet KOL beli, lalu jual ke follower yang masuk
belakangan, untung atau tidak? Pertanyaan dari post X @A_Pirate_I ("SNIPER buys, fills in 0.4 seconds").

Data: rekaman perekam memescan, semua trade beli/jual di 5 menit pertama tiap koin pump.fun (maks 150 trade/koin,
umur trade 0,1 dtk), plus candle 5/15/60 dtk sampai 30 menit. Wallet KOL: 93 alamat leaderboard kolscan
(riset/kol_wallets.txt), dicocokkan lewat 10 huruf pertama alamat (yang disimpan perekam).

Harga tiap trade direkonstruksi dari kurva pump.fun (x*y=k): mcap = v_sol^2 / 32,19, v_sol berubah sebesar SOL tiap
beli/jual. Jangkar = close candle terakhir yang SUDAH selesai sebelum KOL beli (tidak mengintip masa depan).
Jadi kita bisa uji jeda masuk yang sangat kecil:
  0 dtk   : tepat sesudah transaksi KOL di blok yang sama. MUSTAHIL di Solana (tidak ada mempool publik), hanya
            batas atas teori.
  0,4 dtk : 1 slot. Butuh infrastruktur mahal (RPC/gRPC privat, Jito tip), ini klaim bot "0.4 seconds".
  1 / 3 / 9 dtk : bot copy-trade biasa (GMGN, fomo, bot Telegram).
Jual: ikut jual saat KOL jual, TP/SL, trailing stop, atau tahan beberapa detik saja ("jual ke follower").
Biaya: fee 1,25% atau 3% per sisi, priority fee 0,0005 SOL per transaksi, dampak harga ukuran kita (0,1 SOL) di kurva.
Kurva tidak standar dibuang TANPA info masa depan (cek snapshot sebelum sinyal, sama dengan riset luas --floor std).

Pembagian waktu: A (50% sinyal paling lama) nilai tiap KOL | B (20%) pilih aturan | C (30% paling baru) uji sekali
+ simulasi $200. Pembanding: copy wallet acak non-KOL dengan ukuran beli & umur koin mirip.

Pakai: python3 riset/kol.py --data data
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

K_CURVE = 30.0 * 1.073e9 / 1e9          # mcap (SOL) = v_sol^2 / K_CURVE
SIZE = 0.1                              # SOL per trade (~$20)
PRIO = 0.0005
COSTS = {"1,25%": 0.0125, "3%": 0.03}
LATS = (0.0, 0.4, 1.0, 3.0, 9.0)
START, STAKE_PCT, MAX_STAKE = 200.0, 0.10, 20.0
FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}
FLOOR_MCAP = 27.0

EXITS = {"ikut jual KOL (maks 30 mnt)": dict(follow=True, T=1800)}
for hold in (5, 10, 20, 30, 60, 120):
    EXITS[f"tahan {hold} dtk"] = dict(T=hold)
for tp in (1.2, 1.5, 2.0, 3.0):
    for sl in (0.2, 0.35, 0.5):
        for T in (60, 300, 900):
            EXITS[f"TP {tp}x SL {sl:.0%} maks {T}s"] = dict(tp=tp, sl=sl, T=T)
for arm in (0.0, 0.3, 1.0):
    for tr in (0.15, 0.3, 0.5):
        for T in (300, 1800):
            EXITS[f"trail {tr:.0%} aktif +{arm:.0%} maks {T}s"] = dict(arm=arm, trail=tr, sl=0.5, T=T)
for T in (60, 300, 900):
    EXITS[f"ikut jual KOL atau SL 35% maks {T}s"] = dict(follow=True, sl=0.35, T=T)


class Coin:
    __slots__ = ("t0", "end", "m0", "cs", "starts", "w", "cov", "kfrom", "kbad", "tbad")


def load(data_dir):
    d = os.path.join(data_dir, "rec")
    coins = []
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if not r.get("w"):
                        continue
                    c = Coin()
                    c.t0, c.end = float(r["t0"]), float(r["end"])
                    c.m0 = float(r.get("m0") or r["snaps"][0][1])
                    c.cs = [(ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), float(x[1]), float(x[2]),
                             float(x[3])) for x in r["c"]]
                    if not c.cs or c.m0 <= 0:
                        continue
                    c.starts = [x[0] for x in c.cs]
                    c.w = [(float(a), w, int(b), float(s)) for a, w, b, s in r["w"]]
                    c.cov = c.w[-1][0] if len(c.w) >= ms.REC_W_MAX else min(ms.REC_W_AGE, c.end)
                    # Kurva tidak standar, dicek kausal: detik pertama terlihat buruk (inf = tidak pernah).
                    tb = min([x[1] for x in c.cs if x[3] < FLOOR_MCAP] +
                             [float(s[0]) for s in r["snaps"] if float(s[1]) < FLOOR_MCAP] + [math.inf])
                    kb, kf, ib = math.inf, math.inf, math.inf
                    for sn in r["snaps"]:
                        liq, mc, ag = float(sn[FI["liq_sol"]]), float(sn[1]), float(sn[0])
                        if sn[FI["inflow_sol"]] == 0 and sn[FI["growth"]] > 1.05:
                            ib = min(ib, ag)
                        if liq >= 79 or mc <= 0:
                            continue
                        kf = min(kf, ag)
                        if abs((30 + liq) ** 2 * 1e9 / mc / 3.219e10 - 1) > 0.08:
                            kb = min(kb, ag)
                    c.kfrom, c.kbad, c.tbad = kf, min(kb, ib), tb
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                coins.append(c)
    coins.sort(key=lambda c: c.t0)
    return coins


def candle_close(c, t):
    i = bisect.bisect_right(c.starts, t) - 1
    return c.cs[i][4] if i >= 0 else c.m0


class Path:
    """Harga mulai dari jangkar sebelum trade ke-j: titik tick hasil rekonstruksi, lalu candle setelah cakupan."""

    def __init__(self, c, j):
        a = c.w[j][0]
        k = bisect.bisect_right([x[1] for x in c.cs], a) - 1      # candle terakhir yang selesai <= a
        if k >= 0:
            b_end, p_anc = c.cs[k][1], c.cs[k][4]
        else:
            b_end, p_anc = 0.0, c.m0
        v = math.sqrt(K_CURVE * p_anc)
        self.anchor = p_anc
        self.tt, self.tp = [], []
        # Close tiap candle = harga absolut nyata. Setelah semua trade sampai akhir candle diterapkan, harga dipasang
        # ulang ke close itu, supaya trade yang terlewat perekam (RPC putus) tidak membuat jalur harga melenceng.
        ends = [(x[1], x[4]) for x in c.cs if x[1] > b_end and x[1] <= c.cov]
        q = 0
        for i, (ag, _, isb, sol) in enumerate(c.w):
            if ag <= b_end and i < j:
                continue
            if ag > c.cov:
                break
            while q < len(ends) and ends[q][0] < ag:
                v = math.sqrt(K_CURVE * ends[q][1])
                self.tt.append((ends[q][0], -1))
                self.tp.append(ends[q][1])
                q += 1
            v = v + sol if isb else max(1e-6, v - sol)
            self.tt.append((ag, i))
            self.tp.append(v * v / K_CURVE)
        self.c, self.j = c, j
        self.cand = [x for x in c.cs if x[0] >= c.cov]

    def entry(self, lat):
        """Harga setelah semua trade sampai indeks j, plus trade sesudahnya yang umurnya <= umur KOL + jeda."""
        c, j = self.c, self.j
        a = c.w[j][0]
        p = self.anchor
        for (ag, i), pr in zip(self.tt, self.tp):
            if (0 <= i <= j) or (ag <= a and i < 0) or ag <= a + lat:
                p = pr
            else:
                break
        if a + lat > c.cov:
            p = candle_close(c, a + lat)
        return p

    def price_at(self, t):
        if t <= self.c.cov:
            k = bisect.bisect_right(self.tt, (t, 10 ** 9)) - 1
            return self.tp[k] if k >= 0 else self.anchor
        return candle_close(self.c, t)

    def points(self, t_from):
        """(t, close, hi, lo) setelah t_from."""
        k = bisect.bisect_right(self.tt, (t_from, 10 ** 9))
        for (ag, _), pr in zip(self.tt[k:], self.tp[k:]):
            yield ag, pr, pr, pr
        for a, b, hi, lo, cl in self.cand:
            if b > t_from:
                yield b, cl, hi, lo


def sim(path, lat, ex, sell_ts):
    """Return (harga masuk mentah, harga keluar mentah, umur keluar) tanpa biaya, atau None."""
    c = path.c
    a = c.w[path.j][0]
    te = a + lat
    if te >= c.end:
        return None
    p_in = path.entry(lat)
    if p_in <= 0:
        return None
    lx = max(lat, 0.4)
    cfg = EXITS[ex]
    sl = p_in * (1 - cfg["sl"]) if cfg.get("sl") else -1.0
    tp = p_in * cfg["tp"] if cfg.get("tp") else math.inf
    t_lim = te + cfg["T"]
    fol = next((t for t in sell_ts if t > a), None) if cfg.get("follow") else None
    peak, armed = p_in, cfg.get("arm") == 0.0
    for t, cl, hi, lo in path.points(te):
        if t >= t_lim:
            return p_in, path.price_at(t_lim + lx), t_lim + lx
        if fol is not None and t >= fol:
            return p_in, path.price_at(fol + lx), fol + lx
        stop = max(sl, peak * (1 - cfg["trail"])) if armed else sl
        if lo <= stop:
            return p_in, min(stop, path.price_at(t + lx)), t + lx
        if hi >= tp:
            # tick: jual di harga nyata setelah jeda | candle: anggap terisi tepat di level TP
            return p_in, (path.price_at(t + lx) if hi == lo else tp), t + lx
        peak = max(peak, hi)
        if "trail" in cfg:
            armed = armed or peak >= p_in * (1 + cfg["arm"])
    if fol is not None and fol < c.end:
        return p_in, path.price_at(fol + lx), fol + lx
    return p_in, path.price_at(c.end), c.end


def mult(p_in, p_out, cost):
    f = COSTS[cost]
    e = p_in * (1 + SIZE / ms.v_sol_at(p_in)) / (1 - f)
    s = p_out * (1 - f) / (1 + SIZE / ms.v_sol_at(max(p_out, 1e-9)))
    return s / e - 2 * PRIO / SIZE


def sim200(tr):
    eq, busy, n, w, peak, mdd = START, -1.0, 0, 0, START, 0.0
    for t, x, tx in sorted(tr):
        if t < busy:
            continue
        stake = min(eq * STAKE_PCT, MAX_STAKE)
        eq += stake * (x - 1)
        busy, n, w = tx, n + 1, w + (x > 1)
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    return eq, n, w, mdd


def wilson(k, n):
    return ms.wilson(k, n) if n else (float("nan"), float("nan"))


def report(label, xs_tr):
    """xs_tr: list (t_abs, x, t_abs_keluar)."""
    if not xs_tr:
        return f"  {label}: 0 trade"
    xs = np.array([x for _, x, _ in xs_tr])
    n = len(xs)
    lo = xs.mean() - 1.96 * xs.std(ddof=1) / math.sqrt(n) if n > 1 else float("nan")
    eq, n2, w2, mdd = sim200(xs_tr)
    ci = wilson(w2, n2)
    tag = "" if n >= 30 else "  (<30 trade, tidak bisa disimpulkan)"
    return (f"  {label}: {n} sinyal, rata {xs.mean():.3f}x (CI bawah {lo:.3f}), median {np.median(xs):.3f}x, "
            f"menang {(xs > 1).mean():.0%} | $200 sim: {n2} trade, menang {w2 / max(n2, 1):.0%} "
            f"(CI {ci[0]:.0%}-{ci[1]:.0%}), akhir ${eq:.2f}, MDD {mdd:.0%}{tag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--kol", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "kol_wallets.txt"))
    a = ap.parse_args()
    t_start = time.time()
    kol = {}
    for ln in open(a.kol):
        if ln.strip() and not ln.startswith("#"):
            addr, *nm = ln.split()
            kol[addr[:10]] = nm[0] if nm else addr[:6]
    coins = load(a.data)
    if not coins:
        print("Tidak ada data rekaman wallet.")
        return
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"== {len(coins):,} koin pump.fun dengan rekaman wallet, {ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC. "
          f"{len(kol)} wallet KOL kolscan. Baca {time.time() - t_start:.0f} dtk.")

    # ---------- validasi: dari close candle sebelumnya + trade di candle ini, apakah sama dengan close candle ini?
    errs = []
    for c in coins[:: max(1, len(coins) // 20000)]:
        if not (c.kfrom < math.inf and c.kbad == math.inf and c.tbad == math.inf):
            continue
        for k in range(1, len(c.cs)):
            e0, e1 = c.cs[k - 1][1], c.cs[k][1]
            if e1 > c.cov or c.cs[k][0] != e0:
                continue
            v = math.sqrt(K_CURVE * c.cs[k - 1][4])
            for ag, w, isb, sol in c.w:
                if e0 < ag <= e1:
                    v = v + sol if isb else max(1e-6, v - sol)
            errs.append(abs(v * v / K_CURVE / c.cs[k][4] - 1))
    if errs:
        e = np.array(errs)
        print(f"   Cek rekonstruksi harga per candle ({len(e):,} candle, koin kurva standar): median selisih "
              f"{np.median(e):.2%}, > 10% di {np.mean(e > 0.10):.1%} candle (sisa selisih dikoreksi di tiap close).")

    # ---------- kejadian KOL beli (beli pertama tiap KOL per koin) + jual KOL
    ev, n_bad, n_early, early = [], 0, 0, []
    n_kol_coins = 0
    per_kol = {}
    for ci, c in enumerate(coins):
        first, sells = {}, {}
        for j, (ag, w, isb, sol) in enumerate(c.w):
            if w not in kol:
                continue
            if isb and w not in first:
                first[w] = j
            elif not isb:
                sells.setdefault(w, []).append(ag)
        if first:
            n_kol_coins += 1
        order = sorted(first.items(), key=lambda kv: kv[1])
        for rank, (w, j) in enumerate(order):
            ag = c.w[j][0]
            if not (c.kfrom <= ag < c.kbad and ag < c.tbad):
                n_bad += 1
                n_early += ag < c.kfrom
                if ag < c.kfrom and c.kbad == math.inf and c.tbad == math.inf and c.kfrom < math.inf:
                    early.append(dict(ci=ci, j=j, w=w, age=ag, sol=c.w[j][3], t=c.t0 + ag,
                                      sells=sorted(sells.get(w, []))))
                continue
            ev.append(dict(ci=ci, j=j, w=w, rank=rank + 1, age=ag, sol=c.w[j][3], t=c.t0 + ag,
                           sells=sorted(sells.get(w, []))))
            per_kol[w] = per_kol.get(w, 0) + 1
    print(f"   KOL beli di 5 menit pertama: {len(ev):,} kejadian di {n_kol_coins:,} koin, dari {len(per_kol)} KOL "
          f"({n_bad} dibuang: {n_early} karena beli sebelum snapshot pertama umur 10 dtk sehingga kurva belum bisa dicek, "
          f"sisanya kurva tidak standar).")
    if len(ev) < 60:
        print("   Terlalu sedikit untuk diuji.")
        return
    top = sorted(per_kol.items(), key=lambda kv: -kv[1])[:15]
    print("   Paling sering: " + ", ".join(f"{kol[w]} {n}" for w, n in top))
    ages = np.array([e["age"] for e in ev])
    sols = np.array([e["sol"] for e in ev])
    print(f"   Umur koin saat KOL beli: median {np.median(ages):.1f} dtk, <2 dtk {np.mean(ages < 2):.0%}, "
          f"<10 dtk {np.mean(ages < 10):.0%}. Ukuran beli median {np.median(sols):.2f} SOL.")

    # ---------- seberapa cepat harga lari setelah KOL beli
    paths = {}
    for k, e in enumerate(ev):
        paths[k] = Path(coins[e["ci"]], e["j"])
    print("\n== Harga setelah KOL beli (dibanding harga tepat sesudah transaksi KOL, sebelum biaya):")
    base = np.array([paths[k].entry(0.0) for k in range(len(ev))])
    for dt in (0.4, 1, 3, 9, 30, 60, 300):
        r = np.array([paths[k].price_at(ev[k]["age"] + dt) for k in range(len(ev))]) / base
        print(f"   +{dt:>5} dtk: median {np.median(r):.3f}x, rata {np.mean(r):.3f}x, naik >10% {np.mean(r > 1.1):.0%}, "
              f"turun >10% {np.mean(r < 0.9):.0%}")

    # ---------- simulasi semua kejadian x jeda x exit (tanpa biaya; biaya dipasang belakangan)
    t1 = time.time()
    R = {}
    for k, e in enumerate(ev):
        for L in LATS:
            for ex in EXITS:
                r = sim(paths[k], L, ex, e["sells"])
                if r:
                    R[(k, L, ex)] = r
    print(f"\n   {len(R):,} simulasi trade dalam {time.time() - t1:.0f} dtk.")

    def trades(idx, L, ex, cost):
        out = []
        for k in idx:
            r = R.get((k, L, ex))
            if r:
                c = coins[ev[k]["ci"]]
                out.append((c.t0 + ev[k]["age"] + L, mult(r[0], r[1], cost), c.t0 + r[2]))
        return out

    # ---------- semua KOL, tanpa pilih-pilih (tidak ada parameter yang dicocokkan ke data selain exit)
    allk = list(range(len(ev)))
    print("\n== SEMUA KOL, beli pertama tiap KOL, seluruh periode (biaya 1,25%/sisi):")
    for L in LATS:
        best = max(EXITS, key=lambda ex: np.mean([x for _, x, _ in trades(allk, L, ex, "1,25%")] or [0]))
        print(f" jeda {L} dtk{' (MUSTAHIL, batas atas)' if L == 0 else ''}:")
        for ex in ("ikut jual KOL (maks 30 mnt)", "tahan 10 dtk", "tahan 60 dtk", "TP 2.0x SL 35% maks 300s", best):
            print(report(f"{ex}{' [exit terbaik, dipilih setelah lihat data]' if ex == best else ''}",
                         trades(allk, L, ex, "1,25%")))

    # ---------- KOL beli < 10 dtk (sniper). Kurva dicek pakai SELURUH data koin (info masa depan): hasil di sini
    # cenderung TERLALU BAGUS (koin yang belakangan ketahuan tidak standar sudah dibuang), jadi hanya batas atas.
    if early:
        ea = np.array([e["age"] for e in early])
        print(f"\n== KOL BELI < 10 DTK: {len(early):,} kejadian (median umur {np.median(ea):.1f} dtk). Kurva dicek pakai "
              f"info masa depan, jadi hasil ini TERLALU OPTIMIS (batas atas). Biaya 1,25%/sisi:")
        ep = [Path(coins[e["ci"]], e["j"]) for e in early]
        base_e = np.array([p.entry(0.0) for p in ep])
        for dt in (0.4, 1, 3, 9, 60):
            r = np.array([p.price_at(e["age"] + dt) for p, e in zip(ep, early)]) / base_e
            print(f"   harga +{dt} dtk: median {np.median(r):.3f}x, rata {np.mean(r):.3f}x")
        for L in LATS:
            res = {}
            for ex in EXITS:
                tr = []
                for p, e in zip(ep, early):
                    r = sim(p, L, ex, e["sells"])
                    if r:
                        tr.append((p.c.t0 + e["age"] + L, mult(r[0], r[1], "1,25%"), p.c.t0 + r[2]))
                res[ex] = tr
            best = max(res, key=lambda ex: np.mean([x for _, x, _ in res[ex]] or [0]))
            n_pos = sum(bool(v) and np.mean([x for _, x, _ in v]) > 1 for v in res.values())
            print(f" jeda {L} dtk{' (MUSTAHIL)' if L == 0 else ''}: {n_pos} dari {len(EXITS)} cara jual rata-rata untung")
            for ex in ("tahan 10 dtk", "TP 2.0x SL 35% maks 300s", best):
                print(report(f"{ex}{' [terbaik, dipilih setelah lihat data]' if ex == best else ''}", res[ex]))

    # ---------- pembanding: wallet acak non-KOL, umur & ukuran beli mirip
    rng = random.Random(7)
    pool = {}
    for ci, c in enumerate(coins):
        seen = set()
        for j, (ag, w, isb, sol) in enumerate(c.w):
            if not isb or w in kol or w in seen:
                continue
            seen.add(w)
            if c.kfrom <= ag < c.kbad and ag < c.tbad:
                key = (min(int(ag // 5), 59), int(round(math.log2(max(sol, 0.01)))))
                pool.setdefault(key, []).append((ci, j))
    ctrl = []
    for e in ev:
        key = (min(int(e["age"] // 5), 59), int(round(math.log2(max(e["sol"], 0.01)))))
        if pool.get(key):
            ci, j = rng.choice(pool[key])
            ctrl.append((ci, j))
    print(f"\n== PEMBANDING: {len(ctrl):,} beli wallet acak non-KOL (umur koin & ukuran beli mirip), biaya 1,25%:")
    for L in (0.4, 3.0):
        for ex in ("tahan 10 dtk", "tahan 60 dtk", "TP 2.0x SL 35% maks 300s"):
            xs = []
            for ci, j in ctrl:
                c = coins[ci]
                r = sim(Path(c, j), L, ex, [])
                if r:
                    xs.append((c.t0 + c.w[j][0] + L, mult(r[0], r[1], "1,25%"), c.t0 + r[2]))
            kx = trades(allk, L, ex, "1,25%")
            print(f"   jeda {L} dtk, {ex}: KOL rata {np.mean([x for _, x, _ in kx]):.3f}x vs acak "
                  f"{np.mean([x for _, x, _ in xs]):.3f}x")

    # ---------- A/B/C: nilai KOL di A, pilih aturan di B, uji sekali di C
    order = sorted(range(len(ev)), key=lambda k: ev[k]["t"])
    nA, nB = int(len(order) * 0.5), int(len(order) * 0.7)
    A, B, C = order[:nA], order[nA:nB], order[nB:]
    print(f"\n== A nilai KOL {ts(ev[A[0]]['t'])}-{ts(ev[A[-1]]['t'])} ({len(A)}) | B pilih {ts(ev[B[0]]['t'])}-"
          f"{ts(ev[B[-1]]['t'])} ({len(B)}) | C uji {ts(ev[C[0]]['t'])}-{ts(ev[C[-1]]['t'])} ({len(C)}) UTC")
    good = {}
    for L in LATS:
        s = {}
        for k in A:
            r = R.get((k, L, "ikut jual KOL (maks 30 mnt)"))
            if r:
                s.setdefault(ev[k]["w"], []).append(mult(r[0], r[1], "1,25%"))
        good[L] = {w for w, v in s.items() if len(v) >= 3 and np.mean(v) > 1.0}
        print(f"   jeda {L}: {len(good[L])} KOL copy-nya untung di A (>= 3 koin): "
              + ", ".join(sorted(kol[w] for w in good[L]))[:300])

    def select(idx, L, kset, kmin, smin, amax, mmax):
        out = []
        for k in idx:
            e = ev[k]
            if kset == "untung di A" and e["w"] not in good[L]:
                continue
            # sinyal hanya saat KOL ke-kmin (dari set terpilih) beli koin ini, jadi tiap koin maks 1 kali
            c = coins[e["ci"]]
            ws = [w for _, w, isb, _ in c.w[: e["j"] + 1] if isb and w in kol
                  and (kset != "untung di A" or w in good[L])]
            if len(dict.fromkeys(ws)) != kmin or ws[-1] != e["w"] or ws.count(e["w"]) != 1:
                continue
            if e["sol"] < smin or e["age"] > amax:
                continue
            if mmax and paths[k].entry(L) > mmax:
                continue
            out.append(k)
        return out

    configs = [(ks, km, sm, am, mm) for ks in ("semua", "untung di A") for km in (1, 2) for sm in (0.0, 1.0)
               for am in (15, 60, 300) for mm in (0, 150)]
    rows = []
    for L in LATS:
        for cf in configs:
            iB, iC = select(B, L, *cf), select(C, L, *cf)
            if len(iB) < 30:
                continue
            for ex in EXITS:
                xb = [x for _, x, _ in trades(iB, L, ex, "1,25%")]
                if len(xb) < 30:
                    continue
                rows.append((L, cf, ex, float(np.mean(xb)), len(xb), iC))
    n_cfg = len(rows)
    print(f"\n== {n_cfg:,} aturan (>= 30 sinyal di B) = {len(configs)} filter x {len(EXITS)} exit x {len(LATS)} jeda.")
    for L in LATS:
        rl = sorted([r for r in rows if r[0] == L], key=lambda r: -r[3])
        if not rl:
            print(f" jeda {L}: tidak ada aturan dengan >= 30 sinyal di B")
            continue
        n_pos_b = sum(r[3] > 1 for r in rl)
        n_pos_c = 0
        for r in rl:
            xc = [x for _, x, _ in trades(r[5], L, r[2], "1,25%")]
            n_pos_c += bool(xc) and np.mean(xc) > 1
        print(f" jeda {L} dtk{' (MUSTAHIL)' if L == 0 else ''}: {len(rl):,} aturan, untung di B {n_pos_b:,}, "
              f"untung di C {n_pos_c:,}")
        for L_, cf, ex, mb, nb, iC in rl[:3]:
            lab = (f"KOL {cf[0]}, {cf[1]} KOL, beli >= {cf[2]} SOL, umur <= {cf[3]}s"
                   f"{', mcap <= ' + str(cf[4]) + ' SOL' if cf[4] else ''} | {ex} | B {mb:.3f}x n={nb}")
            print(f"   PILIHAN B: {lab}")
            for cost in COSTS:
                print("   " + report(f"UJI C biaya {cost}", trades(iC, L, ex, cost)))
    print(f"\nSelesai dalam {time.time() - t_start:.0f} dtk.")


if __name__ == "__main__":
    main()

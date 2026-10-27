"""Backtest "Hybrid Multi-Agent Versi 2.0 (Ketat)" permintaan pengguna (27 Okt 2026).

Aturan pengguna (dipakai persis):
  Masuk (semua): pair baru pump.fun/DEX, >= 1 smart money/whale sudah beli, likuiditas >= $30.000,
                 volume 1 jam >= $60.000, top10 <= 25%, umur >= 60 dtk, mint revoked & LP locked/burned
  Risk: posisi min(7% modal, $14), maks 1 posisi, maks 5 trade per hari (UTC), SL -18%,
        jual 30% di +25%, sisanya trailing 12% setelah harga sampai +30%, biaya 2,5% pulang-pergi,
        jeda masuk dan keluar acak 4-9 dtk.
Data dan cara sama dengan riset/hybrid.py (v1). Likuiditas = 2 x SOL di kurva dari harga (x*y=k).
Ditambah varian "terdekat" (likuiditas >= $15rb) dan filter v1 + exit v2 sebagai pembanding, diberi
label jelas, BUKAN aturan pengguna.

Smart money = 256 wallet dari kriteria v1 (dinilai 50% awal data wallet). Whale = wallet yang sekali
beli >= 2 SOL setelah detik ke-2 (bukan bundle dev). Diuji di periode uji (50% akhir).

Pakai: python3 riset/hybrid2.py --data data --rugdesk data-rd
"""
import argparse
import bisect
import os
import random
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hybrid as h1  # noqa: E402

w2, ms = h1.w2, h1.ms
START, STAKE_PCT, MAX_STAKE, MAX_DAY = 200.0, 0.07, 14.0, 5
SL, TP1, TP1_FRAC, ARM, TRAIL = 0.18, 0.25, 0.30, 0.30, 0.12
LAT = (4.0, 9.0)
TOP10_MAX, MIN_AGE, WHALE_SOL = 0.25, 60.0, 2.0
LIQ_DEX, DUMP_X = 30000, 0.75
CP = (0.0125, 0.0125)    # biaya beli, jual (2,5% pulang-pergi)


def filt(c, t, solusd, liq_min, vol_min):
    snap = [a for a in c.snaps if a <= t]
    if not snap:
        return "belum_ada_data_holder"
    a = max(snap)
    top10, _, liq_snap = c.snaps[a]
    if top10 > TOP10_MAX:
        return "top10"
    liq = liq_snap if a == t else max(0.0, ms.v_sol_at(h1.mcap_until(c, t)) - ms.VIRTUAL_SOL)
    if 2 * liq * solusd < liq_min:
        return "likuiditas"
    if h1.vol_until(c, t) * solusd < vol_min:
        return "volume"
    return None


def first_money(c, smart, use_whale):
    if use_whale is None:      # pembanding tanpa syarat smart money/whale
        return 0.0
    ts = [bl[0][0] for w, bl in c.buys.items() if smart[w]]
    if use_whale:
        ts += [t for bl in c.buys.values() for t, sol in bl if sol >= WHALE_SOL and t >= 2.0]
    return min(ts) if ts else None


def signal(c, smart, use_whale, solusd, liq_min, vol_min, why):
    tm = first_money(c, smart, use_whale)
    if tm is None:
        why["tanpa_smart/whale"] = why.get("tanpa_smart/whale", 0) + 1
        return None
    t1 = max(MIN_AGE, tm)
    last = None
    for t in [t1] + [float(a) for a in h1.SNAPS if a > t1]:
        if t > c.end:
            break
        last = filt(c, t, solusd, liq_min, vol_min)
        if last is None:
            return t
    why[last or "rekaman_habis"] = why.get(last or "rekaman_habis", 0) + 1
    return None


def run_exit(path, te, p_in, rng, end):
    """path: [(mulai, selesai, high, low, close)] sesudah masuk. Return (x total, t keluar, terbuka)."""
    entry = p_in * (1 + CP[0])
    sl_px, tp_px = entry * (1 - SL), entry * (1 + TP1)
    peak, armed, part, got = entry, False, 0.0, 0.0
    price_at = lambda t: next((x[4] for x in path if x[0] <= t < x[1]), path[-1][4] if path else p_in)
    last = p_in
    for a, b, hi, lo, cl in path:
        stop = max(sl_px, peak * (1 - TRAIL)) if armed else sl_px
        if lo <= stop:
            tf = min(end, a + rng.uniform(*LAT))
            px = min(stop, price_at(tf))
            got += (1 - part) * px * (1 - CP[1]) / entry
            return got, tf, False
        if part == 0 and hi >= tp_px:
            tf = min(end, a + rng.uniform(*LAT))
            px = min(tp_px, price_at(tf))
            got += TP1_FRAC * px * (1 - CP[1]) / entry
            part = TP1_FRAC
        peak = max(peak, hi)
        armed = armed or peak >= entry * (1 + ARM)
        if armed and cl <= peak * (1 - TRAIL):
            tf = min(end, b + rng.uniform(*LAT))
            px = min(peak * (1 - TRAIL), price_at(tf))
            got += (1 - part) * px * (1 - CP[1]) / entry
            return got, tf, False
        last = cl
    got += (1 - part) * last * (1 - CP[1]) / entry
    return got, end, True


def trade_pf(c, t_sig, rng):
    te = t_sig + rng.uniform(*LAT)
    if te >= c.end:
        return None
    p_in = w2.price_at(c, te)
    if p_in <= 0:
        return None
    k = bisect.bisect_right(c.starts, te)
    x, tx, op = run_exit(c.cs[k:], te, p_in, rng, c.end)
    return x, tx, op


def sim(trades):
    """Maks 1 posisi, maks 5 trade per hari UTC, ukuran min(7% modal, $14)."""
    eq, busy, rows, peak, mdd, per_day = START, -1.0, [], START, 0.0, {}
    for t, x, tx in sorted(trades):
        d = int(t // 86400)
        if t < busy or per_day.get(d, 0) >= MAX_DAY:
            continue
        per_day[d] = per_day.get(d, 0) + 1
        stake = min(eq * STAKE_PCT, MAX_STAKE)
        pnl = stake * (x - 1)
        eq += pnl
        busy = tx
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        rows.append((x, pnl, eq))
    return rows, mdd


def report(label, trades):
    xs = [r[1] for r in trades]
    rows, mdd = sim(trades)
    n = len(rows)
    print(f"\n--- {label}")
    if len(xs) >= 2:
        print(f"    Semua sinyal (tanpa batas posisi/hari): {w2.fmt(w2.stat(xs))}")
    if not n:
        print("    0 trade")
        return
    wins = [r for r in rows if r[0] > 1]
    loss = [r for r in rows if r[0] <= 1]
    lo, hi = ms.wilson(len(wins), n)
    gw, gl = sum(r[1] for r in wins), -sum(r[1] for r in loss)
    eq = rows[-1][2]
    print(f"    Total trade      : {n}" + ("  (<30, belum bisa disimpulkan)" if n < 30 else ""))
    print(f"    Winrate          : {len(wins) / n:.1%} (CI 95% {lo:.0%}-{hi:.0%})")
    print(f"    Rata menang/kalah: {np.mean([r[0] - 1 for r in wins]) if wins else 0:+.1%} / "
          f"{np.mean([r[0] - 1 for r in loss]) if loss else 0:+.1%}")
    print(f"    Net PnL          : ${eq - START:+.2f} ({(eq - START) / START:+.1%}), akhir ${eq:.2f}")
    print(f"    Max drawdown     : {mdd:.1%}")
    print(f"    Profit factor    : {gw / gl if gl else float('inf'):.2f}")
    print(f"    Dump parah (rugi > {1 - DUMP_X:.0%} walau SL): {sum(r[0] < DUMP_X for r in rows)}; "
          f"terburuk {min(r[0] for r in rows) - 1:+.0%}")
    step = max(1, n // 12)
    pts = [START] + [rows[i][2] for i in range(step - 1, n, step)]
    if len(rows) % step:
        pts.append(eq)
    print("    Equity: " + " -> ".join(f"${p:.0f}" for p in pts))


def dex(rd_dir, rng):
    import rugdesk as rd
    leads, px = rd.load_all(rd_dir)
    why, trades = {}, []
    for mint, x in leads.items():
        rc, pool = x.get("rc"), x.get("pool")
        r = None
        if not rc or rc.get("risk_score") is None:
            r = "tidak_ada_laporan_rugcheck"
        elif rc.get("rugged"):
            r = "sudah_rug"
        elif rc.get("mint_authority"):
            r = "mint_belum_dicabut"
        elif rc.get("freeze_authority") or rc.get("danger"):
            r = "risiko_honeypot/danger"
        elif rc.get("lp_locked_pct") is None or rc["lp_locked_pct"] < 90:
            r = "LP_tidak_dikunci"
        elif rc.get("top10_pct") is None or rc["top10_pct"] > TOP10_MAX * 100:
            r = "top10"
        elif not pool or (pool.get("liq_usd") or 0) < LIQ_DEX:
            r = "likuiditas"
        why[r or "LOLOS"] = why.get(r or "LOLOS", 0) + 1
        if r:
            continue
        t_in = x["t"] + rng.uniform(*LAT)
        pts = [p for p in px.get(mint, []) if p[0] >= t_in and p[1] > 0]
        if len(pts) < 2:
            continue
        path = [(pts[i][0], pts[i + 1][0], pts[i][1], pts[i][1], pts[i][1]) for i in range(1, len(pts) - 1)]
        if not path:
            continue
        xr, tx, _ = run_exit(path, pts[0][0], pts[0][1], rng, pts[-1][0])
        trades.append((pts[0][0], xr, tx))
    print(f"\n== DEX (rekaman rugdesk, {len(leads)} token berprofil DexScreener 25-26 Okt, harga tiap 1 menit)")
    print("   Saringan v2: " + ", ".join(f"{k} {v}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
    print("   TIDAK bisa diterapkan: smart money/whale (tidak ada data wallet DEX) dan volume 1 jam (tidak direkam).")
    report("DEX: lolos filter v2 yang bisa diukur", trades)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--rugdesk", default="data-rd")
    ap.add_argument("--preset", default="v2", choices=("v2", "v25"))
    a = ap.parse_args()
    global STAKE_PCT, MAX_STAKE, MAX_DAY, SL, TP1, ARM, TRAIL, TOP10_MAX, MIN_AGE, LIQ_DEX, DUMP_X
    if a.preset == "v25":
        # v2.5 "Titik Tengah": liq >= $18rb, vol >= $40rb, top10 <= 27%, umur >= 40 dtk, posisi min(8%, $16),
        # maks 7/hari, SL -15%, jual 30% di +22%, sisa trailing 11% setelah +28%, dump parah = rugi > 30%
        STAKE_PCT, MAX_STAKE, MAX_DAY = 0.08, 16.0, 7
        SL, TP1, ARM, TRAIL = 0.15, 0.22, 0.28, 0.11
        TOP10_MAX, MIN_AGE, LIQ_DEX, DUMP_X = 0.27, 40.0, 18000, 0.70
    t_start = time.time()
    cfg = ms.load_config(a.data)
    wid = {}
    coins, n_bad = h1.load(a.data, wid)
    t_max = coins[-1].t0
    coins = [c for c in coins if c.t0 >= t_max - h1.DAYS * 86400]
    hs, ps, src = h1.sol_prices(coins[0].t0, t_max)
    px = h1.Px(hs, ps)
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    cw = [c for c in coins if c.has_w]
    iA = len(cw) // 2
    A, t_split = cw[:iA], cw[iA].t0
    S = w2.wallet_stats(A, len(wid), cfg, A[len(A) // 2].t0)
    days = max(1e-9, (A[-1].t0 - A[0].t0) / 86400)
    smart = ((S["n"] >= 5) & (np.nan_to_num(S["cp_mean"]) >= 1.2) & (np.nan_to_num(S["cp_win"]) >= 0.4)
             & ~S["sniper"] & (S["n"] / days <= 30))
    max_liq = [2 * (ms.v_sol_at(max(x[2] for x in c.cs)) - ms.VIRTUAL_SOL) * px(c.t0) for c in coins]
    print(f"== {len(coins):,} koin pump.fun {ts(coins[0].t0)} - {ts(t_max)} UTC, {n_bad} kurva tidak standar "
          f"dibuang. SOL ({src}) ${min(ps):.0f}-${max(ps):.0f}. {int(smart.sum())} smart money wallet.")
    print(f"   Likuiditas tertinggi yang pernah dicapai koin di kurva: maks ${max(max_liq):,.0f}, "
          f"{sum(m >= 30000 for m in max_liq)} koin pernah >= $30rb, {sum(m >= 15000 for m in max_liq):,} koin >= $15rb.")
    print(f"   Periode uji (smart money out-of-sample): {ts(t_split)} - {ts(t_max)} UTC")
    test = [c for c in coins if c.t0 >= t_split and c.has_w]
    variants = [
        ("V2.5 PERSIS (liq >= $18rb, vol >= $40rb, smart money ATAU whale)", 18000, 40000, True),
        ("V2.5, hanya smart money (tanpa whale) - pembanding", 18000, 40000, False),
        ("V2.5 tanpa syarat smart/whale - pembanding, BUKAN aturan pengguna", 18000, 40000, None),
    ] if a.preset == "v25" else [
        ("V2 PERSIS (liq >= $30rb, vol >= $60rb, smart money ATAU whale)", 30000, 60000, True),
        ("TERDEKAT YANG MUNGKIN (liq >= $15rb, vol >= $60rb, smart ATAU whale) - BUKAN aturan pengguna",
         15000, 60000, True),
        ("TERDEKAT, hanya smart money (tanpa whale) - BUKAN aturan pengguna", 15000, 60000, False),
        ("v1 filter (liq >= $8rb, vol >= $25rb, top10 25%) + smart ATAU whale + exit v2 - pembanding",
         8000, 25000, True),
    ]
    for label, lq, vo, wh in variants:
        rng = random.Random(11)
        why, tr = {}, []
        for c in test:
            s = signal(c, smart, wh, px(c.t0), lq, vo, why)
            if s is None:
                continue
            r = trade_pf(c, s, rng)
            if r:
                tr.append((c.t0 + s, r[0], c.t0 + r[1]))
        print(f"\n== {label}")
        print("   Gagal karena: " + ", ".join(f"{k} {v:,}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
        report(label.split(" (")[0], tr)
    if os.path.isdir(os.path.join(a.rugdesk, "rugdesk")):
        dex(a.rugdesk, random.Random(5))
    print(f"\nSelesai {time.time() - t_start:.0f} dtk. Paper saja.")


if __name__ == "__main__":
    main()

"""Backtest strategi "Hybrid Multi-Agent (New Pair + Copy Trade)" permintaan pengguna (27 Okt 2026).

Aturan pengguna (dipakai persis, TIDAK dioptimasi, jadi tidak ada data latih untuk aturan ini):
  Scout   : pair baru pump.fun (dan DEX, lihat bagian rugdesk)
  Copy    : smart money wallet beli koin -> sinyal
  Filter  : mint revoked, LP locked/burned, top10 <= 28%, bukan honeypot, likuiditas >= $8.000,
            volume 1 jam >= $25.000
  Analyst : skor tambahan kalau smart money ikut masuk
  Risk    : posisi min(10% modal, $20), SL -10%, trailing aktif di +18% jarak 9%, maks 1 posisi
  Biaya   : 2,5% pulang-pergi (asumsi pengguna) + versi realistis kita (fee 1,25% + slip 2% per sisi,
            priority fee, dampak kurva); jeda masuk DAN keluar acak 3-8 dtk.

Terjemahan ke data pump.fun kita (rekaman memescan, candle 5/15/60 dtk sampai umur 30 menit):
  - mint revoked, LP, honeypot: pump.fun selalu lolos (mint dicabut program, tidak ada LP yang bisa
    ditarik selama di kurva, program selalu bisa jual). Jadi filter ini tidak menyaring apa pun.
  - top10: dari snapshot rekaman (umur 10..600 dtk), holder dari trade yang terlihat.
  - likuiditas USD = 2 x SOL asli di kurva x harga SOL (cara DexScreener menghitung likuiditas pool).
  - volume 1 jam = total volume beli+jual sejak koin lahir (koin < 1 jam), candle yang sudah selesai.
  - smart money: wallet dinilai di 50% pertama periode data wallet (kriteria tetap, ditulis sebelum
    melihat hasil), diuji di 50% sisanya. Data wallet hanya 5 menit pertama tiap koin.
Koin kurva tidak standar (bug inflow 0 di perekam) dibuang.

Pakai: python3 riset/hybrid.py --data data --rugdesk data-rd
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import time
import urllib.request

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallet2 as w2  # noqa: E402

ms = w2.ms
FI = w2.FI
DAYS = 7
START, MAX_STAKE, STAKE_PCT = 200.0, 20.0, 0.10
SL, ARM, TRAIL = 0.10, 0.18, 0.09
LAT = (3.0, 8.0)
TOP10_MAX, LIQ_MIN, VOL_MIN = 0.28, 8000.0, 25000.0
RUG_X = 0.75          # rugi >= 25% walau ada SL -10% = kena dump/rug yang lolos filter
SNAPS = ms.REC_SNAPS


# ---------------------------------------------------------------- harga SOL
def sol_prices(t_from, t_to):
    """Harga SOL/USD per jam (Kraken, cadangan CoinGecko). Return (jam[], harga[], sumber)."""
    try:
        url = f"https://api.kraken.com/0/public/OHLC?pair=SOLUSD&interval=60&since={int(t_from) - 7200}"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "memescan"}), timeout=20) as r:
            rows = next(iter(v for k, v in json.load(r)["result"].items() if k != "last"))
        return [float(x[0]) for x in rows], [float(x[4]) for x in rows], "Kraken"
    except Exception as e:   # noqa: BLE001
        print("Kraken gagal:", e)
    try:
        url = "https://api.coingecko.com/api/v3/coins/solana/market_chart?vs_currency=usd&days=14"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "memescan"}), timeout=20) as r:
            rows = json.load(r)["prices"]
        return [x[0] / 1000 for x in rows], [float(x[1]) for x in rows], "CoinGecko"
    except Exception as e:   # noqa: BLE001
        print("CoinGecko gagal:", e)
    return [t_from], [190.0], "KONSTAN $190 (API gagal)"


class Px:
    def __init__(self, ts, ps):
        self.ts, self.ps = ts, ps

    def __call__(self, t):
        i = max(0, bisect.bisect_right(self.ts, t) - 1)
        return self.ps[i]


# ---------------------------------------------------------------- data pump.fun
class Coin:
    __slots__ = ("t0", "end", "m0", "cs", "starts", "cumv", "snaps", "buys", "sells", "has_w")


def load(data_dir, wid):
    d = os.path.join(data_dir, "rec")
    coins, n_bad = [], 0
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if any(s[FI["inflow_sol"]] == 0 and s[FI["growth"]] > 1.05 for s in r["snaps"]):
                        n_bad += 1
                        continue
                    c = Coin()
                    c.t0, c.end = float(r["t0"]), float(r["end"])
                    c.m0 = float(r.get("m0") or r["snaps"][0][1])
                    c.cs = [(ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), x[1], x[2], x[3]) for x in r["c"]]
                    c.starts = [x[0] for x in c.cs]
                    v, cum = 0.0, []
                    for x in r["c"]:
                        v += float(x[4]) + float(x[5])
                        cum.append(v)
                    c.cumv = cum
                    c.snaps = {int(s[0]): (float(s[FI["top10"]]), float(s[1]), float(s[FI["liq_sol"]]))
                               for s in r["snaps"]}
                    b, s = {}, {}
                    c.has_w = "w" in r
                    for age, w, isbuy, sol in r.get("w", []):
                        i = wid.setdefault(w, len(wid))
                        (b if isbuy else s).setdefault(i, []).append((float(age), float(sol)))
                    c.buys, c.sells = b, s
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                if c.cs and c.m0 > 0:
                    coins.append(c)
    coins.sort(key=lambda c: c.t0)
    return coins, n_bad


def vol_until(c, t):
    """Volume SOL dari candle yang sudah selesai sebelum t (tidak mengintip)."""
    i = bisect.bisect_right([x[1] for x in c.cs], t) - 1
    return c.cumv[i] if i >= 0 else 0.0


def mcap_until(c, t):
    m = c.m0
    for a, b, h, lo, cl in c.cs:
        if b > t:
            break
        m = cl
    return m


def filt(c, t, solusd):
    """Filter Agent di umur t. Return alasan gagal atau None."""
    snap = [a for a in c.snaps if a <= t]
    if not snap:
        return "belum_ada_data_holder"
    a = max(snap)
    top10, m_snap, liq_snap = c.snaps[a]
    if top10 > TOP10_MAX:
        return "top10"
    if a == t:
        liq = liq_snap
    else:
        liq = max(0.0, ms.v_sol_at(mcap_until(c, t)) - ms.VIRTUAL_SOL)
    if 2 * liq * solusd < LIQ_MIN:
        return "likuiditas"
    if vol_until(c, t) * solusd < VOL_MIN:
        return "volume"
    return None


def trade(c, t_sig, rng, cost, size_sol):
    """Masuk t_sig + jeda 3-8 dtk. SL -10%, trailing 9% aktif setelah +18%. Keluar juga pakai jeda.
    Dalam satu candle dianggap turun dulu baru naik (pesimis). Return (x, umur keluar, terbuka_di_akhir)."""
    te = t_sig + rng.uniform(*LAT)
    if te >= c.end:
        return None
    p_in = w2.price_at(c, te)
    if p_in <= 0:
        return None
    k = bisect.bisect_right(c.starts, te)
    entry = cost_in(p_in, cost, size_sol)
    peak, armed = entry, False
    out, t_out, last = None, c.end, p_in
    for a, b, h, lo, cl in c.cs[k:]:
        stop = max(entry * (1 - SL), peak * (1 - TRAIL)) if armed else entry * (1 - SL)
        if lo <= stop:
            t_fill = min(c.end, a + rng.uniform(*LAT))
            out, t_out = min(stop, w2.price_at(c, t_fill)), t_fill
            break
        peak = max(peak, h)
        armed = armed or peak >= entry * (1 + ARM)
        if armed and cl <= peak * (1 - TRAIL):
            t_fill = min(c.end, b + rng.uniform(*LAT))
            out, t_out = min(peak * (1 - TRAIL), w2.price_at(c, t_fill)), t_fill
            break
        last = cl
    is_open = out is None
    if is_open:
        out = last
    return cost_out(out, cost, size_sol) / entry - cost_prio(cost, size_sol), t_out, is_open


def cost_in(p, cost, size_sol):
    if cost == "user":
        return p * 1.0125
    return p * (1 + size_sol / ms.v_sol_at(p)) / ((1 - 0.0125) * (1 - 0.02))


def cost_out(p, cost, size_sol):
    if cost == "user":
        return p * 0.9875
    return p * (1 - 0.0125) * (1 - 0.02) / (1 + size_sol / ms.v_sol_at(p))


def cost_prio(cost, size_sol):
    return 0.0 if cost == "user" else 2 * 0.0005 / size_sol


# ---------------------------------------------------------------- sinyal
def scout_signal(c, solusd):
    for a in SNAPS:
        if a > c.end:
            break
        if a in c.snaps and filt(c, a, solusd) is None:
            return float(a)
    return None


def copy_signal(c, smart, solusd):
    ts = sorted(bl[0][0] for w, bl in c.buys.items() if smart[w])
    if not ts:
        return None
    t1 = ts[0]
    for t in [t1] + [float(a) for a in SNAPS if a > t1]:
        if t > c.end:
            break
        if filt(c, t, solusd) is None:
            return t
    return None


# ---------------------------------------------------------------- simulasi $200
def sim200(trades):
    """trades: (t_masuk_abs, x, t_keluar_abs, smart). Maks 1 posisi, ukuran min(10% modal, $20)."""
    eq, busy, rows, peak, mdd = START, -1.0, [], START, 0.0
    for t, x, tx, sm in sorted(trades, key=lambda r: (r[0], not r[3])):
        if t < busy:
            continue
        stake = min(eq * STAKE_PCT, MAX_STAKE)
        pnl = stake * (x - 1)
        eq += pnl
        busy = tx
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        rows.append((x, pnl, eq, sm))
    return rows, mdd


def report(label, trades, all_x=None):
    rows, mdd = sim200(trades)
    n = len(rows)
    print(f"\n--- {label}")
    if all_x is not None and len(all_x) >= 2:
        st = w2.stat(all_x)
        print(f"    Semua sinyal (tanpa batas 1 posisi): {w2.fmt(st)}")
    if not n:
        print("    0 trade")
        return
    wins = [r for r in rows if r[0] > 1]
    loss = [r for r in rows if r[0] <= 1]
    lo, hi = ms.wilson(len(wins), n)
    gw, gl = sum(r[1] for r in wins), -sum(r[1] for r in loss)
    rug = sum(r[0] <= RUG_X for r in rows)
    eq = rows[-1][2]
    print(f"    Total trade      : {n}" + ("  (<30, belum bisa disimpulkan)" if n < 30 else ""))
    print(f"    Winrate          : {len(wins) / n:.1%} (CI 95% {lo:.0%}-{hi:.0%})")
    print(f"    Rata menang/kalah: {np.mean([r[0] - 1 for r in wins]) if wins else 0:+.1%} / "
          f"{np.mean([r[0] - 1 for r in loss]) if loss else 0:+.1%}  "
          f"(${np.mean([r[1] for r in wins]) if wins else 0:+.2f} / ${np.mean([r[1] for r in loss]) if loss else 0:+.2f})")
    print(f"    Net PnL          : ${eq - START:+.2f} ({(eq - START) / START:+.1%}), akhir ${eq:.2f}")
    print(f"    Max drawdown     : {mdd:.1%}")
    print(f"    Profit factor    : {gw / gl if gl else float('inf'):.2f}")
    print(f"    Rug/dump lolos filter (rugi >= 25% walau SL -10%): {rug} ({rug / n:.0%}); "
          f"terburuk {min(r[0] for r in rows) - 1:+.0%}")
    print(f"    Trade dengan smart money: {sum(r[3] for r in rows)}")
    step = max(1, n // 20)
    pts = [(0, START)] + [(i + 1, rows[i][2]) for i in range(step - 1, n, step)]
    if pts[-1][0] != n:
        pts.append((n, eq))
    lo_e, hi_e = min(p[1] for p in pts), max(p[1] for p in pts)
    print("    Equity curve:")
    for i, e in pts:
        bar = int(round(30 * (e - lo_e) / (hi_e - lo_e))) if hi_e > lo_e else 15
        print(f"      trade {i:>5} | ${e:7.2f} {'#' * max(1, bar)}")


# ---------------------------------------------------------------- DEX (rekaman rugdesk @0xboan)
def dex_part(rd_dir, px_sol):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import rugdesk as rd
    leads, px = rd.load_all(rd_dir)
    print(f"\n== BAGIAN DEX (token yang sudah di DEX, rekaman rugdesk, harga tiap 1 menit): {len(leads)} token")
    if not leads:
        print("   Tidak ada data rugdesk di cache.")
        return
    why, trades, xs = {}, [], []
    rng = random.Random(7)
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
        elif not pool or (pool.get("liq_usd") or 0) < LIQ_MIN:
            r = "likuiditas"
        why[r or "LOLOS"] = why.get(r or "LOLOS", 0) + 1
        if r:
            continue
        t_in = x["t"] + rng.uniform(*LAT)
        pts = [p for p in px.get(mint, []) if p[0] >= t_in and p[1] > 0]
        if len(pts) < 2:
            continue
        entry = pts[0][1] * 1.0125
        peak, armed, out, tx = entry, False, None, pts[-1][0]
        for t, p, liq in pts[1:]:
            stop = max(entry * (1 - SL), peak * (1 - TRAIL)) if armed else entry * (1 - SL)
            if p <= stop:
                out, tx = p, t
                break
            peak = max(peak, p)
            armed = armed or peak >= entry * (1 + ARM)
        if out is None:
            out = pts[-1][1]
        xr = out * 0.9875 / entry
        xs.append(xr)
        trades.append((pts[0][0], xr, tx, False))
    print("   Saringan:", ", ".join(f"{k} {v}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
    print("   Volume 1 jam TIDAK direkam di data ini (hanya jumlah transaksi), jadi filter volume tidak dipakai.")
    report("DEX: token berprofil DexScreener yang lolos filter pengguna", trades, xs)


# ---------------------------------------------------------------- utama
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--rugdesk", default="data-rd")
    a = ap.parse_args()
    t_start = time.time()
    cfg = ms.load_config(a.data)
    wid = {}
    coins, n_bad = load(a.data, wid)
    if not coins:
        print("Tidak ada rekaman.")
        return
    t_max = coins[-1].t0
    coins = [c for c in coins if c.t0 >= t_max - DAYS * 86400]
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    hs, ps, src = sol_prices(coins[0].t0, t_max)
    px = Px(hs, ps)
    print(f"== {len(coins):,} koin pump.fun {ts(coins[0].t0)} - {ts(t_max)} UTC (7 hari terakhir), "
          f"{n_bad} kurva tidak standar dibuang. Harga SOL {src}: ${min(ps):.0f}-${max(ps):.0f}.")
    print(f"   Filter likuiditas $8.000 = {LIQ_MIN / 2 / np.median(ps):.1f} SOL asli di kurva, "
          f"volume $25.000 = {VOL_MIN / np.median(ps):.0f} SOL (pada harga median).")

    # --- smart money: nilai di 50% pertama koin yang punya data wallet
    cw = [c for c in coins if c.has_w]
    iA = len(cw) // 2
    A = cw[:iA]
    t_split = cw[iA].t0
    S = w2.wallet_stats(A, len(wid), cfg, A[len(A) // 2].t0)
    days = max(1e-9, (A[-1].t0 - A[0].t0) / 86400)
    smart = ((S["n"] >= 5) & (np.nan_to_num(S["cp_mean"]) >= 1.2) & (np.nan_to_num(S["cp_win"]) >= 0.4)
             & ~S["sniper"] & (S["n"] / days <= 30))
    buy_sol = np.nan_to_num(S["buy_avg"] * S["n"])
    pnl = np.nan_to_num(S["own_roi"] * buy_sol) - buy_sol
    cand = np.nonzero(S["n"] >= 5)[0]
    gm = np.zeros(len(wid), bool)
    gm[cand[np.argsort(-pnl[cand])][:100]] = True
    print(f"   Smart money dinilai {ts(A[0].t0)} - {ts(A[-1].t0)}: {int(smart.sum())} wallet lolos kriteria "
          f"(>= 5 koin, hasil copy >= 1,2x, menang >= 40%, bukan sniper, <= 30 koin/hari); "
          f"versi GMGN = 100 wallet untung SOL terbanyak.")
    print(f"   Periode UJI (out-of-sample untuk smart money): {ts(t_split)} - {ts(t_max)} UTC")

    test = [c for c in coins if c.t0 >= t_split]
    for cost in ("user", "real"):
        rng = random.Random(42)
        print(f"\n================ BIAYA: {'asumsi pengguna 2,5% pulang-pergi' if cost == 'user' else 'realistis (fee 1,25% + slip 2% per sisi + priority fee + dampak kurva, ~7%)'}")
        sets = {"scout7": [], "scout": [], "copy": [], "copy_gm": [], "hybrid": [], "buyall": []}
        xs = {k: [] for k in sets}
        n_open = 0
        why = {}
        for c in coins:
            s_usd = px(c.t0)
            size_sol = MAX_STAKE / s_usd
            sig = scout_signal(c, s_usd)
            in_test = c.t0 >= t_split
            res_s = trade(c, sig, rng, cost, size_sol) if sig is not None else None
            if sig is None and cost == "user":
                r = filt(c, 60.0, s_usd) if 60 in c.snaps else "belum_ada_data_holder"
                why[r or "lolos_di_menit_lain"] = why.get(r or "lolos_di_menit_lain", 0) + 1
            if res_s:
                row = (c.t0 + sig, res_s[0], c.t0 + res_s[1], False)
                sets["scout7"].append(row)
                xs["scout7"].append(res_s[0])
                n_open += res_s[2]
            if not in_test:
                continue
            if res_s:
                sets["scout"].append(row)
                xs["scout"].append(res_s[0])
            if 60 in c.snaps:
                r = trade(c, 60.0, rng, cost, size_sol)
                if r:
                    sets["buyall"].append((c.t0 + 60, r[0], c.t0 + r[1], False))
                    xs["buyall"].append(r[0])
            if c.has_w:
                for key, mask in (("copy", smart), ("copy_gm", gm)):
                    cs = copy_signal(c, mask, s_usd)
                    if cs is None:
                        continue
                    r = trade(c, cs, rng, cost, size_sol)
                    if r:
                        sets[key].append((c.t0 + cs, r[0], c.t0 + r[1], True))
                        xs[key].append(r[0])
                cs = copy_signal(c, smart, s_usd) if c.has_w else None
                cands = [x for x in ((sig, False), (cs, True)) if x[0] is not None]
                if cands:
                    t_e = min(x[0] for x in cands)
                    sm = cs is not None and cs <= t_e + 1e-9 or any(
                        smart[w] and bl[0][0] <= t_e for w, bl in c.buys.items())
                    r = trade(c, t_e, rng, cost, size_sol)
                    if r:
                        sets["hybrid"].append((c.t0 + t_e, r[0], c.t0 + r[1], bool(sm)))
                        xs["hybrid"].append(r[0])
        if cost == "user":
            print("   Kenapa koin tidak lolos Filter Agent (dicek di umur 60 dtk): "
                  + ", ".join(f"{k} {v:,}" for k, v in sorted(why.items(), key=lambda kv: -kv[1])))
            print(f"   Posisi Scout yang masih terbuka saat rekaman habis (dinilai harga terakhir): {n_open}")
        report("A. Scout saja (pair baru + Filter), 7 hari penuh", sets["scout7"], xs["scout7"])
        report("B. Scout saja, periode uji", sets["scout"], xs["scout"])
        report("C. Copy saja (smart money kriteria) + Filter, periode uji", sets["copy"], xs["copy"])
        report("D. Copy saja (100 wallet untung terbanyak ala GMGN) + Filter, periode uji",
               sets["copy_gm"], xs["copy_gm"])
        report("E. HYBRID (Scout ATAU Copy, Analyst prioritaskan smart money), periode uji",
               sets["hybrid"], xs["hybrid"])
        report("PEMBANDING: beli semua koin umur 60 dtk tanpa filter, aturan jual sama, periode uji",
               sets["buyall"], xs["buyall"])
    if os.path.isdir(os.path.join(a.rugdesk, "rugdesk")):
        dex_part(a.rugdesk, px)
    else:
        print("\n== BAGIAN DEX: cache rugdesk tidak ditemukan.")
    print(f"\nSelesai {time.time() - t_start:.0f} dtk. Data mulai Okt 2026, Jan 2026 - sekarang tidak bisa "
          "disimulasikan. Paper saja.")


if __name__ == "__main__":
    main()

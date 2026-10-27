"""Riset mendalam (27 Okt 2026): kenapa hybrid gagal, dan adakah pendekatan LAIN yang punya edge untuk $200.

Desain anti curve-fitting (ditulis SEBELUM melihat hasil):
  Data   : koin pump.fun dengan data wallet, 7 hari terakhir, urut waktu.
  W  (0-25%)   : nilai wallet (smart money, bot, sniper) -> dipakai sebagai fitur di P dan T
  P  (25-50%)  : pilih konfigurasi terbaik tiap keluarga (rata hasil semua sinyal, n >= 30, biaya 2,5%)
  T  (50-100%) : uji SEKALI. Hanya hasil T yang dipakai untuk kesimpulan.
  Biaya  : 2,5% pulang-pergi (1,25% per sisi) dan 6% (3% per sisi). Jeda masuk dan keluar acak 3-9 dtk.
  Modal  : $200, posisi min(10% modal, $20), maks 1 posisi (F3: maks 2 trade/hari).
  SL/TP dihitung dari harga isi (fill). Dalam satu candle dianggap turun dulu (pesimis).
Keluarga:
  F1 pure copy trade (3 daftar wallet x 1/2 wallet x 3 exit)
  F2 masuk setelah konfirmasi harga & arus beli (umur 2/5/10 menit x momentum x net beli x 3 exit)
  F3 frekuensi rendah: hanya koin dengan volume 5 menit tertinggi (ambang dari P, ~1 atau ~2 per hari)
  F4 exit berbasis waktu/volume pada masuk netral (semua koin umur 60 dtk, sampel)
  F5 filter perilaku wallet (8 fitur x 2 ambang x 2 arah x 2 umur x 2 exit)
  F6 gabungan terbaik F2 + terbaik F5
Plus diagnosa (periode T): ke mana harga koin bergerak, biaya jeda, SL jebol, untung kotor tanpa biaya.

Pakai: python3 riset/deep.py --data data
"""
import argparse
import bisect
import json
import math
import os
import random
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallet2 as w2  # noqa: E402

ms = w2.ms
FI = w2.FI
DAYS = 7
LAT = (3.0, 9.0)
COSTS = {"2,5%": (0.0125, 0.0125), "6%": (0.03, 0.03)}
START, STAKE_PCT, MAX_STAKE = 200.0, 0.10, 20.0
N_TESTED = 0


# ---------------------------------------------------------------- data
class Coin:
    __slots__ = ("i", "t0", "end", "m0", "cs", "starts", "cum_b", "cum_s", "ends", "buys", "sells", "dev", "snaps")


def load(data_dir):
    d = os.path.join(data_dir, "rec")
    wid, coins, n_bad = {}, [], 0
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if "w" not in r:
                        continue
                    if any(s[FI["inflow_sol"]] == 0 and s[FI["growth"]] > 1.05 for s in r["snaps"]):
                        n_bad += 1
                        continue
                    c = Coin()
                    c.t0, c.end = float(r["t0"]), float(r["end"])
                    c.m0 = float(r.get("m0") or r["snaps"][0][1])
                    cs, cb, cv, vb, vs = [], [], [], 0.0, 0.0
                    for x in r["c"]:
                        cs.append((ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), float(x[1]), float(x[2]),
                                   float(x[3])))
                        vb += float(x[4])
                        vs += float(x[5])
                        cb.append(vb)
                        cv.append(vs)
                    c.cs, c.cum_b, c.cum_s = cs, cb, cv
                    c.starts = [x[0] for x in cs]
                    c.ends = [x[1] for x in cs]
                    c.snaps = {int(s[0]): s for s in r["snaps"]}
                    b, s = {}, {}
                    for age, w, isbuy, sol in r["w"]:
                        i = wid.setdefault(w, len(wid))
                        (b if isbuy else s).setdefault(i, []).append((float(age), float(sol)))
                    c.buys, c.sells = b, s
                    c.dev = wid.setdefault(r["dev"], len(wid)) if r.get("dev") else -1
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                if c.cs and c.m0 > 0:
                    coins.append(c)
    coins.sort(key=lambda c: c.t0)
    t_max = coins[-1].t0
    coins = [c for c in coins if c.t0 >= t_max - DAYS * 86400]
    for i, c in enumerate(coins):
        c.i = i
    return coins, wid, n_bad


def price_at(c, t):
    i = bisect.bisect_right(c.starts, t) - 1
    return c.cs[i][4] if i >= 0 else c.m0


def vol_until(c, t, side="all"):
    """Volume SOL dari candle yang SUDAH selesai sebelum t (tidak mengintip)."""
    i = bisect.bisect_right(c.ends, t) - 1
    if i < 0:
        return 0.0
    if side == "buy":
        return c.cum_b[i]
    if side == "sell":
        return c.cum_s[i]
    return c.cum_b[i] + c.cum_s[i]


def rng_for(c, t, tag):
    return random.Random(zlib.crc32(f"{c.i}:{t:.1f}:{tag}".encode()))


# ---------------------------------------------------------------- mesin exit
EXITS = {
    # nama: dict(sl, arm, trail, tp=(naik, porsi), T maks detik, vd=(jendela, rasio) exit kalau volume turun)
    "trail": dict(sl=0.15, arm=0.20, trail=0.10, T=900),
    "time3m": dict(sl=0.20, T=180),
    "voldecay": dict(sl=0.20, T=900, vd=(60.0, 0.3)),
    "follow": dict(sl=0.30, T=600, follow=True),
    "wide": dict(sl=0.20, arm=0.30, trail=0.15, T=600),
    "time2m": dict(sl=0.30, T=120),
}
for T in (30, 60, 120, 300, 600, 1200):
    for sl in (None, 0.15, 0.30):
        EXITS[f"T{T}_sl{sl}"] = dict(sl=sl, T=T)
for win in (30.0, 60.0):
    for fr in (0.2, 0.5):
        EXITS[f"vd{int(win)}_{fr}"] = dict(sl=0.30, T=1200, vd=(win, fr))
for arm in (0.2, 0.5):
    for tr in (0.10, 0.25):
        EXITS[f"tr{arm}_{tr}"] = dict(sl=0.20, arm=arm, trail=tr, T=1200)
F4_EXITS = [k for k in EXITS if k.startswith(("T", "vd", "tr"))]

_cache = {}


def sim_trade(c, t_sig, ex, follow_ts=None):
    """Return (harga isi, [(porsi, harga keluar)], umur keluar, terbuka_di_akhir) atau None. Tanpa biaya."""
    key = (c.i, round(t_sig, 1), ex)
    if key in _cache:
        return _cache[key]
    cfg = EXITS[ex]
    rng = rng_for(c, t_sig, ex)
    te = t_sig + rng.uniform(*LAT)
    if te >= c.end:
        _cache[key] = None
        return None
    p_in = price_at(c, te)
    if p_in <= 0:
        _cache[key] = None
        return None
    sl = p_in * (1 - cfg["sl"]) if cfg.get("sl") else -1.0
    peak, armed = p_in, False
    t_lim = te + cfg["T"]
    fts = sorted(t for t in (follow_ts or []) if t > te) if cfg.get("follow") else []
    vd = cfg.get("vd")
    ref = None
    if vd:
        ref = (vol_until(c, te) - vol_until(c, te - vd[0])) / vd[0]
    k = bisect.bisect_right(c.starts, te)
    out = None
    for a, b, hi, lo, cl in c.cs[k:]:
        if a >= t_lim:
            tf = t_lim + rng.uniform(*LAT)
            out = (price_at(c, tf), tf)
            break
        if fts and fts[0] <= b:
            tf = max(a, fts[0]) + rng.uniform(*LAT)
            out = (price_at(c, tf), tf)
            break
        stop = max(sl, peak * (1 - cfg["trail"])) if armed else sl
        if lo <= stop:
            tf = a + rng.uniform(*LAT)
            out = (min(stop, price_at(c, tf)), tf)
            break
        peak = max(peak, hi)
        if cfg.get("arm"):
            armed = armed or peak >= p_in * (1 + cfg["arm"])
            if armed and cl <= peak * (1 - cfg["trail"]):
                tf = b + rng.uniform(*LAT)
                out = (min(peak * (1 - cfg["trail"]), price_at(c, tf)), tf)
                break
        if vd and ref and b - te >= vd[0]:
            now = (vol_until(c, b) - vol_until(c, b - vd[0])) / vd[0]
            if now < vd[1] * ref:
                tf = b + rng.uniform(*LAT)
                out = (price_at(c, tf), tf)
                break
    res = (p_in, out[0], out[1], False) if out else (p_in, c.cs[-1][4], c.end, True)
    _cache[key] = res
    return res


def mult(r, cost):
    cin, cout = COSTS[cost]
    return r[1] * (1 - cout) / (r[0] * (1 + cin))


# ---------------------------------------------------------------- statistik & simulasi
def sim200(tr, max_day=None):
    eq, busy, rows, peak, mdd, per_day = START, -1.0, [], START, 0.0, {}
    for t, x, tx in sorted(tr):
        if t < busy:
            continue
        d = int(t // 86400)
        if max_day and per_day.get(d, 0) >= max_day:
            continue
        per_day[d] = per_day.get(d, 0) + 1
        stake = min(eq * STAKE_PCT, MAX_STAKE)
        eq += stake * (x - 1)
        busy = tx
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
        rows.append((x, stake * (x - 1), eq))
    return rows, mdd


def summary(trades, cost, max_day=None):
    """trades: [(t_abs_sig, hasil_sim, t_abs_keluar)] -> dict statistik."""
    xs = [mult(r, cost) for _, r, _ in trades]
    tr = [(t, mult(r, cost), tx) for t, r, tx in trades]
    rows, mdd = sim200(tr, max_day)
    n = len(rows)
    out = {"n_sig": len(xs), "mean": float(np.mean(xs)) if xs else float("nan"),
           "lo": (float(np.mean(xs) - 1.96 * np.std(xs, ddof=1) / math.sqrt(len(xs))) if len(xs) > 1 else float("nan")),
           "n": n, "eq": rows[-1][2] if rows else START, "mdd": mdd}
    if n:
        wins = [r for r in rows if r[0] > 1]
        loss = [r for r in rows if r[0] <= 1]
        gw, gl = sum(r[1] for r in wins), -sum(r[1] for r in loss)
        out.update(win=len(wins) / n, ci=ms.wilson(len(wins), n),
                   aw=float(np.mean([r[0] - 1 for r in wins])) if wins else 0.0,
                   al=float(np.mean([r[0] - 1 for r in loss])) if loss else 0.0,
                   pf=gw / gl if gl else float("inf"), dump=sum(r[0] < 0.7 for r in rows))
    return out


def line(label, s, cost):
    if not s["n"]:
        return f"  {label} [{cost}]: 0 trade"
    tag = "" if s["n"] >= 30 else "  (<30 trade)"
    return (f"  {label} [{cost}]: sinyal {s['n_sig']} rata {s['mean']:.3f}x (CI bawah {s['lo']:.3f}) | $200 sim: "
            f"{s['n']} trade, menang {s['win']:.0%} (CI {s['ci'][0]:.0%}-{s['ci'][1]:.0%}), "
            f"rata menang {s['aw']:+.0%} / kalah {s['al']:+.0%}, akhir ${s['eq']:.2f} ({s['eq'] / START - 1:+.0%}), "
            f"MDD {s['mdd']:.0%}, PF {s['pf']:.2f}, dump >30% {s['dump']}{tag}")


def verdict(s25, s6):
    ok = (s25["n"] >= 30 and s25["lo"] > 1.0 and s6["mean"] > 1.0 and s25["eq"] > START and s6["eq"] > START)
    if ok:
        return "LAYAK DIUJI MAJU (untung di T, CI bawah > 1, simulasi $200 tetap untung di biaya 6%)"
    if s25["n"] >= 30 and s25["mean"] > 1.0:
        return "BELUM TERBUKTI (rata > 1 tapi CI bawah <= 1, atau rugi di biaya 6% / di simulasi $200)"
    if s25["n"] < 30:
        return "TIDAK BISA DISIMPULKAN (<30 trade)"
    return "TIDAK LAYAK (rugi di T)"


# ---------------------------------------------------------------- keluarga strategi
def family_run(name, configs, signals_fn, P, T, max_day=None, min_n=30, show=3):
    """configs: list (label, param). signals_fn(coins, param) -> trades. Pilih di P, uji di T."""
    global N_TESTED
    N_TESTED += len(configs)
    res = []
    for label, prm in configs:
        s = summary(signals_fn(P, prm), "2,5%", max_day)
        if s["n_sig"] >= min_n:
            res.append((s["mean"], label, prm, s["n_sig"]))
    res.sort(key=lambda r: -r[0])
    n_pos = sum(r[0] > 1 for r in res)
    print(f"\n==== {name}: {len(configs)} konfigurasi, {len(res)} punya >= {min_n} sinyal di P, {n_pos} untung di P")
    if not res:
        return None
    n_pos_T = 0
    for r in res:
        if r[0] > 1:
            s = summary(signals_fn(T, r[2]), "2,5%", max_day)
            n_pos_T += s["n_sig"] >= 30 and s["mean"] > 1
    print(f"   Dari {n_pos} yang untung di P, {n_pos_T} tetap untung di T (>= 30 sinyal).")
    best = None
    for rank, r in enumerate(res[:show]):
        trT = signals_fn(T, r[2])
        s25, s6 = summary(trT, "2,5%", max_day), summary(trT, "6%", max_day)
        print(f" #{rank + 1} {r[1]}  | P: {r[3]} sinyal, rata {r[0]:.3f}x")
        print(line("T", s25, "2,5%"))
        print(line("T", s6, "6%"))
        print(f"    -> {verdict(s25, s6)}")
        if rank == 0:
            best = (r, s25, s6, trT)
    return best


def wallet_lists(W, n_w, cfg):
    S = w2.wallet_stats(W, n_w, cfg, W[len(W) // 2].t0)
    days = max(1e-9, (W[-1].t0 - W[0].t0) / 86400)
    per_day = S["n"] / days
    cpm, cpw = np.nan_to_num(S["cp_mean"]), np.nan_to_num(S["cp_win"])
    buy_sol = np.nan_to_num(S["buy_avg"] * S["n"])
    pnl = np.nan_to_num(S["own_roi"] * buy_sol) - buy_sol
    L = {
        "L1 kriteria (>=5 koin, copy>=1,2x, menang>=40%, bukan sniper)":
            (S["n"] >= 5) & (cpm >= 1.2) & (cpw >= 0.4) & ~S["sniper"] & (per_day <= 30),
        "L2 ketat (>=10 koin, copy>=1,3x, konsisten 2 paruh, bukan sniper)":
            (S["n"] >= 10) & (cpm >= 1.3) & S["consist"] & ~S["sniper"],
    }
    top = np.zeros(n_w, bool)
    cand = np.nonzero(S["n"] >= 5)[0]
    top[cand[np.argsort(-pnl[cand])][:50]] = True
    L["L3 50 wallet untung SOL terbanyak (ala GMGN)"] = top
    beh = {"bot": per_day > 30, "sniper": S["sniper"].astype(bool), "good": L["L1 kriteria (>=5 koin, copy>=1,2x, menang>=40%, bukan sniper)"],
           "loser": (S["n"] >= 5) & (cpm < 0.7)}
    return L, beh, {k: int(v.sum()) for k, v in L.items()}


def f1_signals(lists):
    def fn(coins, prm):
        lname, k, ex = prm
        mask = lists[lname]
        out = []
        for c in coins:
            hits = sorted((bl[0][0], w) for w, bl in c.buys.items() if mask[w])
            if len(hits) < k:
                continue
            t_sig, ws = hits[k - 1][0], [w for _, w in hits[:k]]
            fol = [t for w in ws for t, _ in c.sells.get(w, [])]
            r = sim_trade(c, t_sig, ex, fol)
            if r:
                out.append((c.t0 + t_sig, r, c.t0 + r[2]))
        return out
    return fn


def f2_signals(coins, prm):
    a, g, nb, ex = prm
    out = []
    for c in coins:
        if c.end <= a + 10:
            continue
        p0, p1 = price_at(c, a / 2), price_at(c, a - 0.01)
        if p0 <= 0 or p1 / p0 < g:
            continue
        net = (vol_until(c, a, "buy") - vol_until(c, a / 2, "buy")) - (vol_until(c, a, "sell") - vol_until(c, a / 2, "sell"))
        if net < nb:
            continue
        r = sim_trade(c, a, ex)
        if r:
            out.append((c.t0 + a, r, c.t0 + r[2]))
    return out


def feats(c, a, beh):
    """Fitur perilaku wallet dari trade sebelum umur a (hanya masa lalu)."""
    bsol, n_b, bot, sn, good, loser, flip, mx = 0.0, 0, 0.0, 0, 0, 0, 0, 0.0
    for w, bl in c.buys.items():
        s = sum(v for t, v in bl if t < a)
        if s <= 0:
            continue
        n_b += 1
        bsol += s
        mx = max(mx, s)
        bot += s if beh["bot"][w] else 0.0
        sn += beh["sniper"][w]
        good += beh["good"][w]
        loser += beh["loser"][w]
        flip += any(t < a for t, _ in c.sells.get(w, []))
    ssol = sum(v for sl in c.sells.values() for t, v in sl if t < a)
    dev_sold = float(any(t < a for t, _ in c.sells.get(c.dev, [])))
    if n_b == 0:
        return None
    return {"n_pembeli": n_b, "porsi_bot": bot / bsol, "porsi_sniper": sn / n_b, "n_smart": good,
            "porsi_loser": loser / n_b, "porsi_flip": flip / n_b, "pembeli_terbesar": mx / bsol,
            "net_beli": bsol / (bsol + ssol), "dev_jual": dev_sold}


F5_FEATS = ("n_pembeli", "porsi_bot", "porsi_sniper", "n_smart", "porsi_loser", "porsi_flip",
            "pembeli_terbesar", "net_beli", "dev_jual")


# ---------------------------------------------------------------- diagnosa
def diagnose(T, beh):
    print("\n==== DIAGNOSA (periode T, semua koin yang masih hidup di umur 60 dtk)")
    alive = [c for c in T if c.end > 70]
    rng = random.Random(1)
    mx, r5, r30, first = [], [], [], {"naik22": 0, "turun15": 0, "tidak": 0}
    for c in alive:
        p = price_at(c, 60 + rng.uniform(*LAT))
        if p <= 0:
            continue
        k = bisect.bisect_right(c.starts, 66)
        hi = max([x[2] for x in c.cs[k:]] or [p])
        mx.append(hi / p)
        r5.append(price_at(c, 360) / p)
        r30.append(c.cs[-1][4] / p)
        f = "tidak"
        for a, b, h, lo, cl in c.cs[k:]:
            if lo <= p * 0.85:
                f = "turun15"
                break
            if h >= p * 1.22:
                f = "naik22"
                break
        first[f] += 1
    mx, r5, r30 = map(np.array, (mx, r5, r30))
    n = len(mx)
    print(f"  {len(T):,} koin di T, {n:,} masih ada trade setelah umur 60 dtk ({n / len(T):.0%}).")
    print(f"  Harga 5 menit kemudian: median {np.median(r5):.2f}x, rata {r5.mean():.2f}x. "
          f"Harga terakhir (maks 30 mnt): median {np.median(r30):.2f}x; {np.mean(r30 < 0.5):.0%} koin turun > 50%.")
    print(f"  Puncak setelah masuk (umur ~66 dtk): >= 1,25x {np.mean(mx >= 1.25):.0%}, >= 2x {np.mean(mx >= 2):.0%}, "
          f">= 5x {np.mean(mx >= 5):.1%}, >= 10x {np.mean(mx >= 10):.2%}.")
    print(f"  Mana duluan: +22% {first['naik22'] / n:.0%}, -15% {first['turun15'] / n:.0%}, "
          f"tidak dua-duanya {first['tidak'] / n:.0%}.")
    gross = summary([(c.t0 + 60, r, c.t0 + r[2]) for c in alive[:30000]
                     for r in [sim_trade(c, 60.0, "T300_slNone")] if r], "2,5%")
    raw = [r[1] / r[0] for c in alive[:30000] for r in [sim_trade(c, 60.0, "T300_slNone")] if r]
    print(f"  Beli umur 60 dtk, jual 5 menit kemudian, TANPA biaya: rata {np.mean(raw):.3f}x, median {np.median(raw):.3f}x "
          f"-> dengan biaya 2,5%: rata {gross['mean']:.3f}x.")
    lat = []
    mom = []
    for c in alive[:30000]:
        p60 = price_at(c, 59.99)
        if p60 <= 0:
            continue
        pf = price_at(c, 60 + rng.uniform(*LAT))
        lat.append(pf / p60)
        p30 = price_at(c, 29.99)
        if p30 > 0 and p60 / p30 >= 1.3:
            mom.append(pf / p60)
    print(f"  Biaya jeda 3-9 dtk (harga isi / harga saat sinyal): semua koin rata {np.mean(lat):.3f}x; "
          f"koin yang sedang naik >= 30% (sinyal momentum) rata {np.mean(mom):.3f}x, median {np.median(mom):.3f}x.")
    gaps = []
    for c in alive[:30000]:
        r = sim_trade(c, 60.0, "trail")
        if r and r[1] < r[0] * 0.85:
            gaps.append(r[1] / (r[0] * 0.85))
    gaps = np.array(gaps)
    print(f"  SL -15%: {len(gaps):,} kena SL. Harga keluar rata {gaps.mean():.2f}x dari harga SL "
          f"(rugi asli rata {(gaps.mean() * 0.85 - 1):+.0%}); {np.mean(gaps < 0.7):.0%} jebol > 30% di bawah SL.")
    # wallet: siapa yang untung
    print(f"  Wallet di W: {int(beh['bot'].sum()):,} bot (> 30 koin/hari), {int(beh['sniper'].sum()):,} sniper, "
          f"{int(beh['good'].sum()):,} smart (L1), {int(beh['loser'].sum()):,} pecundang (copy < 0,7x).")
    prio = 2 * 0.0005 * 104 / MAX_STAKE
    print(f"  Biaya tetap per trade di $20: priority fee 2 x 0,0005 SOL = {prio:.1%}.")


# ---------------------------------------------------------------- utama
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    cfg = ms.load_config(a.data)
    coins, wid, n_bad = load(a.data)
    N = len(coins)
    W, P, T = coins[:N // 4], coins[N // 4:N // 2], coins[N // 2:]
    ts = lambda c: time.strftime("%d/%m %H:%M", time.gmtime(c.t0))
    print(f"== {N:,} koin pump.fun dengan data wallet ({n_bad} kurva tidak standar dibuang), {len(wid):,} wallet. "
          f"Baca {time.time() - t_start:.0f} dtk.")
    print(f"   W nilai wallet {ts(W[0])}-{ts(W[-1])} | P pilih {ts(P[0])}-{ts(P[-1])} | T uji {ts(T[0])}-{ts(T[-1])} UTC")
    lists, beh, sizes = wallet_lists(W, len(wid), cfg)
    for k, v in sizes.items():
        print(f"   {k}: {v} wallet")

    diagnose(T, beh)
    best = {}

    # F0 pembanding
    print("\n==== F0 PEMBANDING (tanpa pemilihan): beli semua koin umur 60 dtk")
    for ex in ("trail", "time3m"):
        tr = [(c.t0 + 60, r, c.t0 + r[2]) for c in T if c.end > 70 for r in [sim_trade(c, 60.0, ex)] if r]
        print(line(f"semua koin, exit {ex}", summary(tr, "2,5%"), "2,5%"))

    # F1 pure copy
    cf = [(f"{ln[:2]}, {k} wallet, exit {ex}", (ln, k, ex)) for ln in lists for k in (1, 2)
          for ex in ("follow", "wide", "time2m")]
    best["F1 pure copy trade"] = family_run("F1 PURE COPY TRADE (abaikan scanning, ikut wallet berkualitas)", cf,
                                            f1_signals(lists), P, T)

    # F2 konfirmasi
    cf = [(f"umur {a}s, naik >= {g}x di paruh kedua, net beli >= {nb} SOL, exit {ex}", (a, g, nb, ex))
          for a in (120, 300, 600) for g in (1.0, 1.3, 2.0) for nb in (2, 10) for ex in ("trail", "time3m", "voldecay")]
    best["F2 entry setelah konfirmasi"] = family_run("F2 ENTRY SETELAH KONFIRMASI HARGA & ARUS BELI", cf, f2_signals, P, T)

    # F3 frekuensi rendah
    def vol5(c):
        return vol_until(c, 300) if c.end > 310 and price_at(c, 299) >= price_at(c, 119) else -1
    vP = np.array([vol5(c) for c in P])
    daysP = (P[-1].t0 - P[0].t0) / 86400
    cf = []
    for per_day in (1, 2):
        q = max(0.0, 1 - per_day / (len(P) / daysP))
        thr = float(np.quantile(vP, q))
        for ex in ("trail", "time3m", "voldecay"):
            cf.append((f"volume 5 mnt >= {thr:.0f} SOL (~{per_day}/hari di P), masuk umur 300s, exit {ex}",
                       (thr, ex, per_day)))

    def f3(coins, prm):
        thr, ex, _ = prm
        return [(c.t0 + 300, r, c.t0 + r[2]) for c in coins if vol5(c) >= thr
                for r in [sim_trade(c, 300.0, ex)] if r]
    global N_TESTED
    N_TESTED += len(cf)
    print(f"\n==== F3 FREKUENSI RENDAH (conviction = volume 5 menit pertama tertinggi, ambang dari P, maks 2/hari)")
    for lab, prm in cf:
        trT = f3(T, prm)
        s25, s6 = summary(trT, "2,5%", 2), summary(trT, "6%", 2)
        print(f" {lab}")
        print(line("T", s25, "2,5%"))
        print(line("T", s6, "6%"))
        print(f"    -> {verdict(s25, s6)}")
        sP = summary(f3(P, prm), "2,5%", 2)
        if "F3" not in best or sP["mean"] > best["F3"][0]:
            best["F3"] = (sP["mean"], lab, s25, s6)

    # F4 exit
    rs = random.Random(3)
    Ps = [c for c in P if c.end > 70]
    Ts = [c for c in T if c.end > 70]
    Ps, Ts = rs.sample(Ps, min(20000, len(Ps))), rs.sample(Ts, min(20000, len(Ts)))

    def f4(coins, ex):
        return [(c.t0 + 60, r, c.t0 + r[2]) for c in coins for r in [sim_trade(c, 60.0, ex)] if r]
    best["F4 exit waktu/volume"] = family_run(
        "F4 EXIT BERBASIS WAKTU / VOLUME (masuk netral: semua koin umur 60 dtk, sampel 20 rb)",
        [(f"exit {ex}", ex) for ex in F4_EXITS], f4, Ps, Ts)

    # F5 perilaku wallet
    fc = {}
    for c in P + T:
        for a_ in (60, 120):
            if c.end > a_ + 10:
                f = feats(c, a_, beh)
                if f:
                    fc[(c.i, a_)] = f
    thr = {}
    for a_ in (60, 120):
        for f in F5_FEATS:
            v = np.array([fc[(c.i, a_)][f] for c in P if (c.i, a_) in fc])
            thr[(a_, f)] = sorted(set(np.round(np.quantile(v, [0.33, 0.67]), 4)))
    cf = [(f"umur {a_}s, {f} {op} {t}, exit {ex}", (a_, f, op, t, ex)) for a_ in (60, 120) for f in F5_FEATS
          for t in thr[(a_, f)] for op in ("<=", ">=") for ex in ("trail", "time3m")]

    def f5(coins, prm):
        a_, f, op, t, ex = prm
        out = []
        for c in coins:
            x = fc.get((c.i, a_))
            if not x or not ((x[f] <= t) if op == "<=" else (x[f] >= t)):
                continue
            r = sim_trade(c, float(a_), ex)
            if r:
                out.append((c.t0 + a_, r, c.t0 + r[2]))
        return out
    best["F5 perilaku wallet"] = family_run("F5 FILTER PERILAKU WALLET (bot, sniper, flipper, konsentrasi, dev jual)",
                                           cf, f5, P, T)

    # F6 gabungan
    b2, b5 = best.get("F2 entry setelah konfirmasi"), best.get("F5 perilaku wallet")
    if b2 and b5:
        a2, g2, nb2, ex2 = b2[0][2]
        a5, f5n, op5, t5, _ = b5[0][2]

        def f6(coins, _):
            out = []
            for c in coins:
                if c.end <= a2 + 10:
                    continue
                x = feats(c, a2, beh)
                if not x or not ((x[f5n] <= t5) if op5 == "<=" else (x[f5n] >= t5)):
                    continue
                out.extend(f2_signals([c], (a2, g2, nb2, ex2)))
            return out
        best["F6 gabungan F2+F5"] = family_run(
            f"F6 GABUNGAN: F2 terbaik + filter wallet F5 terbaik ({f5n} {op5} {t5}, dihitung di umur {a2}s)",
            [("F2+F5", None)], f6, P, T)

    print("\n==== RINGKASAN (periode T, biaya 2,5% dan 6%)")
    for k, v in best.items():
        if not v:
            print(f"  {k}: tidak ada konfigurasi dengan >= 30 sinyal di P")
            continue
        s25, s6 = (v[1], v[2]) if k != "F3" else (v[2], v[3])
        lab = v[0][1] if k != "F3" else v[1]
        print(f"  {k} [{lab}]")
        print(line("T", s25, "2,5%"))
        print(line("T", s6, "6%"))
        print(f"    -> {verdict(s25, s6)}")
    print(f"\n  Total konfigurasi diuji: {N_TESTED}. Dengan sebanyak ini, beberapa yang 'untung' di P bisa muncul "
          "karena kebetulan; hanya hasil T yang dihitung.")
    print(f"  Selesai {time.time() - t_start:.0f} dtk. Paper saja. Data 7 hari (20-27 Okt 2026), "
          "Jan 2026 - sekarang tidak bisa disimulasikan.")


if __name__ == "__main__":
    main()

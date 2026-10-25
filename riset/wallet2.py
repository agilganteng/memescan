"""Copy trade wallet teratas dengan banyak syarat sekaligus (25 Okt 2026).

Data: semua trade beli/jual di 5 menit pertama tiap koin pump.fun (direkam sejak 20 Okt).
  A (50% data paling lama)  : nilai tiap wallet
  B (20% berikutnya)        : pilih aturan terbaik
  C (30% paling baru)       : uji sekali + simulasi $200
Nilai wallet di A (wallet dengan >= 3 koin):
  - hasil kalau KITA yang copy (masuk 3 dtk setelah dia beli, jual 3 dtk setelah dia jual)
  - hasil wallet itu sendiri (SOL keluar vs SOL masuk, sisa token dinilai harga terakhir)
  - persentase menang (copy), konsisten (copy untung di paruh 1 DAN paruh 2 periode A)
  - bukan bot sniper (median beli pertama >= 2 dtk setelah koin dibuat)
  - bukan bot spam (koin per hari <= 30)
  - ukuran beli rata-rata (>= 0,3 SOL = serius)
Sinyal: k wallet terpilih (1/2/3) sudah beli di koin yang sama -> kita beli 3 dtk kemudian.
Jual: ikut jual saat wallet terpilih jual (SL 50% jaga-jaga, maks umur 5 menit) | TP 2x SL 35% 5 mnt |
      TP 1,5x SL 25% 2 mnt | TP 3x SL 40% 15 mnt.
Biaya sama dengan riset lain: jeda 3 dtk, fee 1,25%, slippage 2%, priority fee, dampak kurva.

Pakai: python3 riset/wallet2.py --data data
"""
import argparse
import bisect
import itertools
import json
import math
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

SIZE = 0.1
STAKE, START, STOP = 20.0, 200.0, 40.0
FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}
EXITS = (("ikut jual", None), ("TP 2x SL 35% 5 mnt", (2.0, 0.35, 300)),
         ("TP 1.5x SL 25% 2 mnt", (1.5, 0.25, 120)), ("TP 3x SL 40% 15 mnt", (3.0, 0.4, 900)))
TIME_LIMIT = 22 * 60


class Coin:
    __slots__ = ("t0", "end", "m0", "cs", "starts", "buys", "sells")


def price_at(c, t):
    i = bisect.bisect_right(c.starts, t) - 1
    return c.cs[i][4] if i >= 0 else c.m0


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
                    c.cs = [(ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), x[1], x[2], x[3]) for x in r["c"]]
                    c.starts = [x[0] for x in c.cs]
                    b, s = {}, {}
                    for age, w, isbuy, sol in r["w"]:
                        i = wid.setdefault(w, len(wid))
                        (b if isbuy else s).setdefault(i, []).append((float(age), float(sol)))
                    c.buys, c.sells = b, s
                except (ValueError, KeyError, TypeError, IndexError):
                    continue
                if c.cs and c.m0 > 0:
                    coins.append(c)
    coins.sort(key=lambda c: c.t0)
    return coins, wid, n_bad


def cost(x, cfg):
    f = ((1 - cfg["FEE_PCT"]) * (1 - cfg["SLIPPAGE"])) ** 2
    return x * f - 2 * cfg["PRIORITY_FEE"] / SIZE


def wallet_stats(coins, n_w, cfg, t_mid):
    """Statistik tiap wallet dari koin periode A."""
    n = np.zeros(n_w)
    cp_sum, cp_win, cp_h1, cp_h1n, cp_h2, cp_h2n = (np.zeros(n_w) for _ in range(6))
    buy_sol, val_sol, own_win, snipe, sold = (np.zeros(n_w) for _ in range(5))
    d = cfg["EXEC_DELAY"]
    for c in coins:
        p_last = c.cs[-1][4]
        for w, bl in c.buys.items():
            a = bl[0][0]
            sl = [x for x in c.sells.get(w, []) if x[0] >= a]
            p_in = price_at(c, a + d)
            if p_in <= 0 or a + d >= c.end:
                continue
            s_age = sl[0][0] if sl else min(c.end, max(a + d, 300.0))
            x = cost(price_at(c, min(s_age + d, c.end)) / p_in, cfg)
            bsol = sum(v for _, v in bl)
            tok = sum(v / max(price_at(c, t), 1e-9) for t, v in bl) - sum(v / max(price_at(c, t), 1e-9) for t, v in sl)
            ssol = sum(v for _, v in sl)
            val = ssol + max(0.0, tok) * p_last
            n[w] += 1
            cp_sum[w] += x
            cp_win[w] += x > 1
            if c.t0 < t_mid:
                cp_h1[w] += x
                cp_h1n[w] += 1
            else:
                cp_h2[w] += x
                cp_h2n[w] += 1
            buy_sol[w] += bsol
            val_sol[w] += val
            own_win[w] += val > bsol
            snipe[w] += a < 2.0
            sold[w] += bool(sl)
    with np.errstate(invalid="ignore", divide="ignore"):
        S = {
            "n": n, "cp_mean": cp_sum / n, "cp_win": cp_win / n,
            "consist": (cp_h1 / cp_h1n > 1) & (cp_h2 / cp_h2n > 1),
            "own_roi": val_sol / buy_sol, "own_win": own_win / n,
            "sniper": snipe / n > 0.5, "buy_avg": buy_sol / n, "sold": sold / n,
        }
    return S


def follow_trade(c, entry_age, exit_age, cfg):
    """Masuk di entry_age, keluar 3 dtk setelah wallet jual (exit_age) atau SL 50%."""
    te = entry_age + cfg["EXEC_DELAY"]
    if te >= c.end:
        return None
    p_in = price_at(c, te)
    entry = p_in * (1 + SIZE / ms.v_sol_at(p_in)) / ((1 - cfg["FEE_PCT"]) * (1 - cfg["SLIPPAGE"]))
    tx = min(c.end, exit_age + cfg["EXEC_DELAY"])
    out = None
    for a, b, h, lo, cl in c.cs:
        if a <= te:
            continue
        if a >= tx:
            break
        if lo <= entry * 0.5:
            out, tx = min(entry * 0.5, cl), b
            break
    if out is None:
        out = price_at(c, tx)
    sell = out * (1 - cfg["FEE_PCT"]) * (1 - cfg["SLIPPAGE"]) / (1 + SIZE / ms.v_sol_at(out))
    return sell / entry - 2 * cfg["PRIORITY_FEE"] / SIZE, tx


def sim200(tr):
    bal, busy, n, w = START, -1.0, 0, 0
    for t, m, tx in sorted(tr):
        if t < busy or bal < STOP:
            continue
        bal += min(STAKE, bal) * (m - 1)
        busy, n, w = tx, n + 1, w + (m > 1)
    return bal, n, w


def stat(v):
    v = np.asarray(v, dtype=float)
    n = len(v)
    if n < 2:
        return n, float("nan"), float("nan"), float("nan")
    m, sd = float(v.mean()), float(v.std(ddof=1))
    return n, m, m - 1.96 * sd / math.sqrt(n), float((v > 1).mean())


def fmt(st):
    n, m, lo, w = st
    return f"n={n}, menang {w:.0%}, rata {m:.3f}x (CI bawah {lo:.3f})" if n >= 2 else f"n={n}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    cfg = ms.load_config(a.data)
    coins, wid, n_bad = load(a.data)
    N = len(coins)
    if N < 3000:
        print(f"Baru {N} koin dengan data wallet.")
        return
    iA, iB = int(N * 0.5), int(N * 0.7)
    A, B, C = coins[:iA], coins[iA:iB], coins[iB:]
    ts = lambda c: time.strftime("%d/%m %H:%M", time.gmtime(c.t0))
    print(f"== {N:,} koin dengan data wallet ({n_bad} kurva tidak standar dibuang), {len(wid):,} wallet unik. "
          f"Baca {time.time() - t_start:.0f} dtk.")
    print(f"   A nilai wallet {ts(A[0])}-{ts(A[-1])} | B pilih aturan {ts(B[0])}-{ts(B[-1])} | "
          f"C uji {ts(C[0])}-{ts(C[-1])} UTC")
    S = wallet_stats(A, len(wid), cfg, A[len(A) // 2].t0)
    days = max(1e-9, (A[-1].t0 - A[0].t0) / 86400)
    S["per_day"] = S["n"] / days
    base = S["n"] >= 3
    print(f"   {int(base.sum()):,} wallet punya >= 3 koin di A. Dari mereka: copy rata-rata >1x: "
          f"{int((base & (S['cp_mean'] > 1)).sum()):,}, sniper bot: {int((base & S['sniper']).sum()):,}, "
          f">30 koin/hari: {int((base & (S['per_day'] > 30)).sum()):,}")

    # beli pertama tiap (koin, wallet) di B dan C, urut per koin lalu umur (array datar)
    def first_buys(cl):
        ci_, ag_, w_ = [], [], []
        for ci, c in enumerate(cl):
            for t, w in sorted((bl[0][0], w) for w, bl in c.buys.items()):
                ci_.append(ci)
                ag_.append(t)
                w_.append(w)
        return np.array(ci_, dtype=np.int64), np.array(ag_), np.array(w_, dtype=np.int64)
    FB = {"B": first_buys(B), "C": first_buys(C)}
    cache = {}
    trig_cache = {}

    def triggers(rule_id, mask, k, period):
        key = (rule_id, k, period)
        if key in trig_cache:
            return trig_cache[key]
        CI, AG, W = FB[period]
        idx = np.nonzero(mask[W])[0]
        out = []
        if len(idx):
            cc = CI[idx]
            new = np.r_[True, cc[1:] != cc[:-1]]
            gstart = np.maximum.accumulate(np.where(new, np.arange(len(idx)), 0))
            rank = np.arange(len(idx)) - gstart
            for j in np.nonzero(rank == k - 1)[0]:
                out.append((int(cc[j]), float(AG[idx[j]]), tuple(int(W[idx[j - r]]) for r in range(k))))
        trig_cache[key] = out
        return out

    def run(rule_id, mask, k, e, period):
        cl = B if period == "B" else C
        tr = []
        for ci, ent, ws in triggers(rule_id, mask, k, period):
            c = cl[ci]
            if e == 0:
                sells = [t for w in ws for t, _ in c.sells.get(w, []) if t > ent]
                ex = min(sells) if sells else min(c.end, max(ent, 300.0))
                key = (period, ci, ent, e, ex)
                if key not in cache:
                    cache[key] = follow_trade(c, ent, ex, cfg)
            else:
                key = (period, ci, ent, e)
                if key not in cache:
                    tp, sl, T = EXITS[e][1]
                    x = ms.res_trade(c.cs, c.end, ent, price_at(c, ent), tp, sl, T, cfg, SIZE)
                    cache[key] = (x[0], x[1]) if x else None
            x = cache[key]
            if x:
                tr.append((c.t0 + ent + cfg["EXEC_DELAY"], x[0], c.t0 + x[1]))
        return tr

    grid = list(itertools.product((3, 5, 10), (1.0, 1.2, 1.5), (0.0, 0.4), (0.0, 1.2), (0, 1), (0, 1), (1e9, 30), (0.0, 0.3)))
    rules = []
    for g in grid:
        mn, cpm, cpw, own, cons, nosnipe, maxday, minbuy = g
        m = (S["n"] >= mn) & (S["cp_mean"] >= cpm) & (S["cp_win"] >= cpw) & (S["own_roi"] >= own) \
            & (S["per_day"] <= maxday) & (S["buy_avg"] >= minbuy)
        if cons:
            m &= S["consist"]
        if nosnipe:
            m &= ~S["sniper"]
        m = np.nan_to_num(m).astype(bool)
        if m.sum() >= 3:
            rules.append((g, m))
    print(f"   {len(grid)} aturan pilih wallet x 3 sinyal (1/2/3 wallet) x 4 aturan jual = {len(grid) * 12:,} strategi; "
          f"{len(rules)} aturan punya >= 3 wallet.")

    def lab(g, k, e, nw):
        mn, cpm, cpw, own, cons, nosnipe, maxday, minbuy = g
        parts = [f">= {mn} koin", f"copy rata >= {cpm:g}x"]
        if cpw:
            parts.append(f"copy menang >= {cpw:.0%}")
        if own:
            parts.append(f"untung sendiri >= {own:g}x")
        if cons:
            parts.append("konsisten 2 periode")
        if nosnipe:
            parts.append("bukan sniper bot")
        if maxday < 1e9:
            parts.append(f"<= {maxday} koin/hari")
        if minbuy:
            parts.append(f"beli rata >= {minbuy} SOL")
        return f"{nw} wallet ({', '.join(parts)}); beli saat {k} wallet masuk; jual {EXITS[e][0]}"

    res = []
    stopped = False
    for ri, (g, m) in enumerate(rules):
        for k in (1, 2, 3):
            for e in range(len(EXITS)):
                tr = run(ri, m, k, e, "B")
                if len(tr) >= 30:
                    v = np.array([x[1] for x in tr])
                    res.append(((v.mean() - 1) * len(v) * STAKE, float(v.mean()), len(v), ri, k, e))
        if time.time() - t_start > TIME_LIMIT:
            print(f"   (berhenti di aturan {ri + 1}/{len(rules)} karena batas waktu)")
            stopped = True
            break
    res.sort(key=lambda x: -x[0])
    print(f"\n== {len(res):,} strategi punya >= 30 trade di B, {sum(r[1] > 1 for r in res):,} untung di B. "
          f"({time.time() - t_start:.0f} dtk)")
    ok = 0
    for r in res[:500]:
        st = stat([x[1] for x in run(r[3], rules[r[3]][1], r[4], r[5], "C")])
        ok += st[0] >= 30 and st[1] > 1
    print(f"   Dari 500 terbaik di B, {ok} tetap untung di C (>=30 trade).")
    print("\n== TOP 3 (dipilih di B, diuji sekali di C)")
    seen = set()
    rank = 0
    for r in res:
        sig_ = (int(rules[r[3]][1].sum()), r[2], round(r[1], 4))
        if sig_ in seen:
            continue
        seen.add(sig_)
        rank += 1
        g, m = rules[r[3]]
        tr = run(r[3], m, r[4], r[5], "C")
        st = stat([x[1] for x in tr])
        bal, n, w = sim200(tr)
        lo, hi = ms.wilson(w, n) if n else (0, 0)
        print(f"\n #{rank} {lab(g, r[4], r[5], int(m.sum()))}")
        print(f"    B: n={r[2]}, rata {r[1]:.3f}x")
        print(f"    C (UJI): {fmt(st)} -> {'TERBUKTI' if st[0] >= 30 and st[2] > 1 else 'TIDAK terbukti'}")
        print(f"    SIMULASI $200: {n} trade, menang {w}{f' ({w / n:.0%}, CI {lo:.0%}-{hi:.0%})' if n else ''}, "
              f"akhir ${bal:.2f} ({bal - START:+.2f})" + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))
        if rank == 3:
            break
    # pembanding: wallet "teratas" versi leaderboard (paling untung sendiri), tanpa syarat lain
    top_own = np.zeros(len(wid), bool)
    cand = np.nonzero(S["n"] >= 5)[0]
    top_own[cand[np.argsort(-np.nan_to_num(S["own_roi"][cand]))[:100]]] = True
    tr = run(-1, top_own, 1, 0, "C")
    st = stat([x[1] for x in tr])
    bal, n, w = sim200(tr)
    print(f"\n== PEMBANDING ala leaderboard: 100 wallet paling untung sendiri di A (>= 5 koin), copy semua, ikut jual")
    print(f"    C: {fmt(st)} | $200 -> ${bal:.2f} ({n} trade)")
    print(f"\n   Selesai {time.time() - t_start:.0f} dtk{' (sebagian, kena batas waktu)' if stopped else ''}. "
          "Data wallet mulai 20 Okt 2026, jadi Jan 2026 - sekarang tidak bisa disimulasikan.")


if __name__ == "__main__":
    main()

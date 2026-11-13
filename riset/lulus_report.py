"""Laporan trading koin lulusan PumpSwap (paper), sesuai riset/lulus-praregistrasi.md.

Pakai: python3 riset/lulus_report.py --data data
"""
import argparse
import gzip
import json
import math
import os
from collections import defaultdict

COST = 0.015
H = 3600
EXITS = ["H1 tahan 1j", "H6 tahan 6j", "H24 tahan 24j", "X1 TP2x SL30% 24j", "X2 TP+50% SL25% 6j",
         "X3 trail30% stlh +50% SL40% 24j"]
FILTERS = ["L0 semua lulusan", "L1 rugcheck bersih", "L2 punya akun X", "L3 liq>=$20k", "L4 momentum",
           "L5 L1+L2"]


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def load(data):
    d = os.path.join(data, "lulus")
    toks = {}
    for line in open(os.path.join(d, "tokens.jsonl")):
        try:
            x = json.loads(line)
        except ValueError:
            continue
        toks.setdefault(x["mint"], x)
    px = defaultdict(list)
    for fn in sorted(os.listdir(d)):
        if not fn.startswith("px-"):
            continue
        with gzip.open(os.path.join(d, fn), "rt") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r[1] in toks:
                    px[r[1]].append((r[0], r[2], r[3]))
    for m in px:
        px[m].sort()
    return toks, px


def clean_rc(rec):
    rc = rec.get("rc") or {}
    return bool(rc) and not rc.get("mint_authority") and not rc.get("freeze_authority") and \
        not rc.get("danger") and rc.get("top10_pct") is not None and rc["top10_pct"] <= 30 and \
        (rc.get("insiders") or 0) == 0


def own_x(rec):
    return (rec.get("xp") or {}).get("kind") == "account"


def simulate(rows, i0, p_in, rule):
    """rows: (t, price, liq). Masuk di rows[i0] harga p_in (sebelum biaya). Hasil x setelah biaya."""
    t0 = rows[i0][0]
    buy = p_in * (1 + COST)
    maxh = {"H1": 1, "H6": 6, "H24": 24, "X1": 24, "X2": 6, "X3": 24}[rule] * H
    peak = p_in
    trail_on = False
    last_valid = p_in
    zeros = 0
    t_last = t0
    for t, p, liq in rows[i0 + 1:]:
        if t - t0 > maxh:
            break
        t_last = t
        if p <= 0:
            zeros += 1
            if zeros >= 3:
                return 0.0, t
            continue
        zeros = 0
        if liq < 500:
            return 0.0, t
        last_valid = p
        r = p / p_in
        if rule == "X1":
            if r >= 2.0:
                return 2.0 * p_in * (1 - COST) / buy, t
            if r <= 0.70:
                return p * (1 - COST) / buy, t
        elif rule == "X2":
            if r >= 1.5:
                return 1.5 * p_in * (1 - COST) / buy, t
            if r <= 0.75:
                return p * (1 - COST) / buy, t
        elif rule == "X3":
            peak = max(peak, p)
            if peak >= 1.5 * p_in:
                trail_on = True
            if trail_on and p <= 0.7 * peak:
                return p * (1 - COST) / buy, t
            if not trail_on and r <= 0.60:
                return p * (1 - COST) / buy, t
    return last_valid * (1 - COST) / buy, t_last


def bank(trades, start):
    """trades: (t_in, x, liq, t_out). Posisi bisa tumpang tindih: stake 10% dari ekuitas (kas + posisi
    terbuka di harga beli), dibatasi kas yang ada dan 2% likuiditas."""
    import heapq
    cash, open_ = start, []
    for t_in, x, liq, t_out in sorted(trades):
        while open_ and open_[0][0] <= t_in:
            _, st, xx = heapq.heappop(open_)
            cash += st * xx
        eq = cash + sum(st for _, st, _ in open_)
        stake = min(eq * 0.10, cash, liq * 0.02)
        if stake <= 0.01:
            continue
        cash -= stake
        heapq.heappush(open_, (t_out, stake, x))
    return cash + sum(st * xx for _, st, xx in open_)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    toks, px = load(a.data)
    t_end = max(r[-1][0] for r in px.values() if r)
    print(f"data: {len(toks)} koin lulus, {sum(len(v) for v in px.values()):,} baris harga, "
          f"akhir data {t_end}")
    ev = []
    skip = defaultdict(int)
    for m, rec in toks.items():
        rows = px.get(m) or []
        ts = rec.get("t_seen") or 0
        if ts > t_end - 24 * H:
            skip["<24j data"] += 1
            continue
        i0 = next((i for i, r in enumerate(rows) if r[0] >= ts + 30 and r[1] > 0), None)
        if i0 is None:
            skip["tanpa harga"] += 1
            continue
        t_in, p_in, liq_in = rows[i0]
        if liq_in < 5000:
            skip["liq<$5k"] += 1
            continue
        first = next((r[1] for r in rows if r[1] > 0), p_in)
        e = {"m": m, "t": t_in, "liq": liq_in, "sym": (rec.get("ds") or {}).get("symbol"),
             "lag": (ts - rec["t_pool"]) if rec.get("t_pool") else None,
             "f": [True, clean_rc(rec), own_x(rec), liq_in >= 20000, p_in > first, clean_rc(rec) and own_x(rec)],
             "x": {}}
        for k, name in enumerate(EXITS):
            e["x"][k], e.setdefault("to", {})[k] = simulate(rows, i0, p_in, name.split()[0])
        pk24 = max([r[1] for r in rows[i0:] if r[0] - t_in <= 24 * H] + [p_in]) / p_in
        pk72 = max([r[1] for r in rows[i0:]] + [p_in]) / p_in
        e["pk24"], e["pk72"] = pk24, pk72
        ev.append(e)
    print(f"dihitung {len(ev)} koin; dilewati {dict(skip)}")
    ev.sort(key=lambda e: e["t"])
    t_split = ev[len(ev) // 2]["t"]
    print(f"A = sebelum {t_split}, B = sesudahnya\n")

    print("## Puncak harga dari titik masuk (deskriptif)")
    for key, lab in (("pk24", "24 jam"), ("pk72", "72 jam")):
        n = len(ev)
        s = "  ".join(f">={k}x {100 * sum(1 for e in ev if e[key] >= k) / n:.1f}%" for k in (2, 5, 10, 50))
        print(f"  {lab}: {s}")
    print()

    print("## TABEL (rata x per trade setelah biaya 1.5%/sisi)  A -> B")
    passed = []
    for fi, fname in enumerate(FILTERS):
        sel = [e for e in ev if e["f"][fi]]
        for xi, xname in enumerate(EXITS):
            A = [e["x"][xi] for e in sel if e["t"] < t_split]
            B = [e["x"][xi] for e in sel if e["t"] >= t_split]
            ma = sum(A) / len(A) if A else 0
            mb = sum(B) / len(B) if B else 0
            nb = sorted(B)[:-1]
            mnb = sum(nb) / len(nb) if nb else 0
            ok = len(B) >= 30 and ma > 1 and mb > 1 and mnb > 1
            if ok:
                passed.append((fname, xname))
            print(f"  {fname:22s} {xname:32s} A {ma:6.3f}x n={len(A):5d} | B {mb:6.3f}x n={len(B):5d} "
                  f"tanpa-terbaik {mnb:6.3f}{'  LULUS' if ok else ''}")
    print(f"\n## LULUS (n_B>=30, A>1, B>1, B tanpa terbaik >1): {len(passed)} dari {len(FILTERS) * len(EXITS)}")
    for p in passed:
        print("  ", *p)

    print("\n## Simulasi modal (urut waktu, 10% ekuitas/trade, posisi boleh tumpang tindih, stake maks 2% likuiditas), semua data")
    for fi in (0, 1, 5):
        sel = [e for e in ev if e["f"][fi]]
        for xi in range(len(EXITS)):
            tr = [(e["t"], e["x"][xi], e["liq"], e["to"][xi]) for e in sel]
            if not tr:
                continue
            xs = sorted(x for _, x, _, _ in tr)
            win = sum(1 for x in xs if x > 1)
            lo, hi = wilson(win, len(xs))
            print(f"  {FILTERS[fi]} | {EXITS[xi]}: n={len(xs)} rata {sum(xs) / len(xs):.3f}x median "
                  f"{xs[len(xs) // 2]:.3f}x menang {100 * win / len(xs):.0f}% [{100 * lo:.0f}%-{100 * hi:.0f}%]  "
                  + "  ".join(f"${s}->${bank(tr, s):,.0f}" for s in (100, 200, 1000)))

    print("\n## Per telat deteksi (L0, H6)")
    for lo_, hi_ in ((0, 120), (120, 300), (300, 900), (900, 10 ** 9)):
        xs = [e["x"][1] for e in ev if e["lag"] is not None and lo_ <= e["lag"] < hi_]
        if xs:
            print(f"  {lo_}-{hi_} dtk: n={len(xs)} rata {sum(xs) / len(xs):.3f}x")


if __name__ == "__main__":
    main()

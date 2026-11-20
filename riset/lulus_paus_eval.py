#!/usr/bin/env python3
"""Evaluasi pra-registrasi copy pembelian besar di koin lulus (lihat copy-whale/praregistrasi-whale-koin-lulus-2026-11-20.md).

Transaksi: data/paus/paus-*.jsonl.gz (perekam) + transaksi 24 jam terakhir langsung dari GeckoTerminal.
Harga: OHLCV per menit GeckoTerminal untuk tiap pool yang punya sinyal.
"""
import argparse
import bisect
import gzip
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lulus_paus as lp  # noqa: E402

COST = 0.985 ** 2
GAP_SIG = 3600


def load_recorded(data):
    d = os.path.join(data, "paus")
    out = {}
    if not os.path.isdir(d):
        return out
    for fn in sorted(os.listdir(d)):
        if fn.startswith("paus-"):
            for line in gzip.open(os.path.join(d, fn), "rt"):
                try:
                    r = json.loads(line)
                    out[(r[7], r[3], r[4])] = r
                except (ValueError, IndexError):
                    pass
    return out


def fetch_live(out):
    uni = lp.universe()
    print(f"[live] {len(uni)} pool", flush=True)
    for a, v in uni.items():
        dd = lp.get(f"{lp.GT}/pools/{a}/trades?trade_volume_in_usd_greater_than={lp.MIN_USD}")
        for t in (dd or {}).get("data") or []:
            x = t.get("attributes") or {}
            try:
                ts = lp.iso_ts(x.get("block_timestamp"))
                buy = 1 if x.get("kind") == "buy" else 0
                usd = round(float(x.get("volume_in_usd") or 0), 1)
                tx = x.get("tx_hash") or t.get("id")
                if ts and tx:
                    out.setdefault((tx, buy, usd), [round(ts), a, v["mint"], buy, usd, 0.0, x.get("tx_from_address"), tx])
            except (TypeError, ValueError):
                pass
    return out


def ohlcv(pool, t_lo, t_hi):
    """Bar menit [ts, o, h, l, c] naik, dari t_lo sampai t_hi."""
    bars, before = {}, int(t_hi) + 60
    for _ in range(40):
        dd = lp.get(f"{lp.GT}/pools/{pool}/ohlcv/minute?aggregate=1&limit=1000&before_timestamp={before}"
                    f"&currency=usd&token=base")
        lst = ((((dd or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
        if not lst:
            break
        for b in lst:
            bars[int(b[0])] = [int(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4])]
        oldest = min(int(b[0]) for b in lst)
        if oldest <= t_lo or len(lst) < 1000:
            break
        before = oldest
    bs = [bars[k] for k in sorted(bars)]
    # buang lonjakan palsu: close > 3x atau < 1/3 median 5 tetangga
    cl = [b[4] for b in bs]
    keep = []
    for i, b in enumerate(bs):
        nb = sorted(cl[max(0, i - 2):i + 3])
        m = nb[len(nb) // 2]
        if m > 0 and (b[4] > 3 * m or b[4] < m / 3):
            continue
        b[2] = min(b[2], 3 * m) if m > 0 else b[2]
        b[3] = max(b[3], m / 3) if m > 0 else b[3]
        keep.append(b)
    return keep


class Px:
    def __init__(self, bars):
        self.b = bars
        self.t = [x[0] for x in bars]

    def entry(self, t):
        """Bar pertama yang mulai setelah t -> (index, open)."""
        i = bisect.bisect_right(self.t, t)
        if i >= len(self.b) or self.t[i] - t > 900:
            return None
        return i

    def close_at(self, t):
        i = bisect.bisect_right(self.t, t) - 1
        return self.b[i][4] if i >= 0 else None

    def mean60(self, t):
        i, j = bisect.bisect_left(self.t, t - 3600), bisect.bisect_right(self.t, t)
        xs = [x[4] for x in self.b[i:j]]
        return sum(xs) / len(xs) if len(xs) >= 10 else None


def outcomes(px, t, delay, now):
    """dict exit -> kelipatan bersih (None kalau data belum cukup)."""
    i = px.entry(t + delay)
    if i is None:
        return None
    t_in, p_in = px.t[i], px.b[i][1]
    if p_in <= 0:
        return None
    res = {}
    for name, h in (("tahan1j", 3600), ("tahan6j", 21600)):
        if t_in + h <= now and px.t[-1] >= t_in + h - 900:
            res[name] = px.close_at(t_in + h) / p_in * COST
    for name, h in (("tp1.5sl30_6j", 21600), ("tp1.5sl30_24j", 86400)):
        if t_in + h > now:
            continue
        r = None
        for b in px.b[i:]:
            if b[0] > t_in + h:
                break
            if b[3] / p_in <= 0.70:
                r = 0.70 * 0.72
                break
            if b[2] / p_in >= 1.5:
                r = min(b[2] / p_in, 1.5 * 1.1) if b[1] / p_in >= 1.5 else 1.5
                break
        if r is None:
            r = px.close_at(t_in + h) / p_in
        res[name] = r * COST
    return res


def stat(xs):
    n = len(xs)
    if not n:
        return "n=0"
    s = sorted(x for _, x in xs)
    bal, w = 200.0, 0
    for _, x in sorted(xs):
        bal += min(20.0, bal * 0.10) * (x - 1)
        w += x > 1
    tb = (sum(s) - s[-1]) / (n - 1) if n > 1 else float("nan")
    return (f"n={n} rata {sum(s) / n:.3f}x tanpa-terbaik {tb:.3f}x median {s[n // 2]:.3f}x menang {w / n * 100:.0f}% "
            f"$200->${bal:.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--whales", default="")
    a = ap.parse_args()
    now = time.time()
    tr = load_recorded(a.data)
    n_rec = len(tr)
    fetch_live(tr)
    rows = sorted(tr.values())
    print(f"[data] {len(rows)} transaksi >= ${lp.MIN_USD} ({n_rec} dari perekam), "
          f"{sum(r[3] for r in rows)} beli, {len({r[1] for r in rows})} pool", flush=True)
    if not rows:
        return
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))  # noqa: E731
    print(f"[data] {fmt(rows[0][0])} s/d {fmt(rows[-1][0])}", flush=True)
    wl = set()
    if a.whales and os.path.exists(a.whales):
        try:
            wl = {w["w"] for w in json.load(open(a.whales))["wallets"]}
        except (ValueError, KeyError):
            pass
    print(f"[data] daftar whale kita: {len(wl)} wallet", flush=True)
    pools = {}
    for r in rows:
        pools.setdefault(r[1], []).append(r)
    px = {}
    for p, rs in pools.items():
        bars = ohlcv(p, rs[0][0] - 3700, now)
        if len(bars) >= 30:
            px[p] = Px(bars)
    print(f"[harga] {len(px)} dari {len(pools)} pool punya bar menit", flush=True)

    # hasil +1 jam tiap beli (untuk riwayat wallet, B4)
    hist = {}
    for r in rows:
        if r[3] and r[1] in px:
            o = outcomes(px[r[1]], r[0], 0, now)
            if o and "tahan1j" in o:
                hist.setdefault(r[6], []).append((r[0], o["tahan1j"]))

    def good_wallet(w, t):
        h = [x for tt, x in hist.get(w, []) if tt + 3700 <= t]
        return len(h) >= 3 and sum(h) / len(h) > 1.0

    rnd = random.Random(20)
    SIG = {
        "B6 beli >= $1.000": lambda r, P: r[3] and r[4] >= 1000,
        "B7 beli >= $2.000 (~Rp 30 jt)": lambda r, P: r[3] and r[4] >= 2000,
        "B1 beli >= $5.000": lambda r, P: r[3] and r[4] >= 5000,
        "B2 beli >= $10.000": lambda r, P: r[3] and r[4] >= 10000,
        "B3 beli >= $5.000 saat harga <= 0,8x rata2 60m": lambda r, P: r[3] and r[4] >= 5000 and (
            (lambda m, c: m is not None and c is not None and c <= 0.8 * m)(P.mean60(r[0] - 60), P.close_at(r[0] - 60))),
        "B3b beli >= $1.000 saat harga <= 0,8x rata2 60m": lambda r, P: r[3] and r[4] >= 1000 and (
            (lambda m, c: m is not None and c is not None and c <= 0.8 * m)(P.mean60(r[0] - 60), P.close_at(r[0] - 60))),
        "B4 beli >= $5.000, wallet riwayat bagus": lambda r, P: r[3] and r[4] >= 5000 and good_wallet(r[6], r[0]),
        "B4b beli >= $1.000, wallet riwayat bagus": lambda r, P: r[3] and r[4] >= 1000 and good_wallet(r[6], r[0]),
        "B5 beli >= $2.000, wallet di daftar whale kita": lambda r, P: r[3] and r[4] >= 2000 and (r[6] or "")[:10] in wl,
        "B0 kontrol: beli $1.000-$2.000": lambda r, P: r[3] and 1000 <= r[4] < 2000,
        "K1 kontrol: setelah JUAL >= $1.000": lambda r, P: (not r[3]) and r[4] >= 1000,
    }
    EX = ("tahan1j", "tahan6j", "tp1.5sl30_6j", "tp1.5sl30_24j")
    res = {k: {(d, e): [] for d in (0, 300) for e in EX} for k in list(SIG) + ["K2 kontrol: menit acak, pool sama"]}
    for k, fn in SIG.items():
        last = {}
        for r in rows:
            P = px.get(r[1])
            if P is None or r[0] - last.get(r[1], 0) < GAP_SIG:
                continue
            try:
                if not fn(r, P):
                    continue
            except (TypeError, ValueError):
                continue
            last[r[1]] = r[0]
            for d in (0, 300):
                o = outcomes(P, r[0], d, now)
                for e, x in (o or {}).items():
                    res[k][(d, e)].append((r[0], x))
    for p, P in px.items():
        t0, t1 = pools[p][0][0], pools[p][-1][0]
        n = max(1, int((t1 - t0) / GAP_SIG))
        for j in range(n):
            t = t0 + (j + rnd.random()) * GAP_SIG
            for d in (0, 300):
                o = outcomes(P, t, d, now)
                for e, x in (o or {}).items():
                    res["K2 kontrol: menit acak, pool sama"][(d, e)].append((t, x))
    lolos = []
    for k, cells in res.items():
        print(f"\n## {k}", flush=True)
        for (d, e), xs in cells.items():
            if not xs:
                continue
            xs.sort()
            h = len(xs) // 2
            A, B = xs[:h], xs[h:]
            print(f"  telat {'1m' if d == 0 else '5m'} {e:14s} SEMUA {stat(xs)}", flush=True)
            print(f"        {'':17s} A {stat(A)} | B {stat(B)}", flush=True)
            if len(xs) >= 30 and len(A) >= 2 and len(B) >= 2:
                def tb(v):
                    s = sorted(x for _, x in v)
                    return (sum(s) - s[-1]) / (len(s) - 1)
                if tb(xs) > 1 and tb(A) > 1 and tb(B) > 1 and not k.startswith(("B0", "K")):
                    lolos.append((k, d, e))
    print(f"\n[ringkas] LOLOS (n>=30, tanpa-terbaik >1 di semua, A dan B): {len(lolos)}", flush=True)
    for x in lolos:
        print("  LOLOS", x, flush=True)


if __name__ == "__main__":
    main()

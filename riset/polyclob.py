"""Uji pakai data ASLI Polymarket: pasar "Up or Down 5 menit" BTC/ETH/SOL/XRP (28 Okt 2026).

Kenapa: riset/polybtc.py (candle Binance) menemukan bias jam/menit TIDAK bertahan, tapi pola "lawan arah setelah
3 candle searah" bertahan di TRAIN 2023-2025 dan TEST 2026 (ETH 53.7%, SOL 53.1%, XRP 52.7%). Itu dari Binance.
Polymarket beda: resolusi pakai Chainlink, sejak ~Agu 2026 pakai TWAP jendela vs harga awal, ada fee taker
(crypto_fees_v2: 0.07 x p x (1-p) per share), dan harga beli = harga pasar saat jendela mulai.

Data : gamma-api (event per slug {coin}-updown-5m-{ts}: hasil resolusi, deskripsi) + clob prices-history (harga
       per menit). API publik, tanpa key, tanpa trading.
Sampel: blok acak 2 jam (24 jendela berurutan) sejak pasar ada (~Mar 2026). Sinyal streak dihitung dari hasil
       Polymarket sebelumnya di blok yang sama.
Aturan (dipilih SEBELUMNYA dari Binance 2023-2025, jadi seluruh data Polymarket = out-of-sample):
       lawan 3 (utama), plus lawan 2, lawan 1, ikut 3 sebagai pembanding.
Harga masuk: harga Polymarket terakhir <= detik mulai jendela untuk sisi yang dibeli, +0.005 (setengah spread), + fee.
Simulasi $100/$200/$1000: 5% equity per bet, maks $100 per bet, urut waktu.

Pakai: python3 riset/polyclob.py [--blocks 200]
"""
import argparse
import concurrent.futures as cf
import json
import math
import random
import time
import urllib.request

G = "https://gamma-api.polymarket.com"
C = "https://clob.polymarket.com"
COINS = ("btc", "eth", "sol", "xrp")
FEE_RATE = 0.07
HALF_SPREAD = 0.005
CAPS = (100, 200, 1000)
MAXBET = 100.0
RULES = (("lawan 3", 3, -1), ("lawan 2", 2, -1), ("lawan 1", 1, -1), ("ikut 3", 3, 1), ("ikut 1", 1, 1))


def get(u):
    for a in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(1.5 * 2 ** a)
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * 2 ** a)
    return None


def event(coin, t):
    e = get(f"{G}/events?slug={coin}-updown-5m-{t}")
    if not e:
        return None
    m = e[0]["markets"][0]
    try:
        op = [float(x) for x in json.loads(m["outcomePrices"])]
        outs = json.loads(m["outcomes"])
        tok = json.loads(m["clobTokenIds"])
    except Exception:  # noqa: BLE001
        return None
    if sorted(op) != [0.0, 1.0]:
        return None                                  # belum/bermasalah resolusi
    up_i = outs.index("Up")
    return dict(t=t, up=int(op[up_i] == 1.0), twap="TWAP" in e[0].get("description", ""),
                tok_up=tok[up_i], tok_dn=tok[1 - up_i], vol=float(m.get("volumeNum") or 0))


def price_at(tok, t):
    h = get(f"{C}/prices-history?market={tok}&startTs={t-1200}&endTs={t+240}&fidelity=1")
    if not h or not h.get("history"):
        return None, None
    pts = sorted((x["t"], float(x["p"])) for x in h["history"])
    before = [p for ts, p in pts if ts <= t]
    after = [p for ts, p in pts if t < ts <= t + 90]
    return (before[-1] if before else None), (after[0] if after else None)


def find_first(coin, now):
    lo, hi = now - 400 * 86400, now - 86400
    lo -= lo % 86400
    if event(coin, hi - hi % 300):
        while hi - lo > 86400:
            mid = (lo + hi) // 2
            mid -= mid % 300
            if event(coin, mid) or event(coin, mid + 3600):
                hi = mid
            else:
                lo = mid
        return hi
    return None


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return mid - h, mid + h


def ret(p_mid, win):
    p = min(0.99, max(0.01, p_mid + HALF_SPREAD))
    cost = p + FEE_RATE * p * (1 - p)                 # per share
    return (1.0 / cost - 1.0) if win else -1.0


def sim(rs, cap):
    eq, peak, dd = float(cap), float(cap), 0.0
    for r in rs:
        eq += min(eq * 0.05, MAXBET) * r
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
        if eq < 1:
            break
    return eq, dd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=200)
    a = ap.parse_args()
    now = int(time.time())
    end = now - now % 300 - 3600
    rnd = random.Random(5)
    allrows = {}
    for coin in COINS:
        first = find_first(coin, now)
        if not first:
            print(f"{coin}: pasar 5 menit tidak ditemukan")
            continue
        print(f"{coin}: pasar 5 menit pertama ~{time.strftime('%Y-%m-%d', time.gmtime(first))}", flush=True)
        starts = sorted(rnd.randrange(first + 86400, end - 24 * 300) // 300 * 300 for _ in range(a.blocks))
        ts = sorted({s + 300 * i for s in starts for i in range(24)})
        with cf.ThreadPoolExecutor(16) as ex:
            evs = dict(zip(ts, ex.map(lambda t: event(coin, t), ts)))
        rows = []
        for s in starts:
            seq = [evs.get(s + 300 * i) for i in range(24)]
            for i in range(3, 24):
                cur = seq[i]
                hist = seq[i - 3:i]
                if cur is None or any(h is None for h in hist):
                    continue
                d = [1 if h["up"] else -1 for h in hist]     # urutan: [-3, -2, -1]
                rows.append(dict(cur, prev=d))
        # harga saat mulai hanya untuk jendela yang memicu salah satu aturan
        need = []
        for r in rows:
            for _, k, _ in RULES:
                if len(set(r["prev"][-k:])) == 1:
                    need.append(r)
                    break
        with cf.ThreadPoolExecutor(16) as ex:
            prices = list(ex.map(lambda r: (price_at(r["tok_up"], r["t"]), price_at(r["tok_dn"], r["t"])), need))
        for r, (pu, pd) in zip(need, prices):
            r["p_up0"], r["p_up1"] = pu
            r["p_dn0"], r["p_dn1"] = pd
        allrows[coin] = rows
        n = len(rows)
        upr = sum(r["up"] for r in rows) / max(n, 1)
        print(f"  {n} jendela sampel ({sum(r['twap'] for r in rows)} era TWAP), Up {upr*100:.2f}%, "
              f"volume median ${sorted(r['vol'] for r in rows)[n//2]:,.0f}", flush=True)

    print("\n================ HASIL (semua = out-of-sample; aturan dipilih dari Binance 2023-2025)")
    for era_name, era in (("semua", None), ("era start/end (s/d ~Agu)", False), ("era TWAP (~Agu-sekarang)", True)):
        print(f"\n--- {era_name}")
        for name, k, dirn in RULES:
            for coin in list(allrows) + ["GABUNG"]:
                rows = [r for c in allrows for r in allrows[c]] if coin == "GABUNG" else allrows[coin]
                sel = [r for r in rows if (era is None or r["twap"] == era) and len(set(r["prev"][-k:])) == 1]
                sel.sort(key=lambda r: r["t"])
                wins, rs, pin = 0, [], []
                for r in sel:
                    side_up = (r["prev"][-1] * dirn) > 0
                    win = r["up"] == (1 if side_up else 0)
                    wins += win
                    p0 = r.get("p_up0") if side_up else r.get("p_dn0")
                    if p0 is None:
                        continue
                    pin.append(p0)
                    rs.append(ret(p0, win))
                n = len(sel)
                lo, hi = wilson(wins, n)
                if n < 30:
                    print(f"  {name:<8} {coin:<6} n={n} (<30, tidak disimpulkan)")
                    continue
                ev = sum(rs) / len(rs) if rs else float("nan")
                avgp = sum(pin) / len(pin) if pin else float("nan")
                be = (avgp + HALF_SPREAD) * (1 + FEE_RATE * (1 - avgp - HALF_SPREAD)) if pin else float("nan")
                line = (f"  {name:<8} {coin:<6} n={n:>5} win {wins/n*100:5.2f}% [{lo*100:5.2f}-{hi*100:5.2f}] "
                        f"harga masuk rata {avgp:.3f} (breakeven ~{be*100:.1f}%) EV/bet {ev*100:+6.2f}%")
                if coin == "GABUNG" or k == 3:
                    sims = " ".join(f"${c}->${sim(rs, c)[0]:,.0f}" for c in CAPS)
                    line += f" | {sims}"
                print(line)
    # sudah terhargai? harga Up saat mulai vs streak
    print("\nHarga 'Up' saat jendela mulai, dikelompokkan menurut 3 hasil sebelumnya (kalau pasar sudah memperhitungkan"
          " pola, harga tidak ~0.50):")
    for coin, rows in allrows.items():
        for pat in ((-1, -1, -1), (1, 1, 1)):
            ps = [r["p_up0"] for r in rows if tuple(r["prev"]) == pat and r.get("p_up0") is not None]
            p1 = [r["p_up1"] for r in rows if tuple(r["prev"]) == pat and r.get("p_up1") is not None]
            if ps:
                print(f"  {coin} setelah {'DDD' if pat[0] < 0 else 'UUU'}: harga Up saat mulai rata {sum(ps)/len(ps):.3f} "
                      f"(n={len(ps)}), menit pertama {sum(p1)/max(len(p1),1):.3f} (n={len(p1)})")


if __name__ == "__main__":
    main()

"""Polymarket "Bitcoin Up or Down - 5 menit": ada bias jam/menit yang bisa dipakai? (28 Okt 2026)

Klaim @techluisenzo: "temporal bias, jendela waktu BTC dengan edge >65%" + Kelly + filter volatilitas + update Bayes.
Pasar 5 menit Polymarket: bayar $1 kalau harga akhir >= harga awal (Up), selain itu Down.
Proksi harga: candle 5 menit BTCUSDT spot Binance (data.binance.vision, tanpa key). Resolusi asli pakai Chainlink,
bedanya kecil untuk arah 5 menit.

Aturan (ditulis sebelum lihat hasil). Masuk SEBELUM jendela mulai, harga beli ~50c:
  R1 jam+menit : 288 slot (jam UTC x slot 5 menit). Bet arah mayoritas slot kalau |rate-50%| >= thr di TRAIN.
  R2 hari+jam  : 168 sel (hari x jam). Sama.
  R3 momentum  : arah k candle terakhir sama semua (k=1..3) -> ikut atau lawan (dipilih di TRAIN).
  R4 Bayes     : 288 slot, prior Beta(50,50), diupdate tiap hari dengan semua data sebelumnya (walk-forward murni).
  Tiap aturan +/- filter volatilitas (lewati kalau volatilitas 1 jam terakhir > persentil 75 TRAIN, atau hanya
  ambil yang tinggi).
TRAIN = 2023-2025, TEST = 1 Jan 2026 - sekarang (dipakai SEKALI). Pilih varian terbaik di TRAIN, laporkan TEST.
Biaya: ideal (maker, beli 50c, tanpa fee) / taker (ask 50,5c + fee ~1,56%) / realistis (ask 51c + fee 1,56%).
Simulasi $100/$200/$1000: 5% equity per bet, dan half-Kelly (p dari TRAIN, maks 10%), taruhan maks $100.

Pakai: python3 riset/polybtc.py
"""
import calendar
import concurrent.futures as cf
import csv
import io
import math
import sys
import time
import urllib.error
import urllib.request
import zipfile

import numpy as np

BV = "https://data.binance.vision/data/spot"
FIRST = (2023, 1)
SPLIT = calendar.timegm(time.strptime("2026-01-01", "%Y-%m-%d"))
COSTS = {"ideal": (0.50, 0.0), "taker": (0.505, 0.0156), "realistis": (0.51, 0.0156)}
CAPS = (100, 200, 1000)
MAXBET = 100.0        # batas taruhan per jendela (likuiditas buku order 5 menit terbatas)
SYMS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
rng = np.random.default_rng(7)


def get(url):
    for a in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            time.sleep(2 ** a)
        except Exception:  # noqa: BLE001
            time.sleep(2 ** a)
    return None


def rows_zip(b):
    if not b:
        return []
    with zipfile.ZipFile(io.BytesIO(b)) as z:
        txt = z.read(z.namelist()[0]).decode()
    return [r for r in csv.reader(io.StringIO(txt)) if r and r[0][:1].isdigit()]


def klines(sym, now):
    y, m = FIRST
    g = time.gmtime(now)
    jobs = []
    while (y, m) < (g.tm_year, g.tm_mon):
        jobs.append(f"{BV}/monthly/klines/{sym}/5m/{sym}-5m-{y}-{m:02d}.zip")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for d in range(1, g.tm_mday):
        jobs.append(f"{BV}/daily/klines/{sym}/5m/{sym}-5m-{g.tm_year}-{g.tm_mon:02d}-{d:02d}.zip")
    with cf.ThreadPoolExecutor(16) as ex:
        parts = list(ex.map(lambda u: rows_zip(get(u)), jobs))
    rows = {}
    for part in parts:
        for r in part:
            t = int(r[0])
            while t > 1e11:          # ms / us -> detik
                t //= 1000
            rows[t] = (t, float(r[1]), float(r[4]))
    a = np.array(sorted(rows.values()))
    return a


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return mid - h, mid + h


def prep(a):
    t, o, c = a[:, 0].astype(np.int64), a[:, 1], a[:, 2]
    # Polymarket (Chainlink, banyak desimal) hampir tidak pernah seri. Di Binance harga dibulatkan ke tick, jadi
    # candle seri (close == open) cukup sering untuk SOL/XRP. Seri = jendela dibuang, bukan dihitung Up.
    sgn = np.sign(c - o).astype(np.int8)
    up = (sgn > 0).astype(np.int8)
    r = np.log(c / o)
    slot = (t % 86400) // 300                          # 0..287
    dh = ((t // 86400 + 3) % 7) * 24 + (t % 86400) // 3600   # hari (0=Senin) x jam
    vol = np.full(len(t), np.nan)                      # std return 12 candle SEBELUMNYA (tanpa lihat masa depan)
    cs, cs2 = np.concatenate([[0], np.cumsum(r)]), np.concatenate([[0], np.cumsum(r * r)])
    i = np.arange(12, len(t))
    m1 = (cs[i] - cs[i - 12]) / 12
    vol[i] = np.sqrt(np.maximum((cs2[i] - cs2[i - 12]) / 12 - m1 * m1, 0))
    # streak arah k candle sebelumnya: +k kalau k terakhir Up semua, -k kalau Down semua
    prev = np.zeros((4, len(t)), np.int8)
    for k in (1, 2, 3):
        s = np.zeros(len(t), np.int8)
        for j in range(1, k + 1):
            sh = np.roll(sgn, j).astype(np.int16)
            sh[:j] = 0
            s = s + sh
        prev[k] = np.where(np.abs(s) == k, np.sign(s), 0)
    # candle harus berurutan (lewati jendela setelah gap data)
    gap = np.concatenate([[True], np.diff(t) != 300]) | (sgn == 0)
    return dict(tie=(sgn == 0), t=t, up=up, slot=slot, dh=dh, vol=vol, prev=prev, gap=gap)


def pnl_unit(win, cost):
    ask, fee = COSTS[cost]
    return np.where(win, (1 - fee) / ask - 1, -1.0)


def stats(win, cost):
    n = len(win)
    if n == 0:
        return dict(n=0, wr=0, lo=0, hi=0, ev=0)
    k = int(win.sum())
    lo, hi = wilson(k, n)
    return dict(n=n, wr=k / n, lo=lo, hi=hi, ev=float(pnl_unit(win, cost).mean()))


def sim(win, cap, cost, frac):
    eq, peak, dd = float(cap), float(cap), 0.0
    u = pnl_unit(win, cost)
    for x in u:
        eq += min(eq * frac, MAXBET) * x
        peak = max(peak, eq)
        dd = max(dd, 1 - eq / peak)
        if eq < 1:
            break
    return eq, dd


def kelly(p, cost):
    ask, fee = COSTS[cost]
    b = (1 - fee) / ask - 1
    f = (p * b - (1 - p)) / b
    return max(0.0, min(0.10, f / 2))


# ------------------------------------------------------------------ aturan -> (mask bet, arah bet +1 Up / -1 Down)
def rule_cells(D, key, ncell, tr, thr, z=2.0):
    cell = D[key]
    n = np.bincount(cell[tr], minlength=ncell).astype(float)
    k = np.bincount(cell[tr], weights=D["up"][tr], minlength=ncell)
    rate = np.where(n > 0, k / np.maximum(n, 1), 0.5)
    zz = (rate - 0.5) / np.sqrt(0.25 / np.maximum(n, 1))
    pick = (np.abs(rate - 0.5) >= thr) & (np.abs(zz) >= z)
    side = np.where(rate >= 0.5, 1, -1)
    return pick[cell], side[cell], rate


def rule_mom(D, k, follow):
    s = D["prev"][k].astype(int)
    return s != 0, s * (1 if follow else -1)


def rule_bayes(D, thr, a0=50.0):
    """Walk-forward harian: posterior slot dari semua hari SEBELUM hari ini."""
    t, up, slot = D["t"], D["up"], D["slot"]
    day = t // 86400
    mask = np.zeros(len(t), bool)
    side = np.zeros(len(t), np.int8)
    a = np.full(288, a0)
    b = np.full(288, a0)
    starts = np.concatenate([[0], np.nonzero(np.diff(day))[0] + 1, [len(t)]])
    for s0, s1 in zip(starts[:-1], starts[1:]):
        pm = a / (a + b)
        sl = slot[s0:s1]
        mask[s0:s1] = np.abs(pm[sl] - 0.5) >= thr
        side[s0:s1] = np.where(pm[sl] >= 0.5, 1, -1)
        real = ~D["tie"][s0:s1]
        np.add.at(a, sl, up[s0:s1] * real)
        np.add.at(b, sl, (1 - up[s0:s1]) * real)
    return mask, side


def volmask(D, tr, mode):
    v = D["vol"]
    if mode == "semua":
        return np.ones(len(v), bool)
    q = np.nanpercentile(v[tr], 75)
    ok = ~np.isnan(v)
    return ok & (v <= q) if mode == "tenang" else ok & (v > q)


def variants(D, tr):
    out = []
    for vm in ("semua", "tenang", "ramai"):
        V = volmask(D, tr, vm)
        for thr in (0.01, 0.02, 0.03, 0.05):
            for z in (0.0, 2.0):
                m, s, _ = rule_cells(D, "slot", 288, tr, thr, z)
                out.append((f"R1 jam+menit thr{thr:.2f} z{z:.0f} vol={vm}", m & V, s))
                m, s, _ = rule_cells(D, "dh", 168, tr, thr, z)
                out.append((f"R2 hari+jam thr{thr:.2f} z{z:.0f} vol={vm}", m & V, s))
        for k in (1, 2, 3):
            for fol in (True, False):
                m, s = rule_mom(D, k, fol)
                out.append((f"R3 {'ikut' if fol else 'lawan'} {k} candle vol={vm}", m & V, s))
        for thr in (0.01, 0.02, 0.03):
            m, s = rule_bayes(D, thr)
            out.append((f"R4 Bayes thr{thr:.2f} vol={vm}", m & V, s))
    return out


def fmt(st):
    return f"n={st['n']:>6} win {st['wr']*100:5.2f}% [{st['lo']*100:5.2f}-{st['hi']*100:5.2f}] EV/bet {st['ev']*100:+6.2f}%"


def analyse(sym, a):
    D = prep(a)
    ok = ~D["gap"]
    tr = ok & (D["t"] < SPLIT)
    te = ok & (D["t"] >= SPLIT)
    up = D["up"]
    print(f"\n=================== {sym}: {tr.sum():,} jendela TRAIN 2023-2025, {te.sum():,} jendela TEST 2026 "
          f"(s/d {time.strftime('%Y-%m-%d %H:%M', time.gmtime(int(D['t'][-1])))} UTC)")
    print(f"Candle seri (close == open, dibuang): {D['tie'].mean()*100:.2f}%")
    print(f"Base rate Up: TRAIN {up[tr].mean()*100:.2f}%  TEST {up[te].mean()*100:.2f}%")
    # klaim '>65%': berapa slot yang segitu, dibanding acak
    _, _, rate_tr = rule_cells(D, "slot", 288, tr, 0)
    _, _, rate_te = rule_cells(D, "slot", 288, te, 0)
    dev_tr, dev_te = np.abs(rate_tr - 0.5), np.abs(rate_te - 0.5)
    print(f"Slot 5-menit (288): rate terjauh dari 50% TRAIN {50+dev_tr.max()*100:.1f}%, TEST {50+dev_te.max()*100:.1f}%. "
          f"Slot >=65% atau <=35%: TRAIN {(dev_tr >= 0.15).sum()}, TEST {(dev_te >= 0.15).sum()}.")
    nte = te.sum() / 288
    print(f"  (dengan ~{nte:.0f} jendela/slot di TEST, acak murni sudah memberi slot terjauh ~{50+100*np.sqrt(0.25/nte)*2.9:.1f}%)")
    corr = np.corrcoef(rate_tr - 0.5, rate_te - 0.5)[0, 1]
    print(f"  korelasi rate slot TRAIN vs TEST: {corr:+.3f} (0 = bias tidak bertahan)")
    _, _, r2tr = rule_cells(D, "dh", 168, tr, 0)
    _, _, r2te = rule_cells(D, "dh", 168, te, 0)
    print(f"Sel hari+jam (168): terjauh TRAIN {50+np.abs(r2tr-0.5).max()*100:.1f}%, TEST {50+np.abs(r2te-0.5).max()*100:.1f}%, "
          f"korelasi {np.corrcoef(r2tr-0.5, r2te-0.5)[0,1]:+.3f}")

    res = []
    for name, m, s in variants(D, tr):
        win = (s == np.where(up == 1, 1, -1))
        a_, b_ = m & tr, m & te
        if name.startswith("R4"):
            a_ = m & tr & (D["t"] >= SPLIT - 2 * 365 * 86400)   # Bayes butuh burn-in: TRAIN 2024-2025
        sa, sb = stats(win[a_], "taker"), stats(win[b_], "taker")
        res.append((name, sa, sb, win[b_], sa["wr"]))
    print(f"\n{len(res)} varian. Breakeven win rate: ideal 50,0%, taker {COSTS['taker'][0]/(1-COSTS['taker'][1])*100:.1f}%, "
          f"realistis {COSTS['realistis'][0]/(1-COSTS['realistis'][1])*100:.1f}%")
    elig = [r for r in res if r[1]["n"] >= 2000]
    elig.sort(key=lambda r: -r[1]["lo"])
    print("\nTop-10 dipilih di TRAIN (urut batas bawah CI win rate, n>=2000) -> hasil TEST:")
    for name, sa, sb, _, _ in elig[:10]:
        print(f"  {name:<40} TRAIN {fmt(sa)}\n  {'':<40} TEST  {fmt(sb)}")
    print("Semua varian momentum/reversal (R3), TRAIN -> TEST:")
    for name, sa, sb, _, _ in res:
        if name.startswith("R3") and name.endswith("semua"):
            print(f"  {name:<40} TRAIN {fmt(sa)} | TEST {fmt(sb)}")
    prof_te = sum(1 for r in res if r[2]["n"] >= 30 and r[2]["lo"] > COSTS["taker"][0] / (1 - COSTS["taker"][1]))
    prof_both = sum(1 for r in res if r[1]["n"] >= 30 and r[2]["n"] >= 30 and r[1]["ev"] > 0 and r[2]["ev"] > 0)
    print(f"Varian dengan CI bawah TEST > breakeven taker: {prof_te} dari {len(res)}. "
          f"EV>0 di TRAIN dan TEST (taker): {prof_both}.")

    if not elig:
        return
    name, sa, sb, wte, p_tr = elig[0]
    print(f"\nSimulasi TEST 2026 aturan pilihan TRAIN: {name}  ({sb['n']} bet)")
    for cost in COSTS:
        st = stats(wte, cost)
        line = []
        for cap in CAPS:
            e5, d5 = sim(wte, cap, cost, 0.05)
            fk = kelly(p_tr, cost)
            ek, dk = sim(wte, cap, cost, fk) if fk > 0 else (cap, 0)
            line.append(f"${cap}->${e5:,.2f} (DD {d5*100:.0f}%) | Kelly{fk*100:.1f}% ${ek:,.2f}")
        print(f"  {cost:<9} win {st['wr']*100:.2f}% [{st['lo']*100:.2f}-{st['hi']*100:.2f}] EV/bet {st['ev']*100:+.2f}%")
        for x in line:
            print(f"     {x}")
    # kontrol acak: bet arah acak di jendela acak dengan jumlah sama
    ctrl = []
    idx = np.nonzero(te)[0]
    for _ in range(200):
        pick = rng.choice(idx, size=min(sb["n"], len(idx)), replace=False)
        side = rng.choice([-1, 1], size=len(pick))
        ctrl.append((side == np.where(up[pick] == 1, 1, -1)).mean())
    ctrl = np.array(ctrl)
    print(f"  kontrol acak (200x, n sama): win {np.mean(ctrl)*100:.2f}%, persentil 95 {np.percentile(ctrl,95)*100:.2f}%")
    # per bulan
    tt = D["t"][te & elig_mask(D, name, tr)]
    if len(tt):
        mo = np.array([time.strftime("%Y-%m", time.gmtime(int(x))) for x in tt])
        ww = wte
        out = []
        for m_ in sorted(set(mo)):
            g = mo == m_
            out.append(f"{m_[5:]}:{ww[g].mean()*100:.1f}%")
        print("  win rate per bulan TEST: " + "  ".join(out))


def elig_mask(D, name, tr):
    for n_, m, _ in variants(D, tr):
        if n_ == name:
            return m
    return np.zeros(len(D["t"]), bool)


def main():
    now = time.time()
    for sym in SYMS:
        a = klines(sym, now)
        if len(a) < 10000:
            print(f"{sym}: data kurang ({len(a)})")
            continue
        analyse(sym, a)
        sys.stdout.flush()
    print("\nCatatan: masuk sebelum jendela mulai di ~50c. Strategi masuk di TENGAH jendela (harga Polymarket sudah"
          " bergerak) tidak bisa diuji tanpa histori order book Polymarket.")


if __name__ == "__main__":
    main()

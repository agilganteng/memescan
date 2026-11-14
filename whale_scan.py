#!/usr/bin/env python3
"""whale_scan: bangun daftar wallet whale / smart money (maks 5000) dari rekaman memescan.

Sumber data: data/rec/rec-*.jsonl (perekam memescan). Tiap koin pump.fun: semua trade beli/jual di 5 menit
pertama (maks 150 trade, wallet = 10 huruf pertama alamat) + candle sampai 30 menit. Harga tiap trade
direkonstruksi dari kurva bonding (mcap = v_sol^2 / 32,19), dipasang ulang ke close candle tiap candle selesai.
Koin dengan kurva tidak standar (bug perekam: harga palsu) dibuang lewat cek identitas kurva di snapshot.

LANGKAH
  1. Hitung tiap wallet: berapa koin dia beli, berapa koin dia jadi dev (pembuat).
  2. Untuk wallet dengan >= MIN_COINS koin: per periode waktu (data dibagi 4 periode sama panjang) hitung
     - PnL sendiri (SOL jual - SOL beli + sisa token dinilai di harga akhir rekaman, maks 30 mnt)
     - hasil COPY kita: beli 3 dtk setelah dia beli, jual 3 dtk setelah dia jual pertama (kalau tidak terlihat
       jual dalam 5 mnt: jual di akhir rekaman). Biaya: fee 1,25%/sisi, slippage 2%/sisi, priority 0,0005 SOL x2,
       ukuran 0,1 SOL.
  3. BUANG (bukan whale/smart money):
     - dev: pernah jadi pembuat >= 2 koin, atau > 10% koinnya dia sendiri yang buat
     - sniper/bundler peluncuran: > 40% beli pertamanya di 2 detik pertama koin
     - bot frekuensi tinggi: rata-rata > 150 koin per hari aktif
     - bot flip/MEV: > 50% koin dijual lagi <= 5 dtk setelah beli
     - bukan whale: rata-rata beli < MIN_BUY SOL per koin
  4. LOLOS (tidak longgar, tidak ketat banget):
     - >= MIN_COINS koin, aktif >= 3 hari berbeda, aktif (>= 2 koin) di >= 2 periode
     - PnL sendiri positif di >= 2/3 periode aktifnya (dan minimal 2 periode), total PnL > 0, ROI >= 5%
     Tier A = lolos + hasil copy 3 dtk rata-rata > 1,0 (>= 10 koin). Tier B = lolos saja.
     Urutan: tier A dulu, lalu skor = konsistensi x log(1 + PnL SOL) x (1 + ROI). Diambil maks 5000.
  5. UJI JUJUR (holdout): daftar dibangun ulang HANYA dari periode 1-3, lalu diuji di periode 4 (belum dilihat):
     - copy wallet daftar vs copy wallet kontrol acak (lolos filter anti-bot, tidak lolos syarat untung)
     - sinyal bot: koin yang dibeli >= N wallet daftar (N = 1..4), masuk 3 dtk setelah wallet ke-N,
       keluar pakai aturan bot (TP 2x jual 50%, trailing 45%, SL -35%, time stop 10 mnt) / tahan 5 mnt.
       Simulasi $200 (10%/trade, maks $20).
  Daftar FINAL (yang dipakai bot) dibangun dari SEMUA periode.

Keluaran (folder --out, default whales/): watchlist.json, status.json, STATUS.md

Batas jujur: wallet hanya terlihat di 5 menit pertama tiap koin di kurva pump.fun (sejak perekam mulai, simpan
14 hari). Wallet yang main di koin lama / PumpSwap / Raydium tidak terlihat. Alamat cuma 10 huruf pertama.
Simulasi Jan 2026 - sekarang TIDAK bisa (data mulai Okt 2026).

Pakai: python3 whale_scan.py --data data --out whales
"""
import argparse
import bisect
import collections
import json
import math
import os
import random
import sys
import time

import memescan as ms

K_CURVE = 30.0 * 1.073e9 / 1e9
FLOOR = 27.0
LAT = 3.0
FEE, SLIP, PRIO, SIZE = 0.0125, 0.02, 0.0005, 0.1
NPER = 4
MAX_WALLETS = 5000
FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}

CRIT = dict(MIN_COINS=10, MIN_DAYS=3, MIN_PER_ACTIVE=2, MIN_BUY=0.5, MIN_ROI=0.05,
            DEV_MAX_N=2, DEV_MAX_SHARE=0.10, SNIPE_AGE=2.0, SNIPE_MAX=0.40, BOT_PER_DAY=150,
            FLIP_S=5.0, FLIP_MAX=0.50, COPY_A=1.0, COPY_A_N=10)


def net(gross):
    return gross * (1 - FEE) ** 2 * (1 - SLIP) ** 2 - 2 * PRIO / SIZE


class Coin:
    __slots__ = ("t0", "end", "m0", "cs", "w", "cov", "dev", "ends", "tt", "tp", "starts")


def iter_coins(data_dir, files=None):
    d = os.path.join(data_dir, "rec")
    for fn in files if files is not None else rec_files(data_dir):
        try:
            f = open(os.path.join(d, fn))
        except OSError:
            continue
        with f:
            for line in f:
                c = parse(line)
                if c is not None:
                    yield c


def rec_files(data_dir):
    d = os.path.join(data_dir, "rec")
    return sorted(fn for fn in os.listdir(d) if fn.startswith("rec-")) if os.path.isdir(d) else []


def parse(line):
    try:
        r = json.loads(line)
        if not r.get("w"):
            return None
        c = Coin()
        c.t0, c.end = float(r["t0"]), float(r["end"])
        c.m0 = float(r.get("m0") or r["snaps"][0][1])
        c.cs = [(ms.rec_bucket_start(x[0]), ms.rec_bucket_end(x[0]), float(x[1]), float(x[2]), float(x[3]))
                for x in r["c"]]
        if not c.cs or c.m0 <= 0:
            return None
        # kurva standar? cek identitas (30 + liq)^2 * 1e9 / mcap ~ 3,219e10 di snapshot (tidak bergantung dump)
        ok_from, bad = False, False
        for sn in r["snaps"]:
            liq, mc = float(sn[FI["liq_sol"]]), float(sn[1])
            if sn[FI["inflow_sol"]] == 0 and sn[FI["growth"]] > 1.05:
                bad = True
            if liq >= 79 or mc <= 0:
                continue
            ok_from = True
            if abs((30 + liq) ** 2 * 1e9 / mc / 3.219e10 - 1) > 0.08:
                bad = True
        if bad or not ok_from:
            return None
        c.w = [(float(a), w, int(b), float(s)) for a, w, b, s in r["w"]]
        c.dev = r.get("dev") or ""
        c.cov = c.w[-1][0] if len(c.w) >= ms.REC_W_MAX else min(ms.REC_W_AGE, c.end)
        c.starts = [x[0] for x in c.cs]
        c.tt = None
        return c
    except (ValueError, KeyError, TypeError, IndexError):
        return None


def candle_close(c, t):
    i = bisect.bisect_right(c.starts, t) - 1
    return c.cs[i][4] if i >= 0 else c.m0


def build_path(c):
    """Harga (mcap SOL) setelah tiap trade; dipasang ulang ke close candle tiap candle selesai."""
    v = math.sqrt(K_CURVE * c.m0)
    ends = [(x[1], x[4]) for x in c.cs if x[1] <= c.cov]
    tt, tp, q = [], [], 0
    for ag, _, isb, sol in c.w:
        if ag > c.cov:
            break
        while q < len(ends) and ends[q][0] < ag:
            v = math.sqrt(K_CURVE * ends[q][1])
            tt.append(ends[q][0])
            tp.append(ends[q][1])
            q += 1
        v = v + sol if isb else max(1e-6, v - sol)
        if v * v / K_CURVE < FLOOR:
            v = math.sqrt(K_CURVE * candle_close(c, ag))
        tt.append(ag)
        tp.append(v * v / K_CURVE)
    c.tt, c.tp = tt, tp


def price_at(c, t):
    """Harga pada umur t (sesudah semua trade dengan umur <= t)."""
    if c.tt is None:
        build_path(c)
    if t <= c.cov:
        k = bisect.bisect_right(c.tt, t) - 1
        return c.tp[k] if k >= 0 else c.m0
    return candle_close(c, min(t, c.end))


def end_price(c):
    return candle_close(c, c.end)


def points(c, t_from):
    """(umur, close, high, low) setelah t_from: tick lalu candle."""
    if c.tt is None:
        build_path(c)
    k = bisect.bisect_right(c.tt, t_from)
    for ag, pr in zip(c.tt[k:], c.tp[k:]):
        yield ag, pr, pr, pr
    for a, b, hi, lo, cl in c.cs:
        if a >= c.cov and b > t_from:
            yield b, cl, hi, lo


def bot_exit(c, te):
    """Aturan jual bot (TP 2x jual 50%, trailing 45%, SL -35%, time stop 10 mnt kalau puncak < 1,3x)."""
    p_in = price_at(c, te) * (1 + SLIP)
    if p_in <= 0:
        return None
    peak, tp1, got, left = 1.0, False, 0.0, 1.0
    for t, cl, hi, lo in points(c, te):
        if t > c.end:
            break
        if lo / p_in <= 0.65:
            # isi stop: harga 3 dtk kemudian, minimal haircut 0,72 dari level stop (temuan riset 1 Nov)
            px = min(price_at(c, t + LAT), p_in * 0.65 * 0.72 if t > c.cov else price_at(c, t + LAT))
            return got + left * net(px / p_in)
        if not tp1 and hi / p_in >= 2.0:
            tp1 = True
            got += 0.5 * net(price_at(c, t + LAT) / p_in)
            left = 0.5
        peak = max(peak, hi / p_in)
        if tp1 and cl / p_in <= peak * 0.55:
            return got + left * net(price_at(c, t + LAT) / p_in)
        if t - te >= 600 and peak < 1.3:
            return got + left * net(price_at(c, t + LAT) / p_in)
    return got + left * net(end_price(c) / p_in)


def savip_exit(c, te):
    """Gaya post @savipww: Risk potong kalau turun 6%, take profit bertahap (1/3 di 1,5x, 1/3 di 2x, sisa trailing 25%).
    Isi order 3 dtk setelah pemicu."""
    p_in = price_at(c, te) * (1 + SLIP)
    if p_in <= 0:
        return None
    got, left, peak, steps = 0.0, 1.0, 1.0, [1.5, 2.0]
    for t, cl, hi, lo in points(c, te):
        if t > c.end:
            break
        if lo / p_in <= 0.94:
            px = price_at(c, t + LAT)
            if t > c.cov:
                px = min(px, p_in * 0.94 * 0.72)
            return got + left * net(px / p_in)
        while steps and hi / p_in >= steps[0]:
            steps.pop(0)
            got += (1 / 3) * net(price_at(c, t + LAT) / p_in)
            left -= 1 / 3
        peak = max(peak, hi / p_in)
        if not steps and cl / p_in <= peak * 0.75:
            return got + left * net(price_at(c, t + LAT) / p_in)
    return got + left * net(end_price(c) / p_in)


def hold_exit(c, te, secs):
    p_in = price_at(c, te) * (1 + SLIP)
    return net(price_at(c, min(te + secs, c.end)) / p_in) if p_in > 0 else None


# ---------------------------------------------------------------- per wallet
# slot statistik per periode: n, pnl, buysol, copy_sum, copy_n, copy_win, own_win
S = 7


def new_acc():
    return [0.0] * (S * NPER) + [0.0, 0.0, 0.0, 0.0, 0.0]   # + snipe, flip, buysol_total, days(bitmask), n


def coin_wallets(c):
    """Per wallet di koin ini: (umur beli pertama, sol beli, sol jual, sisa token, umur jual pertama)."""
    out = {}
    for ag, w, isb, sol in c.w:
        if ag > c.cov:
            break
        p = price_at(c, ag) / ms.SUPPLY       # SOL per token (kira-kira)
        if p <= 0:
            continue
        o = out.get(w)
        if o is None:
            if not isb:
                continue                       # jual tanpa beli terlihat
            o = out[w] = [ag, 0.0, 0.0, 0.0, None]
        if isb:
            o[1] += sol
            o[3] += sol / p
        else:
            o[2] += sol
            o[3] = max(0.0, o[3] - sol / p)
            if o[4] is None:
                o[4] = ag
    return out


def scan(data_dir, files, t_lo, t_hi, cand, dev_n, acc, period_of):
    n = 0
    for c in iter_coins(data_dir, files):
        if not (t_lo <= c.t0 <= t_hi):
            continue
        ws = coin_wallets(c)
        if not ws:
            continue
        per = period_of(c.t0)
        day = int((c.t0 - t_lo) // 86400)
        pend = end_price(c) / ms.SUPPLY
        for w, (a, bsol, ssol, tok, fs) in ws.items():
            if w not in cand or bsol <= 0:
                continue
            A = acc.get(w)
            if A is None:
                A = acc[w] = new_acc()
            pnl = ssol + tok * pend - bsol
            te = a + LAT
            p_in = price_at(c, te) * (1 + SLIP)
            tx = (fs + LAT) if fs is not None else c.end
            cm = net(price_at(c, tx) / p_in) if p_in > 0 and te < c.end else None
            b = per * S
            A[b] += 1
            A[b + 1] += pnl
            A[b + 2] += bsol
            if cm is not None:
                A[b + 3] += cm
                A[b + 4] += 1
                A[b + 5] += cm > 1.0
            A[b + 6] += pnl > 0
            k = S * NPER
            A[k] += a <= CRIT["SNIPE_AGE"]
            A[k + 1] += fs is not None and fs - a <= CRIT["FLIP_S"]
            A[k + 2] += bsol
            A[k + 3] = int(A[k + 3]) | (1 << min(day, 60))
            A[k + 4] += 1
        n += 1
    return n


def judge(w, A, dev_n, pers, CRIT=CRIT):
    """Return (lolos?, alasan, info) memakai periode di `pers`."""
    k = S * NPER
    n = sum(A[p * S] for p in pers)
    if n < CRIT["MIN_COINS"]:
        return False, "koin kurang", None
    tot_n = A[k + 4]
    dn = dev_n.get(w, 0)
    if dn >= CRIT["DEV_MAX_N"] or dn / (tot_n + dn) > CRIT["DEV_MAX_SHARE"]:
        return False, "dev", None
    if A[k] / tot_n > CRIT["SNIPE_MAX"]:
        return False, "sniper/bundler", None
    days = bin(int(A[k + 3])).count("1")
    if tot_n / max(1, days) > CRIT["BOT_PER_DAY"]:
        return False, "bot frekuensi", None
    if A[k + 1] / tot_n > CRIT["FLIP_MAX"]:
        return False, "bot flip", None
    if A[k + 2] / tot_n < CRIT["MIN_BUY"]:
        return False, "beli kecil (bukan whale)", None
    elig = {"n": int(n), "days": days}
    if days < CRIT["MIN_DAYS"]:
        return False, "hari aktif kurang", elig
    act = [p for p in pers if A[p * S] >= 2]
    win = [p for p in act if A[p * S + 1] > 0]
    pnl = sum(A[p * S + 1] for p in pers)
    buy = sum(A[p * S + 2] for p in pers)
    cn = sum(A[p * S + 4] for p in pers)
    cm = sum(A[p * S + 3] for p in pers) / cn if cn else 0.0
    ownw = sum(A[p * S + 6] for p in pers) / n
    info = dict(elig, pnl=pnl, roi=pnl / buy if buy else 0.0, pa=len(act), pw=len(win), copy=cm, copy_n=int(cn),
                win=ownw, buy=buy / n)
    if len(act) < CRIT["MIN_PER_ACTIVE"]:
        return False, "periode aktif kurang", info
    if len(win) < max(2, math.ceil(len(act) * 2 / 3)):
        return False, "tidak konsisten", info
    if pnl <= 0 or info["roi"] < CRIT["MIN_ROI"]:
        return False, "PnL/ROI kurang", info
    if ownw < CRIT.get("MIN_WIN", 0.0):
        return False, "winrate kurang", info
    info["tier"] = "A" if cm > CRIT["COPY_A"] and cn >= CRIT["COPY_A_N"] else "B"
    if CRIT.get("ONLY_A") and info["tier"] != "A":
        return False, "bukan tier A", info
    info["score"] = (len(win) / len(act)) * math.log1p(pnl) * (1 + min(info["roi"], 3.0))
    return True, "lolos", info


def build_list(acc, dev_n, pers, crit=CRIT):
    ok, reasons, elig = [], collections.Counter(), []
    for w, A in acc.items():
        good, why, info = judge(w, A, dev_n, pers, crit)
        reasons[why] += 1
        if good:
            ok.append((w, info))
        elif info is not None:
            elig.append(w)
    ok.sort(key=lambda x: (x[1]["tier"] != "A", -x[1]["score"]))
    return ok[:MAX_WALLETS], reasons, elig, len(ok)


def mstat(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if not n:
        return dict(n=0)
    s = sorted(xs)
    bal, w = 200.0, 0
    for x in xs:
        st = min(20.0, bal * 0.10)
        bal += st * (x - 1)
        w += x > 1
    return dict(n=n, mean=round(sum(xs) / n, 4), median=round(s[n // 2], 4), win=round(w / n, 3),
                sim200=round(bal, 2), mean_wo_best=round((sum(xs) - s[-1]) / (n - 1), 4) if n > 1 else None)


def holdout(data_dir, files, t4, t_hi, listed, control):
    """Uji di periode 4: copy per wallet + sinyal >= N wallet daftar."""
    res = {"copy_daftar": [], "copy_kontrol": []}
    sig = {f"N{k}": {"bot": [], "tahan5m": [], "savip": []} for k in (1, 2, 3, 4)}
    sigc = {f"N{k}": {"bot": [], "tahan5m": []} for k in (1, 2, 3)}
    for c in iter_coins(data_dir, files):
        if not (t4 <= c.t0 <= t_hi):
            continue
        ws = coin_wallets(c)
        order = sorted((v[0], w) for w, v in ws.items())
        hit, hitc = [], []
        for a, w in order:
            v = ws[w]
            grp = "copy_daftar" if w in listed else "copy_kontrol" if w in control else None
            if grp:
                te = a + LAT
                p_in = price_at(c, te) * (1 + SLIP)
                tx = (v[4] + LAT) if v[4] is not None else c.end
                if p_in > 0 and te < c.end:
                    res[grp].append(net(price_at(c, tx) / p_in))
            if w in listed:
                hit.append(a)
            if w in control:
                hitc.append(a)
        for k in (1, 2, 3, 4):
            if len(hit) >= k and hit[k - 1] + LAT < c.end:
                te = hit[k - 1] + LAT
                sig[f"N{k}"]["bot"].append(bot_exit(c, te))
                sig[f"N{k}"]["tahan5m"].append(hold_exit(c, te, 300))
                sig[f"N{k}"]["savip"].append(savip_exit(c, te))
        for k in (1, 2, 3):
            if len(hitc) >= k and hitc[k - 1] + LAT < c.end:
                te = hitc[k - 1] + LAT
                sigc[f"N{k}"]["bot"].append(bot_exit(c, te))
                sigc[f"N{k}"]["tahan5m"].append(hold_exit(c, te, 300))
    out = {g: mstat(v) for g, v in res.items()}
    out["sinyal_daftar"] = {k: {e: mstat(v) for e, v in d.items()} for k, d in sig.items()}
    out["sinyal_kontrol"] = {k: {e: mstat(v) for e, v in d.items()} for k, d in sigc.items()}
    return out


def signals(data_dir, files, t_from, t_to, lists, ns=(2, 3, 4)):
    """lists: {nama: set wallet}. Return {nama: {N: {exit: [mult]}}} untuk koin dengan t0 di [t_from, t_to)."""
    out = {k: {n: {"bot": [], "tahan5m": []} for n in ns} for k in lists}
    for c in iter_coins(data_dir, files):
        if not (t_from <= c.t0 < t_to):
            continue
        ws = coin_wallets(c)
        order = sorted((v[0], w) for w, v in ws.items())
        for k, L in lists.items():
            hit = [a for a, w in order if w in L]
            for n in ns:
                if len(hit) >= n and hit[n - 1] + LAT < c.end:
                    te = hit[n - 1] + LAT
                    out[k][n]["bot"].append(bot_exit(c, te))
                    out[k][n]["tahan5m"].append(hold_exit(c, te, 300))
    return out


def grid(a, files, acc, dev_n, t_lo, span):
    """Pilih varian syarat wallet di periode 3 (daftar dari P1-2), uji SEKALI di periode 4 (daftar dari P1-3)."""
    import itertools
    variants = {}
    for mc, mb, roi, win, sn, ca in itertools.product((10, 20), (0.5, 1.0, 2.0), (0.05, 0.3), (0.0, 0.4),
                                                      (0.4, 0.2), ("semua", "A>1.0", "A>1.2")):
        cr = dict(CRIT, MIN_COINS=mc, MIN_BUY=mb, MIN_ROI=roi, MIN_WIN=win, SNIPE_MAX=sn,
                  ONLY_A=ca != "semua", COPY_A=1.2 if ca == "A>1.2" else 1.0, MIN_PER_ACTIVE=2)
        variants[f"koin>={mc} beli>={mb} roi>={roi} win>={win} snipe<={sn} {ca}"] = cr
    t3, t4 = t_lo + 2 * span, t_lo + 3 * span
    lists12 = {k: {w for w, _ in build_list(acc, dev_n, range(2), cr)[0]} for k, cr in variants.items()}
    lists12 = {k: v for k, v in lists12.items() if v}
    print(f"[grid] {len(variants)} varian, {len(lists12)} punya wallet; uji pilih di P3", flush=True)
    r3 = signals(a.data, files, t3, t4, lists12)
    rows = []
    for k, d in r3.items():
        for n, ex in d.items():
            for e, xs in ex.items():
                st = mstat(xs)
                if st.get("n", 0) >= 30:
                    rows.append((st["mean_wo_best"], st["mean"], k, n, e, st, len(lists12[k])))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    n_ok = sum(1 for r in rows if r[0] > 1.0)
    print(f"[grid] strategi n>=30 di P3: {len(rows)}; untung (tanpa koin terbaik > 1): {n_ok}", flush=True)
    for r in rows[:15]:
        print(f"  P3 {r[2]} | N{r[3]} {r[4]} | wallet {r[6]} | {r[5]}", flush=True)
    top = rows[:5]
    lists123 = {r[2]: {w for w, _ in build_list(acc, dev_n, range(3), variants[r[2]])[0]} for r in top}
    rnd = random.Random(11)
    pool = list(acc)
    ctrl = {f"KONTROL acak {len(v)}": set(rnd.sample(pool, min(len(pool), len(v)))) for v in lists123.values()}
    r4 = signals(a.data, files, t4, math.inf, {**lists123, **ctrl})
    res = []
    print("[grid] UJI SEKALI di P4 (daftar dibangun dari P1-3):", flush=True)
    for r in top:
        st = mstat(r4[r[2]][r[3]][r[4]])
        res.append({"varian": r[2], "N": r[3], "exit": r[4], "wallet": len(lists123[r[2]]), "P3": r[5], "P4": st})
        print(f"  {r[2]} | N{r[3]} {r[4]} | wallet {len(lists123[r[2]])} | P4 {st}", flush=True)
    for k in ctrl:
        print(f"  {k}: " + " ".join(f"N{n} bot {mstat(v['bot'])}" for n, v in r4[k].items()), flush=True)
    return {"n_strategi": len(rows), "untung_P3": n_ok, "top_P3": [dict(varian=r[2], N=r[3], exit=r[4], st=r[5])
                                                                  for r in rows[:15]], "uji_P4": res}


def loose_list(acc, dev_n, pers, min_buy, min_coins=10):
    """Wallet lolos filter anti-bot/dev/sniper saja, diurutkan PnL sendiri di periode `pers`."""
    k = S * NPER
    out = []
    for w, A in acc.items():
        n = sum(A[p * S] for p in pers)
        tot = A[k + 4]
        if n < min_coins or not tot:
            continue
        dn = dev_n.get(w, 0)
        if dn >= CRIT["DEV_MAX_N"] or dn / (tot + dn) > CRIT["DEV_MAX_SHARE"]:
            continue
        days = bin(int(A[k + 3])).count("1")
        if (A[k] / tot > CRIT["SNIPE_MAX"] or tot / max(1, days) > CRIT["BOT_PER_DAY"]
                or A[k + 1] / tot > CRIT["FLIP_MAX"] or A[k + 2] / tot < min_buy):
            continue
        out.append((sum(A[p * S + 1] for p in pers), w))
    out.sort(reverse=True)
    return out


def banyak(a, files, acc, dev_n, t_lo, span):
    """Daftar besar (1000-5000+, syarat longgar) x syarat banyak whale (N 2..12). Pilih P3, uji sekali P4."""
    ns = (2, 3, 5, 8, 10, 12, 15, 20)
    t3, t4 = t_lo + 2 * span, t_lo + 3 * span

    def lists(pers):
        L = {}
        for mb in (0.2, 0.5):
            ll = loose_list(acc, dev_n, pers, mb)
            L[f"semua lolos anti-bot (beli>={mb})"] = {w for _, w in ll}
            L[f"PnL>0 (beli>={mb})"] = {w for p, w in ll if p > 0}
            for top in (1000, 2000, 5000):
                L[f"top {top} PnL (beli>={mb})"] = {w for _, w in ll[:top]}
        return L
    l12 = lists(range(2))
    print("[banyak] ukuran daftar P1-2: " + ", ".join(f"{k}={len(v)}" for k, v in l12.items()), flush=True)
    r3 = signals(a.data, files, t3, t4, l12, ns)
    rows = []
    for k, d in r3.items():
        for n, ex in d.items():
            for e, xs in ex.items():
                st = mstat(xs)
                print(f"  P3 {k} | N{n} {e} | {st}", flush=True)
                if st.get("n", 0) >= 30:
                    rows.append((st["mean_wo_best"], st["mean"], k, n, e, st))
    rows.sort(key=lambda r: (-r[0], -r[1]))
    print(f"[banyak] strategi n>=30 di P3: {len(rows)}; untung tanpa koin terbaik: {sum(r[0] > 1 for r in rows)}",
          flush=True)
    l123 = lists(range(3))
    top = rows[:5]
    r4 = signals(a.data, files, t4, math.inf, {r[2]: l123[r[2]] for r in top}, ns)
    print("[banyak] UJI SEKALI di P4 (daftar dari P1-3):", flush=True)
    for r in top:
        print(f"  {r[2]} ({len(l123[r[2]])} wallet) | N{r[3]} {r[4]} | P3 {r[5]} | P4 {mstat(r4[r[2]][r[3]][r[4]])}",
              flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="whales")
    ap.add_argument("--banyak", action="store_true", help="uji daftar besar x banyak whale")
    ap.add_argument("--grid", action="store_true", help="uji varian syarat (pilih P3, uji P4), tidak menulis daftar")
    a = ap.parse_args()
    t_start = time.time()
    os.makedirs(a.out, exist_ok=True)
    files = rec_files(a.data)
    if not files:
        sys.exit("tidak ada data/rec")
    # langkah 1
    cnt, dev_n = collections.Counter(), collections.Counter()
    t_lo, t_hi, n_coins = math.inf, -math.inf, 0
    for c in iter_coins(a.data, files):
        n_coins += 1
        t_lo, t_hi = min(t_lo, c.t0), max(t_hi, c.t0)
        if c.dev:
            dev_n[c.dev] += 1
        seen = set()
        for ag, w, isb, sol in c.w:
            if isb and w not in seen and ag <= c.cov:
                seen.add(w)
                cnt[w] += 1
    cand = {w for w, n in cnt.items() if n >= CRIT["MIN_COINS"]}
    print(f"[1] {n_coins} koin kurva standar, {len(cnt)} wallet, {len(cand)} wallet >= {CRIT['MIN_COINS']} koin "
          f"({time.time() - t_start:.0f}s)", flush=True)
    del cnt
    span = (t_hi - t_lo) / NPER

    def period_of(t):
        return min(NPER - 1, int((t - t_lo) // span)) if span > 0 else 0

    # langkah 2
    acc = {}
    scan(a.data, files, t_lo, t_hi, cand, dev_n, acc, period_of)
    print(f"[2] statistik {len(acc)} wallet ({time.time() - t_start:.0f}s)", flush=True)
    if a.banyak:
        banyak(a, files, acc, dev_n, t_lo, span)
        return
    if a.grid:
        g = grid(a, files, acc, dev_n, t_lo, span)
        with open(os.path.join(a.out, "grid.json"), "w") as f:
            json.dump(g, f, indent=1)
        return
    # langkah 5 dulu: daftar dari periode 1-3, uji di periode 4
    lst3, reasons3, elig3, nok3 = build_list(acc, dev_n, range(NPER - 1))
    listed3 = {w for w, _ in lst3}
    rnd = random.Random(7)
    pool = [w for w in elig3 if w not in listed3]
    control = set(rnd.sample(pool, min(len(pool), len(listed3)))) if pool else set()
    t4 = t_lo + span * (NPER - 1)
    ho = holdout(a.data, files, t4, t_hi, listed3, control)
    print(f"[5] holdout: daftar P1-3 {len(listed3)} wallet; {json.dumps(ho)[:1500]}", flush=True)
    # daftar final
    lst, reasons, elig, nok = build_list(acc, dev_n, range(NPER))
    tiers = collections.Counter(i["tier"] for _, i in lst)
    now = time.time()
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(t))  # noqa: E731
    wl = {"updated": fmt(now), "updated_ts": round(now), "n": len(lst), "tiers": dict(tiers),
          "note": "alamat = 10 huruf pertama (yang disimpan perekam memescan)",
          "wallets": [dict(w=w, tier=i["tier"], n=i["n"], days=i["days"], pnl_sol=round(i["pnl"], 3),
                           roi=round(i["roi"], 3), periode=f"{i['pw']}/{i['pa']}", copy3s=round(i["copy"], 3),
                           win=round(i["win"], 3), beli_rata_sol=round(i["buy"], 3)) for w, i in lst]}
    with open(os.path.join(a.out, "watchlist.json"), "w") as f:
        json.dump(wl, f, separators=(",", ":"))
    st = {"updated": fmt(now), "wallet_terkumpul": len(lst), "lolos_sebelum_batas": nok, "batas": MAX_WALLETS,
          "tier": dict(tiers), "data": {"koin": n_coins, "dari": fmt(t_lo), "sampai": fmt(t_hi),
                                        "wallet_dicek": len(acc)},
          "alasan_dibuang": dict(reasons), "kriteria": CRIT,
          "holdout_periode4": {"dari": fmt(t4), "daftar_dari_P1_3": len(listed3), **ho},
          "durasi_s": round(now - t_start)}
    with open(os.path.join(a.out, "status.json"), "w") as f:
        json.dump(st, f, indent=1)
    md = [f"# Status scan whale ({fmt(now)})", "",
          f"**Wallet terkumpul: {len(lst)}** (batas {MAX_WALLETS}; yang lolos sebelum dipotong {nok})  ",
          f"Tier A (lolos + copy 3 dtk > 1,0): {tiers.get('A', 0)} · Tier B: {tiers.get('B', 0)}  ",
          f"Data: {n_coins} koin pump.fun, {fmt(t_lo)} s/d {fmt(t_hi)}, {len(acc)} wallet dicek", "",
          "## Uji jujur periode 4 (daftar dibangun dari periode 1-3 saja)", "",
          f"Copy wallet daftar: {ho['copy_daftar']}  ", f"Copy wallet kontrol acak: {ho['copy_kontrol']}  ", ""]
    for k, d in ho["sinyal_daftar"].items():
        md.append(f"- Sinyal {k} wallet daftar: bot {d['bot']} · tahan 5m {d['tahan5m']} · gaya savip "
                  f"(cut -6%, TP bertahap) {d['savip']}")
    for k, d in ho["sinyal_kontrol"].items():
        md.append(f"- Kontrol {k}: bot {d['bot']} · tahan 5m {d['tahan5m']}")
    md += ["", "Alasan dibuang: " + ", ".join(f"{k} {v}" for k, v in reasons.most_common()), ""]
    with open(os.path.join(a.out, "STATUS.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()

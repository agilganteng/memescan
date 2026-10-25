"""Riset: tiru setup "Grok Bot = Robinhood meme sniper" dari artikel X @0xCristal (22 Okt 2026).

Setup aslinya (Robinhood Chain, bukan Solana):
  Scout  : tiap 15 menit cari pool baru (Uniswap V3 PoolCreated).
  Risk   : 5 menit kemudian, lolos kalau isi pool >= 3 WETH, top 10 wallet <= 35%,
           kontrak terverifikasi, owner sudah renounce.
  Desk   : tiket $12 dari bankroll $200 (risiko 1,5%, stop 25%, maks 10%), berhenti
           kalau rugi hari itu sudah 5% ($10). Manusia yang tanda tangan.
Artikel tidak menyebut take profit dan tidak mengklaim hasil apa pun.

Bagian 1: cek apakah RPC Robinhood Chain bisa diakses dan berapa pool baru per jam.
Bagian 2: aturan yang sama dijalankan di rekaman koin pump.fun kita:
  isi pool  -> SOL masuk kurva (liq_sol) di umur 10 menit
  top 10    -> top10 (% supply, tanpa kurva) di umur 10 menit
  verified/renounce -> selalu lolos di pump.fun (kontrak standar, mint authority dicabut)
  masuk     -> umur 10 / 15 / 20 menit (scan 15 menit + cek risk + approve manusia)
  jual      -> SL 25% + (tahan sampai rekaman habis | TP 1,5x | 2x | 3x)
Dipilih di 70% data lama, diuji sekali di 30% data baru, simulasi $200 pakai Desk-nya
($12 per trade, berhenti hari itu kalau rugi $10, satu posisi sekali waktu).
Koin dengan kurva tidak standar (inflow tercatat 0 padahal harga naik) dibuang karena
rekamannya terpotong (bug yang ketemu di riset trailing stop).

Pakai: python3 riset/cristal.py --data data
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.request

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

AGES = (600, 900, 1200)
DEPTH = (5, 10, 20, 40, 70)       # SOL; 3 WETH ~ $7rb ~ 70 SOL
TOP10 = (25, 35, 50, 101)         # 101 = tanpa batas
EXITS = ((1e9, "tahan"), (1.5, "TP 1.5x"), (2.0, "TP 2x"), (3.0, "TP 3x"))
SL, T_MAX = 0.25, 1800.0
SIZE = 0.1
STAKE, START, DAY_HALT = 12.0, 200.0, 10.0
FI = {k: 2 + i for i, k in enumerate(ms.FEATURES)}

RH_RPC = "https://rpc.mainnet.chain.robinhood.com"
RH_CHAIN = 4663
RH_FACTORY = "0x1f7d7550B1b028f7571E69A784071F0205FD2EfA"
POOL_CREATED = "0x783cca1c0412dd0d695e784568c96da2e9c22ff989357a2e8b1d9b2b4e6b7118"


def rpc(method, params):
    req = urllib.request.Request(RH_RPC, json.dumps({"jsonrpc": "2.0", "id": 1, "method": method,
                                                     "params": params}).encode(),
                                 {"Content-Type": "application/json", "User-Agent": "memescan-riset"})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
    if "error" in out:
        raise RuntimeError(out["error"])
    return out["result"]


def probe_robinhood():
    print("== BAGIAN 1: ROBINHOOD CHAIN (chain yang dipakai artikel)")
    try:
        cid = int(rpc("eth_chainId", []), 16)
        head = int(rpc("eth_blockNumber", []), 16)
    except Exception as e:   # noqa: BLE001
        print(f"   RPC {RH_RPC} tidak bisa diakses: {type(e).__name__} {e}")
        return
    print(f"   chainId {cid} ({'cocok' if cid == RH_CHAIN else 'BEDA dengan artikel'}), blok terakhir {head:,}")
    ts = lambda b: int(rpc("eth_getBlockByNumber", [hex(b), False])["timestamp"], 16)
    t_head = ts(head)
    n, end, calls, step = 0, head, 0, 2000
    start = end
    while calls < 300:
        start = max(0, end - step + 1)
        try:
            logs = rpc("eth_getLogs", [{"address": RH_FACTORY, "topics": [POOL_CREATED],
                                        "fromBlock": hex(start), "toBlock": hex(end)}])
        except Exception as e:   # noqa: BLE001
            print(f"   getLogs gagal di blok {start}-{end}: {e}")
            break
        n += len(logs)
        calls += 1
        if t_head - ts(start) >= 86400 or start == 0:
            break
        end = start - 1
    span = max(1, t_head - ts(start))
    print(f"   pool Uniswap V3 baru: {n:,} dalam {span / 3600:.1f} jam terakhir "
          f"= {n / span * 86400:,.0f} per hari (artikel: ~26.000 token per hari di September)")


def load(data_dir):
    d = os.path.join(data_dir, "rec")
    files = [os.path.join(d, f) for f in sorted(os.listdir(d))] if os.path.isdir(d) else []
    cfg = ms.load_config(data_dir)
    rows, n_all, n_bad, n_600 = [], 0, 0, 0
    for fp in files:
        with open(fp) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    t0, end = float(r["t0"]), float(r["end"])
                    snaps = r["snaps"]
                except (ValueError, KeyError, TypeError):
                    continue
                n_all += 1
                if any(s[FI["inflow_sol"]] == 0 and s[FI["growth"]] > 1.05 for s in snaps):
                    n_bad += 1
                    continue
                s600 = next((s for s in snaps if s[0] == 600), None)
                if s600 is None:
                    continue
                n_600 += 1
                cs = [(ms.rec_bucket_start(c[0]), ms.rec_bucket_end(c[0]), c[1], c[2], c[3]) for c in r["c"]]
                res = []
                for A in AGES:
                    for tp, _ in EXITS:
                        x = ms.res_trade(cs, end, A, s600[1], tp, SL, T_MAX, cfg, SIZE)
                        res.append((x[0], x[1]) if x else (np.nan, np.nan))
                rows.append((t0, s600[FI["liq_sol"]], s600[FI["top10"]], s600[FI["holders"]], res))
    rows.sort(key=lambda x: x[0])
    return rows, n_all, n_bad, n_600


def desk_sim(trades):
    """trades: (waktu masuk, hasil x, waktu keluar). Desk artikel: $12, stop hari itu kalau rugi $10."""
    bal, busy, n, w, day_pnl = START, -1.0, 0, 0, {}
    for t_in, m, t_out in sorted(trades):
        day = time.strftime("%Y%m%d", time.gmtime(t_in))
        if t_in < busy or day_pnl.get(day, 0.0) <= -DAY_HALT or bal < STAKE:
            continue
        pnl = STAKE * (m - 1)
        bal += pnl
        day_pnl[day] = day_pnl.get(day, 0.0) + pnl
        busy, n, w = t_out, n + 1, w + (m > 1)
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
    probe_robinhood()

    print("\n== BAGIAN 2: ATURAN YANG SAMA DI KOIN PUMP.FUN KITA")
    t = time.time()
    rows, n_all, n_bad, n_600 = load(a.data)
    if len(rows) < 100:
        print(f"   Data terlalu sedikit ({len(rows)} koin yang masih hidup di umur 10 menit).")
        return
    T0 = np.array([r[0] for r in rows])
    LIQ = np.array([r[1] for r in rows])
    TOP = np.array([r[2] for r in rows]) * 100   # fraksi -> persen
    t_cut = float(np.quantile(T0, 0.7))
    days = (T0[-1] - T0[0]) / 86400
    print(f"   {n_all:,} koin terekam ({time.strftime('%d/%m', time.gmtime(T0[0]))}-"
          f"{time.strftime('%d/%m', time.gmtime(T0[-1]))}), {n_bad:,} dibuang (kurva tidak standar), "
          f"{n_600:,} masih aktif di umur 10 menit. Baca {time.time() - t:.0f} dtk.")
    print(f"   Data lama (pilih): s/d {time.strftime('%d/%m %H:%M', time.gmtime(t_cut))} UTC, data baru (uji): sesudahnya.")

    def trades(ai, ei, dep, top, new):
        k = ai * len(EXITS) + ei
        sel = (LIQ >= dep) & (TOP <= top) & ((T0 >= t_cut) if new else (T0 < t_cut))
        out = []
        for i in np.nonzero(sel)[0]:
            m, h = rows[i][4][k]
            if not np.isnan(m):
                out.append((T0[i] + AGES[ai], m, T0[i] + h))
        return out

    print("\n   Berapa koin lolos filter per hari (artikel: kalau puluhan per hari, filter terlalu longgar):")
    for dep in DEPTH:
        print("     isi >= %2d SOL: " % dep + ", ".join(
            f"top10<={tp if tp <= 100 else 'bebas'}: {((LIQ >= dep) & (TOP <= tp)).sum() / days:,.0f}" for tp in TOP10))

    grid = []
    for ai in range(len(AGES)):
        for ei in range(len(EXITS)):
            for dep in DEPTH:
                for tp in TOP10:
                    old = trades(ai, ei, dep, tp, False)
                    if len(old) >= 30:
                        grid.append((float(np.mean([x[1] for x in old])), len(old), ai, ei, dep, tp))
    print(f"\n   {len(AGES) * len(EXITS) * len(DEPTH) * len(TOP10)} kombinasi, {len(grid)} punya >=30 trade di data lama; "
          f"{sum(g[0] > 1 for g in grid)} untung di data lama.")
    lab = lambda ai, ei, dep, tp: (f"masuk {AGES[ai] // 60} mnt, isi {'>=' + str(dep) + ' SOL' if dep >= 0 else 'bebas'}, top10 "
                                   f"{'<=' + str(tp) + '%' if tp <= 100 else 'bebas'}, SL 25% {EXITS[ei][1]}")

    def show(title, ai, ei, dep, tp, m_old=None):
        new = trades(ai, ei, dep, tp, True)
        st = stat([x[1] for x in new])
        bal, n, w = desk_sim(new)
        lo, hi = ms.wilson(w, n) if n else (0, 0)
        print(f"\n   {title}: {lab(ai, ei, dep, tp)}")
        if m_old is not None:
            print(f"     data lama {m_old:.3f}x")
        print(f"     DATA BARU: {fmt(st)} -> {'TERBUKTI' if st[0] >= 30 and st[2] > 1 else 'TIDAK terbukti'}")
        print(f"     SIMULASI $200 (Desk artikel): {n} trade, menang {w}"
              f"{f' ({w / n:.0%}, CI {lo:.0%}-{hi:.0%})' if n else ''}, akhir ${bal:.2f} ({bal - START:+.2f})"
              + ("  <30 trade, belum bisa disimpulkan" if n < 30 else ""))

    show("ATURAN ARTIKEL (paling mirip)", AGES.index(900), 0, 70, 35)
    show("ATURAN ARTIKEL, isi pool dilonggarkan", AGES.index(900), 0, 20, 35)
    for rank, (m_old, n_old, ai, ei, dep, tp) in enumerate(sorted(grid, reverse=True)[:3], 1):
        show(f"TERBAIK #{rank} di data lama", ai, ei, dep, tp, m_old)
    for ai in range(len(AGES)):
        show("PEMBANDING beli semua koin yang masih hidup", ai, 0, -1, 101)
    print("\n   Rekaman berhenti di umur 30 menit, jadi 'tahan' keluar paling lambat di menit 30.")
    print("   Data rekaman mulai 14 Okt 2026, jadi Jan 2026 - sekarang tidak bisa disimulasikan.")


if __name__ == "__main__":
    main()

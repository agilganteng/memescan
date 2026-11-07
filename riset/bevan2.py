"""Uji "database wallet ala Bevan" + copy wallet dev/sniper/awal + jaringan teman + wallet pucuk (7 Nov 2026).

Aturan ditulis di sini SEBELUM melihat hasil.

DATA: rekaman memescan (pump.fun, kurva standar, trade pertama < 1 dtk setelah lahir). Semua trade beli/jual di 5 menit
pertama tiap koin (maks 150, wallet 10 huruf pertama), harga direkonstruksi per trade (mesin riset/kol.py).
PEMBAGIAN WAKTU: A = 50% koin paling lama (bangun database wallet), B = 20% berikutnya (pilih aturan),
C = 30% paling baru (uji SEKALI). Untuk uji C, database dibangun ulang dari A+B (seperti kalau dipakai sungguhan).

NILAI TIAP WALLET (di jendela pembangun): untuk tiap koin yang dia beli (beli pertama umur <= 290 dtk):
  copy_ikut : hasil kalau KITA beli 1 dtk setelah dia, jual 1 dtk setelah dia jual pertama (kalau tidak terlihat jual
              di 5 menit, jual di akhir rekaman 30 mnt). Ukuran 0,1 SOL, fee 1,25%/sisi, priority 0,0005 SOL x2, dampak kurva.
  copy_60   : sama, tapi jual 60 dtk setelah masuk.
  pnl_sendiri: SOL jual - SOL beli dia sendiri di 5 menit (yang belum dijual dihitung 0 = rugi; peringatan Bevan
              soal winrate palsu karena koin belum dijual).
  peran     : dev (pembuat koin) / sniper (beli < 1 dtk setelah trade pertama) / awal (1-10 dtk) / telat (> 10 dtk);
              peran wallet = yang paling sering.
  hold      : median jeda beli pertama -> jual pertama.

W1 DATABASE WALLET (kriteria Bevan: PnL bukan 30 hari tapi panjang, hold cocok, winrate jujur; hindari KOL publik):
  peran {semua, dev, sniper, awal, telat} x koin minimal {5, 15} x
  ukuran {copy_ikut > 1,0 / > 1,2, copy_60 > 1,0 / > 1,2, gaya Bevan (pnl_sendiri > 0 & menang >= 60%),
          konsisten (copy_ikut > 1,0 / > 1,2 di paruh-1 DAN paruh-2 jendela, masing-masing >= 3 koin)} x
  hold median {bebas, >= 30 dtk}. Wallet KOL kolscan selalu dibuang. = 140 database.
  Sinyal: k = 1/2/3 wallet database sudah beli koin itu (konfirmasi berlapis), masuk 1 dtk setelah wallet ke-k.
  "Persen saldo" (konviksi): varian hanya hitung beli yang >= 1,5x median ukuran beli wallet itu.
  Jual: E1 ikut jual (keluar 1 dtk setelah wallet pemicu pertama mulai jual, maks 30 mnt) | E2 TP 2x SL 30% |
        E3 tahan 5 mnt | E4 tahan sampai akhir rekaman | E5 NYENDAL: setengah di sinyal, setengah lagi kalau harga
        >= +20% dalam 120 dtk sebelum ada wallet pemicu jual; keluar seperti E1 (yang tidak ditambah = kas).
  140 x 3 x 2 x 5 = 4.200 strategi.
W2 JARINGAN TEMAN ("friend network"): pasangan wallet yang beli koin sama dalam selisih <= 2 dtk (umur <= 60 dtk),
  minimal m = 3/5 kali, dan lift (bersama / koin wallet yang lebih jarang) >= 0,3/0,6 -> gabung jadi tim (2..30 wallet).
  Tim dinilai di jendela: copy saat anggota ke-2 beli (+1 dtk), jual saat anggota pemicu pertama jual; syarat
  rata > {tanpa syarat, 1,0, 1,2} dan >= 5 kemunculan. Sinyal: >= 2 anggota tim lolos beli. Jual E1..E5. = 60 strategi.
W3 DEV TAMBAH POSISI ("tim masih hold / masih beli"): dev beli LAGI di umur >= 10 dtk, ukuran >= 0,3/1/2 SOL,
  varian dev belum pernah jual. Masuk +1 dtk. Jual E1 (ikut dev jual) .. E5. = 30 strategi.
W4 WALLET PUCUK (beli = tanda jual): wallet dengan copy_ikut < 0,7 dan >= 15 koin di jendela. Pembanding: beli semua
  koin di umur 60 dtk, tahan 5 mnt: koin yang SUDAH dibeli wallet pucuk vs yang belum.

PILIH: di B, minimal 30 trade, urut rata-rata hasil per trade. 10 terbaik diuji SEKALI di C.
KONTROL ACAK: strategi terbaik diulang di C dengan wallet acak sejumlah sama dari kolam yang sama (20 kali).
MODAL: $100/$200/$1000, 2%/trade (maks 20 posisi) dan 10%/trade (maks 5); biaya ringan (di atas) dan realistis
(+ slippage 2%/sisi). Jeda 0,4/1/3 dtk untuk finalis.
BATAS: rekaman mulai Okt 2026, tiap koin 30 menit pertama di kurva, wallet cuma 5 menit pertama;
  Jan 2026 - sekarang TIDAK bisa disimulasikan. Sumber dana wallet (cara Bevan mengenali tim) tidak ada di data.

Pakai: python3 riset/bevan2.py --data data
"""
import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bevan  # noqa: E402
import kol  # noqa: E402
import memescan as ms  # noqa: E402

FEE, PRIO, SIZE = 0.0125, 0.0005, 0.1
LAT = 1.0
MAXAGE = 290.0
CAPS = (100.0, 200.0, 1000.0)
EXN = ("E1 ikut jual", "E2 TP2x SL30%", "E3 tahan 5mnt", "E4 tahan 30mnt", "E5 nyendal")
ROLES = ("semua", "dev", "sniper", "awal", "telat")
METRICS = (("copy_ikut", 1.0), ("copy_ikut", 1.2), ("copy_60", 1.0), ("copy_60", 1.2), ("gaya_bevan", 0.0),
           ("konsisten", 1.0), ("konsisten", 1.2))


class Coin2:
    """Pengganti bevan.Coin (yang pakai __slots__) supaya bisa menambah array harga."""


bevan.Coin = Coin2
SIGCAP = 4000     # maks sinyal per strategi saat menyaring ribuan strategi (sampel merata); finalis pakai semua


# ---------------------------------------------------------------- harga
def prep(c):
    p = kol.Path(c, 0)
    c.T = np.array([t for t, _ in p.tt], dtype=np.float64)
    c.P = np.array(p.tp, dtype=np.float64)
    c.anc = p.anchor
    cand = p.cand
    c.AT = np.concatenate([c.T, np.array([x[1] for x in cand], dtype=np.float64)])
    c.AH = np.concatenate([c.P, np.array([x[2] for x in cand], dtype=np.float64)])
    c.AL = np.concatenate([c.P, np.array([x[3] for x in cand], dtype=np.float64)])
    c.NT = len(c.T)
    c.CSs = np.array([x[0] for x in c.cs], dtype=np.float64)
    c.CSc = np.array([x[4] for x in c.cs], dtype=np.float64)
    # beli pertama & jual pertama tiap wallet
    fb, fs, buys, sells = {}, {}, defaultdict(float), defaultdict(float)
    for ag, w, b, s in c.w:
        if b:
            buys[w] += s
            if w not in fb:
                fb[w] = (ag, s)
        else:
            sells[w] += s
            if w in fb and w not in fs:
                fs[w] = ag
    c.fb, c.fs, c.buys, c.sells = fb, fs, buys, sells
    c.a0 = c.w[0][0]
    c.devre = [(ag, s) for ag, w, b, s in c.w if b and w == c.dev and ag >= 10.0]
    c.devsell = min([ag for ag, w, b, s in c.w if not b and w == c.dev] + [math.inf])
    del c.snaps, c.path


def price_at(c, t):
    if t <= c.cov:
        k = np.searchsorted(c.T, t, "right") - 1
        return float(c.P[k]) if k >= 0 else c.anc
    k = np.searchsorted(c.CSs, t, "right") - 1
    return float(c.CSc[k]) if k >= 0 else c.m0


def first_idx(mask):
    return int(np.argmax(mask)) if mask.any() else None


def exit_px(c, te, p_in, lx, tp=math.inf, sl=-1.0, tlim=math.inf, fol=None):
    """Sama dengan kol.sim: urutan cek per titik = batas waktu, ikut jual, SL, TP."""
    s = int(np.searchsorted(c.AT, te, "right"))
    AT, AH, AL = c.AT[s:], c.AH[s:], c.AL[s:]
    cands = []
    if tlim < math.inf:
        i = first_idx(AT >= tlim)
        if i is not None:
            cands.append((i, 0))
    if fol is not None:
        i = first_idx(AT >= fol)
        if i is not None:
            cands.append((i, 1))
    if sl > 0:
        i = first_idx(AL <= sl)
        if i is not None:
            cands.append((i, 2))
    if tp < math.inf:
        i = first_idx(AH >= tp)
        if i is not None:
            cands.append((i, 3))
    if cands:
        i, kind = min(cands)
        t = float(AT[i])
        if kind == 0:
            return price_at(c, tlim + lx), tlim + lx
        if kind == 1:
            return price_at(c, fol + lx), fol + lx
        if kind == 2:
            return min(sl, price_at(c, t + lx)), t + lx
        tick = (s + i) < c.NT
        return (price_at(c, t + lx) if tick else tp), t + lx
    if fol is not None and fol < c.end:
        return price_at(c, fol + lx), fol + lx
    return price_at(c, c.end), c.end


def mult(p_in, p_out, size=SIZE):
    e = p_in * (1 + size / ms.v_sol_at(p_in)) / (1 - FEE)
    s = p_out * (1 - FEE) / (1 + size / ms.v_sol_at(max(p_out, 1e-9)))
    return s / e - 2 * PRIO / size


def run_exits(c, a_sig, lat, fol, exits=range(5)):
    """Return dict exit -> (x, t_out_abs) untuk sinyal di umur a_sig."""
    te = a_sig + lat
    if te >= c.end:
        return None
    p_in = price_at(c, te)
    if p_in <= 0:
        return None
    lx = max(lat, 0.4)
    out = {}
    for e in exits:
        if e == 0 or e == 4:
            p1, t1 = exit_px(c, te, p_in, lx, tlim=te + 1800, fol=fol)
            if e == 0:
                out[0] = (mult(p_in, p1), c.t0 + t1)
                continue
            # nyendal: kaki 2 kalau harga >= +20% dalam 120 dtk dan sebelum wallet pemicu jual
            s = int(np.searchsorted(c.AT, te, "right"))
            lim = min(te + 120, fol if fol is not None else math.inf)
            AT, AH = c.AT[s:], c.AH[s:]
            m = (AT <= lim) & (AH >= p_in * 1.2)
            i = first_idx(m)
            x1 = mult(p_in, p1, SIZE / 2)
            if i is None:
                out[4] = (0.5 * x1 + 0.5, c.t0 + t1)
            else:
                t2 = float(AT[i]) + lx
                p2 = price_at(c, t2)
                p2o, t2o = exit_px(c, t2, p2, lx, tlim=te + 1800, fol=fol)
                out[4] = (0.5 * x1 + 0.5 * mult(p2, p2o, SIZE / 2), c.t0 + max(t1, t2o))
        elif e == 1:
            p1, t1 = exit_px(c, te, p_in, lx, tp=p_in * 2, sl=p_in * 0.7, tlim=te + 1800)
            out[1] = (mult(p_in, p1), c.t0 + t1)
        elif e == 2:
            p1, t1 = exit_px(c, te, p_in, lx, tlim=te + 300)
            out[2] = (mult(p_in, p1), c.t0 + t1)
        elif e == 3:
            p1, t1 = exit_px(c, te, p_in, lx)
            out[3] = (mult(p_in, p1), c.t0 + t1)
    return out


# ---------------------------------------------------------------- wallet stats
class WS:
    """Statistik wallet di satu jendela koin."""

    def __init__(self, coins, wid, kolset):
        n = len(wid)
        self.n = np.zeros(n, int)
        sx, sx60, own, ownw = np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)
        h1s, h1n, h2s, h2n = np.zeros(n), np.zeros(n, int), np.zeros(n), np.zeros(n, int)
        holds, bsz = defaultdict(list), defaultdict(list)
        rc = np.zeros((n, 4), int)
        mid_t = coins[len(coins) // 2].t0 if coins else 0
        self.copy_x = defaultdict(list)    # untuk W2/W4
        for c in coins:
            for w, (ab, sb) in c.fb.items():
                if ab > MAXAGE:
                    continue
                te = ab + LAT
                if te >= c.end:
                    continue
                i = wid[w]
                p_in = price_at(c, te)
                f = c.fs.get(w)
                p_o = price_at(c, f + LAT) if f is not None else price_at(c, c.end)
                x = mult(p_in, p_o)
                x60 = mult(p_in, price_at(c, te + 60))
                self.n[i] += 1
                sx[i] += x
                sx60[i] += x60
                pnl = c.sells.get(w, 0.0) - c.buys[w]
                own[i] += pnl
                ownw[i] += pnl > 0
                if c.t0 < mid_t:
                    h1s[i] += x
                    h1n[i] += 1
                else:
                    h2s[i] += x
                    h2n[i] += 1
                holds[i].append((f - ab) if f is not None else 1e6)
                bsz[i].append(sb)
                rc[i, 0 if w == c.dev else 1 if ab - c.a0 < 1.0 else 2 if ab - c.a0 <= 10 else 3] += 1
        nn = np.maximum(self.n, 1)
        self.cx, self.cx60, self.own, self.wr = sx / nn, sx60 / nn, own, ownw / nn
        self.h1 = np.where(h1n >= 3, h1s / np.maximum(h1n, 1), 0.0)
        self.h2 = np.where(h2n >= 3, h2s / np.maximum(h2n, 1), 0.0)
        self.hold = np.zeros(n)
        self.med = np.full(n, np.inf)
        for i, v in holds.items():
            self.hold[i] = float(np.median(v))
            self.med[i] = float(np.median(bsz[i]))
        self.role = rc.argmax(1) + 1          # 1 dev 2 sniper 3 awal 4 telat (0 = semua)
        self.kol = np.zeros(n, bool)
        for w, i in wid.items():
            if w in kolset:
                self.kol[i] = True

    def select(self, role, nmin, metric, thr, hold30):
        m = (self.n >= nmin) & ~self.kol
        if role:
            m &= self.role == role
        if hold30:
            m &= self.hold >= 30
        if metric == "copy_ikut":
            m &= self.cx > thr
        elif metric == "copy_60":
            m &= self.cx60 > thr
        elif metric == "gaya_bevan":
            m &= (self.own > 0) & (self.wr >= 0.6)
        elif metric == "konsisten":
            m &= (self.h1 > thr) & (self.h2 > thr)
        elif metric == "pool":
            pass
        return m


def events(coins, wid):
    """Semua beli pertama (umur <= MAXAGE) urut koin lalu umur: (idx koin lokal, umur, wid, sol)."""
    ci, ag, wi, so = [], [], [], []
    for k, c in enumerate(coins):
        for w, (ab, sb) in sorted(c.fb.items(), key=lambda kv: kv[1][0]):
            if ab <= MAXAGE:
                ci.append(k)
                ag.append(ab)
                wi.append(wid[w])
                so.append(sb)
    return np.array(ci), np.array(ag), np.array(wi), np.array(so)


def signals(ev, sel_mask, med, k, conv):
    ci, ag, wi, so = ev
    m = sel_mask[wi]
    if conv:
        m &= so >= 1.5 * med[wi]
    idx = np.where(m)[0]
    if not len(idx):
        return []
    c2 = ci[idx]
    u, st, cnt = np.unique(c2, return_index=True, return_counts=True)
    out = []
    for cc, s, n in zip(u, st, cnt):
        if n >= k:
            trig = idx[s:s + k]
            out.append((int(cc), float(ag[trig[-1]]), [int(wi[j]) for j in trig]))
    return out


def eval_sigs(coins, sigs, inv, lat=LAT, cap=None):
    """Return list per exit: [(t_in_abs, x, t_out_abs)]."""
    res = [[] for _ in EXN]
    if cap and len(sigs) > cap:
        step = len(sigs) / cap
        sigs = [sigs[int(i * step)] for i in range(cap)]
    for cc, a, trig in sigs:
        c = coins[cc]
        fol = min([c.fs.get(inv[w], math.inf) for w in trig if c.fs.get(inv[w], math.inf) > c.fb[inv[w]][0]]
                  + [math.inf])
        fol = None if fol == math.inf else fol
        r = run_exits(c, a, lat, fol)
        if r is None:
            continue
        for e, (x, tx) in r.items():
            res[e].append((c.t0 + a + lat, x, tx))
    return res


def mean_x(tr):
    return float(np.mean([x for _, x, _ in tr])) if tr else float("nan")


def sim_frac(tr, cap, frac, max_pos, extra=1.0):
    eq, open_ = cap, []
    n = 0
    for t, x, tx in sorted(tr):
        still = []
        for te, st, xx in open_:
            if te <= t:
                eq += st * xx
            else:
                still.append((te, st, xx))
        open_ = still
        tot = eq + sum(s for _, s, _ in open_)
        if len(open_) >= max_pos or tot <= 1.0:
            continue
        st = min(eq, tot * frac)
        if st <= 0.05:
            continue
        eq -= st
        open_.append((tx, st, max(0.0, x * extra)))
        n += 1
    return eq + sum(s * xx for _, s, xx in open_), n


def line(label, tr):
    xs = np.array([x for _, x, _ in tr])
    if not len(xs):
        return f"   {label}: 0 trade"
    k = int((xs > 1).sum())
    lo, hi = ms.wilson(k, len(xs))
    wo = (xs.sum() - xs.max()) / max(1, len(xs) - 1)
    s = (f"   {label}: n={len(xs)}{' (<30!)' if len(xs) < 30 else ''} rata {xs.mean():.3f}x median {np.median(xs):.3f}x "
         f"menang {k / len(xs):.0%} [{lo:.0%}-{hi:.0%}] tanpa-terbaik {wo:.3f}x")
    for frac, mp, nm in ((0.02, 20, "2%"), (0.10, 5, "10%")):
        parts = []
        for cap in CAPS:
            e1, _ = sim_frac(tr, cap, frac, mp)
            e2, _ = sim_frac(tr, cap, frac, mp, extra=0.98 * 0.98)
            parts.append(f"${cap:.0f}->${e1:,.0f}/${e2:,.0f}")
        s += f"\n      modal {nm}/trade (ringan/realistis): " + "  ".join(parts)
    return s


# ---------------------------------------------------------------- W2 tim
def build_teams(coins, wid, ws, m_min, lift):
    many = ws.n >= 5
    cnt = defaultdict(int)
    for c in coins:
        ev = sorted((ab, wid[w]) for w, (ab, sb) in c.fb.items() if ab <= 60 and many[wid[w]] and w != c.dev)
        for i in range(len(ev)):
            for j in range(i + 1, len(ev)):
                if ev[j][0] - ev[i][0] > 2.0:
                    break
                a, b = ev[i][1], ev[j][1]
                cnt[(a, b) if a < b else (b, a)] += 1
    par = {}

    def find(x):
        while par.get(x, x) != x:
            par[x] = par.get(par[x], par[x])
            x = par[x]
        return x
    for (a, b), n in cnt.items():
        if n >= m_min and n / min(ws.n[a], ws.n[b]) >= lift:
            ra, rb = find(a), find(b)
            if ra != rb:
                par[ra] = rb
    comp = defaultdict(list)
    for x in list(par):
        comp[find(x)].append(x)
    team = {}
    for r, mem in comp.items():
        if 2 <= len(mem) <= 30:
            for x in mem:
                team[x] = r
    return team


def team_sigs(coins, wid, team, ok=None):
    out = []
    for k, c in enumerate(coins):
        seen = {}
        for w, (ab, sb) in sorted(c.fb.items(), key=lambda kv: kv[1][0]):
            if ab > MAXAGE:
                break
            t = team.get(wid[w])
            if t is None or (ok is not None and t not in ok):
                continue
            seen.setdefault(t, []).append(wid[w])
            if len(seen[t]) == 2:
                out.append((k, ab, list(seen[t]), t))
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    t_start = time.time()
    coins, n_all = bevan.load(a.data)
    print(f"   dimuat {len(coins):,} koin", flush=True)
    coins = [c for c in coins if c.std and c.w and c.w[0][0] < 1.0]
    for c in coins:
        prep(c)
    N = len(coins)
    iA, iB = int(N * 0.5), int(N * 0.7)
    A, B, C, AB = coins[:iA], coins[iA:iB], coins[iB:], coins[:iB]
    ts = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))  # noqa: E731
    print(f"== {N:,} koin pump.fun kurva standar ({ts(coins[0].t0)} - {ts(coins[-1].t0)} UTC). "
          f"A < {ts(B[0].t0)} <= B < {ts(C[0].t0)} <= C. Siap {time.time() - t_start:.0f} dtk.")
    print("   BATAS: rekaman mulai Okt 2026; Jan 2026 - sekarang tidak bisa disimulasikan. Wallet = 10 huruf pertama.")
    wid = {}
    for c in coins:
        for w in c.fb:
            if w not in wid:
                wid[w] = len(wid)
    inv = {i: w for w, i in wid.items()}
    kolset = set()
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "kol_wallets.txt")) as f:
        for ln in f:
            if ln.strip() and not ln.startswith("#"):
                kolset.add(ln.split()[0][:10])
    wsA = WS(A, wid, kolset)
    wsAB = WS(AB, wid, kolset)
    evB, evC = events(B, wid), events(C, wid)
    print(f"   {len(wid):,} wallet; dengan >= 5 koin di A: {(wsA.n >= 5).sum():,}, >= 15: {(wsA.n >= 15).sum():,}. "
          f"Statistik selesai {time.time() - t_start:.0f} dtk.")

    # pembanding: beli SEMUA beli-pertama (siapa pun) -> tidak masuk akal, pakai beli semua koin di umur 60 dtk
    base = {"B": [], "C": []}
    for nm, cs in (("B", B), ("C", C)):
        for c in cs:
            r = run_exits(c, 60.0, 0.0, None, exits=(2,))
            if r:
                base[nm].append((c.t0 + 60, r[2][0], r[2][1]))
    print(line("PEMBANDING beli semua koin umur 60 dtk, tahan 5 mnt [B]", base["B"]))
    print(line("PEMBANDING beli semua koin umur 60 dtk, tahan 5 mnt [C]", base["C"]))

    # ================= W1
    print("\n################ W1 DATABASE WALLET ala Bevan (dipilih dari hasil copy, bukan PnL mereka)")
    rows = []
    for ri, role in enumerate(ROLES):
        for nmin in (5, 15):
            for metric, thr in METRICS:
                for hold30 in (False, True):
                    selA = wsA.select(ri, nmin, metric, thr, hold30)
                    if selA.sum() == 0:
                        continue
                    for k in (1, 2, 3):
                        for conv in (False, True):
                            sg = signals(evB, selA, wsA.med, k, conv)
                            if len(sg) < 30:
                                continue
                            res = eval_sigs(B, sg, inv, cap=SIGCAP)
                            for e in range(5):
                                rows.append((mean_x(res[e]), len(res[e]), (ri, nmin, metric, thr, hold30, k, conv, e),
                                             int(selA.sum())))
    rows = [r for r in rows if r[1] >= 30]
    nB = sum(r[0] > 1 for r in rows)
    print(f"   {len(rows):,} strategi dengan >= 30 trade di B; untung di B: {nB}. Waktu {time.time() - t_start:.0f} dtk.")
    rows.sort(key=lambda r: -r[0])

    def desc(cfg):
        ri, nmin, metric, thr, hold30, k, conv, e = cfg
        return (f"{ROLES[ri]}, >={nmin} koin, {metric}{'>' + str(thr) if metric in ('copy_ikut', 'copy_60', 'konsisten') else ''}"
                f"{', hold>=30dtk' if hold30 else ''}, k={k}{', konviksi' if conv else ''}, {EXN[e]}")
    # semua strategi juga dinilai di C (database A+B) untuk hitung "untung di B DAN C"
    both, n_c, top_c = 0, 0, []
    cacheC = {}
    for xB, nb, cfg, nsel in rows:
        ri, nmin, metric, thr, hold30, k, conv, e = cfg
        key = cfg[:7]
        if key not in cacheC:
            sel = wsAB.select(ri, nmin, metric, thr, hold30)
            sg = signals(evC, sel, wsAB.med, k, conv)
            cacheC[key] = (eval_sigs(C, sg, inv, cap=SIGCAP), sel, sg)
        trC = cacheC[key][0][e]
        if len(trC) >= 30:
            n_c += 1
            xc = mean_x(trC)
            both += (xB > 1) and (xc > 1)
            top_c.append((xc, len(trC), cfg))
    print(f"   Dinilai juga di C (database dibangun ulang A+B): {n_c:,} strategi >= 30 trade; untung di B DAN C: {both}.")
    print("   10 terbaik di B, diuji SEKALI di C:")
    for xB, nb, cfg, nsel in rows[:10]:
        trC = eval_sigs(C, cacheC[cfg[:7]][2], inv)[cfg[7]]      # semua sinyal, tanpa sampel
        print(f"  * [{desc(cfg)}] database A {nsel} wallet | B {xB:.3f}x n={nb}")
        print(line("C", trC))
    top_c.sort(key=lambda r: -r[0])
    print("   (info, BUKAN pilihan) 5 terbaik kalau dilihat langsung di C - bias seleksi:")
    for xc, n, cfg in top_c[:5]:
        print(f"     {xc:.3f}x n={n} [{desc(cfg)}]")

    best = rows[0][2] if rows else None
    if best:
        ri, nmin, metric, thr, hold30, k, conv, e = best
        print(f"\n   Finalis #1 [{desc(best)}] di C dengan jeda berbeda:")
        sel = cacheC[best[:7]][1]
        sg = signals(evC, sel, wsAB.med, k, conv)
        for L in (0.4, 1.0, 3.0):
            print(line(f"jeda {L} dtk", eval_sigs(C, sg, inv, lat=L)[e]))
        pool = np.where(wsAB.select(ri, nmin, "pool", 0, hold30))[0]
        nsel = int(sel.sum())
        rng = np.random.default_rng(7)
        xs = []
        for _ in range(20):
            if len(pool) < nsel or nsel == 0:
                break
            m = np.zeros(len(wid), bool)
            m[rng.choice(pool, nsel, replace=False)] = True
            tr = eval_sigs(C, signals(evC, m, wsAB.med, k, conv), inv, cap=SIGCAP)[e]
            if len(tr) >= 10:
                xs.append(mean_x(tr))
        if xs:
            print(f"   KONTROL ACAK ({nsel} wallet acak dari kolam {len(pool):,}, 20x) di C: rata {np.mean(xs):.3f}x "
                  f"[min {min(xs):.3f} maks {max(xs):.3f}] vs pilihan {mean_x(cacheC[best[:7]][0][e]):.3f}x")

    # wallet satu per satu: yang terpilih (copy_ikut>1,2, >=15 koin di A+B) dan hasil copy-nya di C
    print("\n   WALLET SATU-SATU: dipilih dari A+B (>= 15 koin, copy_ikut > 1,2, bukan KOL), hasil copy di C (jeda 1 dtk):")
    sel = wsAB.select(0, 15, "copy_ikut", 1.2, False)
    wsC = WS(C, wid, kolset)
    idx = [i for i in np.where(sel)[0] if wsC.n[i] >= 10]
    idx.sort(key=lambda i: -wsC.n[i])
    good = 0
    for i in idx:
        lo = None
        good += wsC.cx[i] > 1
    print(f"   {int(sel.sum())} wallet terpilih; {len(idx)} masih aktif >= 10 koin di C; copy untung di C: {good}")
    for i in idx[:25]:
        print(f"     {inv[i]}.. peran {ROLES[wsAB.role[i]]:6s} A+B: {wsAB.n[i]} koin copy {wsAB.cx[i]:.2f}x hold "
              f"{wsAB.hold[i]:.0f}dtk | C: {wsC.n[i]} koin copy {wsC.cx[i]:.3f}x copy60 {wsC.cx60[i]:.3f}x")
    keep = [inv[i] for i in idx if wsC.n[i] >= 30 and wsC.cx[i] > 1.0 and wsC.cx60[i] > 1.0]
    print(f"   Wallet yang TETAP untung di C dengan >= 30 koin (kandidat simpan GMGN): {keep if keep else 'tidak ada'}")

    # ================= W2
    print("\n################ W2 JARINGAN TEMAN (tim = wallet yang sering beli bareng dalam 2 dtk)")
    rows2 = []
    for m_min in (3, 5):
        for lift in (0.3, 0.6):
            tmA = build_teams(A, wid, wsA, m_min, lift)
            tmAB = build_teams(AB, wid, wsAB, m_min, lift)
            # nilai tim di jendela pembangun
            for thr in (None, 1.0, 1.2):
                def ok_teams(cs, tm):
                    if thr is None:
                        return None
                    sg = team_sigs(cs, wid, tm)
                    per = defaultdict(list)
                    for k_, ag, trig, t in sg:
                        r = eval_sigs(cs, [(k_, ag, trig)], inv)[0]
                        if r:
                            per[t].append(r[0][1])
                    return {t for t, v in per.items() if len(v) >= 5 and np.mean(v) > thr}
                okA, okAB = ok_teams(A, tmA), ok_teams(AB, tmAB)
                sgB = [(k_, ag, trig) for k_, ag, trig, t in team_sigs(B, wid, tmA, okA)]
                sgC = [(k_, ag, trig) for k_, ag, trig, t in team_sigs(C, wid, tmAB, okAB)]
                rB, rC = eval_sigs(B, sgB, inv), eval_sigs(C, sgC, inv)
                ntA = len(set(tmA.values())) if okA is None else len(okA)
                for e in range(5):
                    rows2.append((mean_x(rB[e]) if len(rB[e]) >= 30 else -1, (m_min, lift, thr, e), rB[e], rC[e], ntA))
    rows2.sort(key=lambda r: -r[0])
    print(f"   untung di B (>=30 trade): {sum(r[0] > 1 for r in rows2)} dari {sum(r[0] >= 0 for r in rows2)}; "
          f"untung di B DAN C: {sum(r[0] > 1 and len(r[3]) >= 30 and mean_x(r[3]) > 1 for r in rows2)}")
    for xb, cfg, rb, rc, nt in rows2[:5]:
        print(f"  * [m>={cfg[0]} lift>={cfg[1]} syarat tim {cfg[2]} {EXN[cfg[3]]}] {nt} tim di A | B {xb:.3f}x n={len(rb)}")
        print(line("C", rc))

    # ================= W3
    print("\n################ W3 DEV TAMBAH POSISI (dev beli lagi di umur >= 10 dtk)")
    rows3 = []
    for smin in (0.3, 1.0, 2.0):
        for nosell in (False, True):
            def sg_dev(cs):
                out = []
                for k_, c in enumerate(cs):
                    for ag, s in c.devre:
                        if s >= smin and ag <= MAXAGE and (not nosell or c.devsell > ag):
                            out.append((k_, ag, [wid[c.dev]] if c.dev in wid else []))
                            break
                return out
            def ev_dev(cs, sg):
                res = [[] for _ in EXN]
                for k_, ag, _ in sg:
                    c = cs[k_]
                    fol = c.devsell if c.devsell > ag and c.devsell < math.inf else None
                    r = run_exits(c, ag, LAT, fol)
                    if r:
                        for e, (x, tx) in r.items():
                            res[e].append((c.t0 + ag + LAT, x, tx))
                return res
            rB, rC = ev_dev(B, sg_dev(B)), ev_dev(C, sg_dev(C))
            for e in range(5):
                rows3.append((mean_x(rB[e]) if len(rB[e]) >= 30 else -1, (smin, nosell, e), rB[e], rC[e]))
    rows3.sort(key=lambda r: -r[0])
    print(f"   untung di B: {sum(r[0] > 1 for r in rows3)} dari {sum(r[0] >= 0 for r in rows3)}; untung di B DAN C: "
          f"{sum(r[0] > 1 and len(r[3]) >= 30 and mean_x(r[3]) > 1 for r in rows3)}")
    for xb, cfg, rb, rc in rows3[:3]:
        print(f"  * [dev tambah >= {cfg[0]} SOL{', dev belum jual' if cfg[1] else ''}, {EXN[cfg[2]]}] B {xb:.3f}x n={len(rb)}")
        print(line("C", rc))

    # ================= W4
    print("\n################ W4 WALLET PUCUK (copy_ikut < 0,7, >= 15 koin) - beli semua umur 60 dtk tahan 5 mnt")
    for nm, ws, cs in (("B", wsA, B), ("C", wsAB, C)):
        pucuk = (ws.n >= 15) & (ws.cx < 0.7)
        ada, tidak = [], []
        for c in cs:
            r = run_exits(c, 60.0, 0.0, None, exits=(2,))
            if not r:
                continue
            hit = any(pucuk[wid[w]] for w, (ab, sb) in c.fb.items() if ab <= 60)
            (ada if hit else tidak).append((c.t0 + 60, r[2][0], r[2][1]))
        print(f"   [{nm}] {int(pucuk.sum())} wallet pucuk")
        print(line(f"[{nm}] koin SUDAH dibeli wallet pucuk", ada))
        print(line(f"[{nm}] koin TIDAK dibeli wallet pucuk", tidak))
    # ================= W5 SNIPER: berapa jeda yang masih untung
    print("\n################ W5 SNIPER semua koin baru (masuk setelah trade pertama = beli dev) - data C, 30k sampel")
    step = max(1, len(C) // 30000)
    for L in (0.0, 0.2, 0.4, 1.0, 3.0):
        for nm, kw in (("TP1.2x SL15% 30dtk", dict(tp=1.2, sl=0.85, T=30)), ("tahan 10 dtk", dict(T=10)),
                       ("TP1.5x SL30% 30dtk", dict(tp=1.5, sl=0.7, T=30))):
            tr = []
            for c in C[::step]:
                te = c.a0 + L
                if te >= c.end:
                    continue
                p_in = price_at(c, te)
                lx = max(L, 0.2)
                p_o, t_o = exit_px(c, te, p_in, lx, tp=p_in * kw.get("tp", math.inf),
                                   sl=p_in * kw["sl"] if "sl" in kw else -1.0, tlim=te + kw["T"])
                tr.append((c.t0 + te, mult(p_in, p_o), c.t0 + t_o))
            xs = np.array([x for _, x, _ in tr])
            print(f"   jeda {L} dtk, {nm}: n={len(xs)} rata {xs.mean():.3f}x median {np.median(xs):.3f}x "
                  f"menang {np.mean(xs > 1):.0%}")
    print("   Catatan: jeda 0 = harga tepat setelah beli dev, di blok yang sama. Itu hanya mungkin buat bundle dev sendiri "
          "atau bot dengan infrastruktur paling cepat, dan di sana pun berebut dengan bot lain.")
    print(f"\nSelesai {time.time() - t_start:.0f} dtk. Paper saja, tidak ada transaksi.")


if __name__ == "__main__":
    main()

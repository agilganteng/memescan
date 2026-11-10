"""GRID BESAR varian bot @zostaff (sniper dev-buy, graduation curve, copy-wallet) + momentum. 10 Nov 2026. PAPER.

PRAREGISTRASI (ditulis & di-hash SEBELUM melihat hasil):
DATA: rekaman memescan rec-*.jsonl (kurva bonding pump.fun; candle s/d 30 mnt, snapshot fitur 10..600 dtk,
  trade wallet 5 mnt pertama maks 150/koin). Kurva tidak standar dibuang (c.std, sama dengan zostaff.py; sedikit
  optimistis). Urut t0; split waktu A 50% / B 20% / C 30%.
BIAYA (realistis): fee 1,25%/sisi, slippage 2%/sisi, priority 0,0005 SOL x2, dampak kurva (ukuran 0,1 SOL).
  Jeda: 0,4 dtk / 1 dtk / acak 3-8 dtk (sama untuk masuk & keluar). Stop yang terpicu dari CANDLE (di luar cakupan
  tick) terisi di level stop x 0,72; stop dari tick terisi di harga nyata setelah jeda (min dengan level stop).
  TP dari tick = harga nyata setelah jeda; dari candle = level TP. Dalam candle: cek stop dulu baru TP.
KELUARGA:
  S1 SNIPER dev-buy: masuk setelah trade pertama + jeda. Dev buy (dev beli s/d trade pertama+0,2 dtk) band:
     semua, <0,5, 0,5-1, 1-2, 2-5, >=5, >=0,5 SOL (7).
  S1b MOMENTUM: keputusan di umur D {10,30,60,120,300} dari snapshot: mcap band {<35,35-60,60-120,>=120,semua} x
     pembeli unik {>=0,>=10,>=30} x top10 {<=25%,<=40%,semua} x growth {semua,>=1,3x,>=2x} x devbuy {semua,>=0,5} = 270.
  S2 GRADUATION: sinyal saat mcap pertama >= kurva {50,60,70,80,90,95,98}% x umur saat sinyal {semua,<5m,5-15m,>15m}.
     Rekaman berhenti saat lulus -> harga keluar terakhir = BATAS ATAS.
  S3 COPY-WALLET: statistik wallet KAUSAL (hanya koin yang rekamannya selesai sebelum sinyal):
     min koin {5,10,20} x winrate {50,65,80%} x median hold {semua,<=60 dtk,>60 dtk} x jendela {semua,6 jam terakhir},
     wajib total untung > 0 (54 aturan). 1 entry per koin (wallet lolos pertama).
  EXIT S1/S1b/S2: TP {1,2 1,5 2 3 5}x SL {0,5 0,7 0,8 0,9} x T {10,30,120,600,1800 dtk} (100) + trailing arm {+20,+50,+100%}
     x trail {15,30%} x T {300,1800}, SL 0,7 (12) = 112 (S2: TP {1,05 1,1 1,2 1,5 2 tanpa} x SL {0,7 0,8 0,9 tanpa} x T {30,120,600,1800}
     + 12 trailing = 108). S3: ikut jual (maks 30 mnt) {tanpa SL, SL 0,5, SL 0,7} + TP{1,2 1,5 2}xSL{0,7 0,9}xT{30,120,600} = 21.
PILIH: per kombinasi rata x per trade di A (n_A>=30). Top 5 per A -> lihat B -> yang B>1 diuji SEKALI di C.
LULUS: n_C>=30, mean A>1, B>1, C>1, C tanpa koin terbaik >1, DAN jumlah lulus > null.
NULL: 20x acak fitur/label antar koin (S1,S1b: baris fitur; S2: umur-band antar koin yang kena sinyal; S3: baris statistik
  wallet antar event), hitung jumlah lulus. Koreksi multiple testing: finalis di C wajib p < 0,05/k (bootstrap satu sisi).
SIM: $200, 8% dan 10% saldo/trade, maks 1 posisi (varian 5), urut waktu, hasil x dari 0,1 SOL.
"""
import argparse, bisect, json, math, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bevan, kol  # noqa
import memescan as ms  # noqa

FEE, SLIP, PRIO, SIZE, STOPFILL = 0.0125, 0.02, 0.0005, 0.1, 0.72
DELAYS = ("0.4", "1", "3-8")
FI = bevan.FI


def mult(p_in, p_out):
    e = p_in * (1 + SIZE / ms.v_sol_at(p_in)) / ((1 - FEE) * (1 - SLIP))
    s = p_out * (1 - FEE) * (1 - SLIP) / (1 + SIZE / ms.v_sol_at(max(p_out, 1e-9)))
    return max(0.0, s / e - 2 * PRIO / SIZE)


def mk_exits(tps, sls, Ts):
    ex = [dict(tp=tp, sl=sl, T=T) for tp in tps for sl in sls for T in Ts]
    ex += [dict(tp=math.inf, sl=0.7, T=T, arm=a, trail=tr) for a in (0.2, 0.5, 1.0) for tr in (0.15, 0.3) for T in (300, 1800)]
    return ex


EX1 = mk_exits((1.2, 1.5, 2, 3, 5), (0.5, 0.7, 0.8, 0.9), (10, 30, 120, 600, 1800))
EX2 = mk_exits((1.05, 1.1, 1.2, 1.5, 2, math.inf), (0.7, 0.8, 0.9, 0.0), (30, 120, 600, 1800))
EX3 = [dict(tp=math.inf, sl=s, T=1800, follow=True) for s in (0.0, 0.5, 0.7)] + \
      [dict(tp=tp, sl=sl, T=T) for tp in (1.2, 1.5, 2) for sl in (0.7, 0.9) for T in (30, 120, 600)]


def exname(e):
    if e.get("follow"):
        return f"ikut-jual SL{e['sl']}"
    if "trail" in e:
        return f"trail arm+{e['arm']:.0%} {e['trail']:.0%} SL{e['sl']} {e['T']}s"
    return f"TP{e['tp']} SL{e['sl']} {e['T']}s"


def pts_of(p, te):
    return list(p.points(te))


def run_exit(c, p, pts, te, p_in, e, lx, fol=None):
    """-> (p_out, umur keluar)"""
    sl = p_in * e["sl"] if e["sl"] > 0 else -1.0
    tp = p_in * e["tp"]
    tl = te + e["T"]
    peak, armed = p_in, False
    for t, cl, hi, lo in pts:
        if t >= tl:
            return p.price_at(tl + lx), tl + lx
        if fol is not None and t >= fol:
            return p.price_at(fol + lx), fol + lx
        stop = max(sl, peak * (1 - e["trail"])) if armed else sl
        tick = hi == lo
        if lo <= stop:
            return (min(stop, p.price_at(t + lx)) if tick else stop * STOPFILL), t + lx
        if hi >= tp:
            return (p.price_at(t + lx) if tick else tp), t + lx
        peak = max(peak, hi)
        if "trail" in e and peak >= p_in * (1 + e["arm"]):
            armed = True
    if fol is not None and fol < c.end:
        return p.price_at(fol + lx), fol + lx
    return p.price_at(c.end), c.end


def lag(L, rng):
    return {"0.4": 0.4, "1": 1.0}.get(L) or float(rng.uniform(3, 8))


def outcomes(c, p, te, L, exits, fol=None):
    """baris x dan t_keluar (abs) utk semua exit, atau None"""
    if te >= c.end - 1:
        return None
    p_in = p.price_at(te)
    if p_in <= 0:
        return None
    pts = pts_of(p, te)
    xs = np.empty(len(exits), np.float32)
    ts = np.empty(len(exits), np.float64)
    for k, e in enumerate(exits):
        po, tx = run_exit(c, p, pts, te, p_in, e, L, fol)
        xs[k] = mult(p_in, po)
        ts[k] = c.t0 + tx
    return xs, ts


def stats(X, mask_rows, period):
    """X: (n,E) outcome; mask_rows (F,n) bool; period (n,) 0/1/2 -> n[F,3], mean[F,3,E]"""
    out_n = np.zeros((mask_rows.shape[0], 3))
    out_m = np.full((mask_rows.shape[0], 3, X.shape[1]), np.nan)
    for s in range(3):
        sel = period == s
        M = mask_rows[:, sel].astype(np.float64)
        n = M.sum(1)
        S = M @ X[sel].astype(np.float64)
        out_n[:, s] = n
        with np.errstate(invalid="ignore", divide="ignore"):
            out_m[:, s, :] = S / n[:, None]
    return out_n, out_m


def nobest_mean(xs):
    if len(xs) < 2:
        return float("nan")
    return (xs.sum() - xs.max()) / (len(xs) - 1)


def count_pass(n, m, X, masks, period, nmin=30):
    """jumlah kombinasi lulus semua syarat (cek tanpa-koin-terbaik hanya utk kandidat)"""
    cand = (n[:, 2][:, None] >= nmin) & (m[:, 0] > 1) & (m[:, 1] > 1) & (m[:, 2] > 1)
    cnt = 0
    for f, k in zip(*np.where(cand)):
        xs = X[masks[f] & (period == 2), k]
        if nobest_mean(xs) > 1:
            cnt += 1
    return cnt, int(cand.sum()), int(((m[:, 0] > 1) & (m[:, 1] > 1) & (n[:, 0][:, None] >= nmin)).sum())


def sim200(trades, frac, maxpos, cap=200.0):
    eq, open_, n, k = cap, [], 0, 0
    for t, x, tx in sorted(trades):
        still = []
        for te_, st, xx in open_:
            if te_ <= t:
                eq += st * xx
            else:
                still.append((te_, st, xx))
        open_ = still
        tot = eq + sum(s for _, s, _ in open_)
        if len(open_) >= maxpos or tot < 1:
            continue
        st = min(eq, tot * frac)
        if st <= 0.05:
            continue
        eq -= st
        open_.append((tx, st, x))
        n += 1
        k += x > 1
    eq += sum(s * xx for _, s, xx in open_)
    return eq, n, k


def boot_p(xs, B=4000, seed=1):
    if len(xs) < 2:
        return float("nan")
    r = np.random.default_rng(seed)
    bs = r.choice(xs, (B, len(xs))).mean(1)
    return float((bs <= 1).mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="out")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--null", type=int, default=20)
    a = ap.parse_args()
    T0 = time.time()
    rng = np.random.default_rng(7)
    coins, n_all = bevan.load(a.data)
    coins = [c for c in coins if c.std and c.w and c.w[0][0] < 1.0]
    if a.sample and len(coins) > a.sample:
        idx = np.sort(rng.choice(len(coins), a.sample, replace=False))
        coins = [coins[i] for i in idx]
    for i, c in enumerate(coins):
        c.i = i
    N = len(coins)
    t0s = np.array([c.t0 for c in coins])
    cut1, cut2 = t0s[int(N * 0.5)], t0s[int(N * 0.7)]
    per_c = np.where(t0s < cut1, 0, np.where(t0s < cut2, 1, 2))
    R = dict(N=N, n_all=n_all, t_first=float(t0s[0]), t_last=float(t0s[-1]), cut1=float(cut1), cut2=float(cut2),
             nA=int((per_c == 0).sum()), nB=int((per_c == 1).sum()), nC=int((per_c == 2).sum()), fam={})
    print(f"{N} koin std (dari {n_all} rekaman), A/B/C = {R['nA']}/{R['nB']}/{R['nC']}", flush=True)
    devbuy = np.array([sum(s for ag, w, b, s in c.w if b and w == c.dev and ag <= c.w[0][0] + 0.2) for c in coins])
    R["devbuy_share"] = {k: float(np.mean(devbuy >= k)) for k in (0.5, 1, 2, 5)}
    fams = []  # (nama, labels_filter, masks(F,n), X(n,E), Tx(n,E), period(n), t_in(n), coin_idx(n), exits, nullfn)

    # ---------- S1 SNIPER
    bands = [("semua", 0, 1e9), ("<0,5", 0, 0.5), ("0,5-1", 0.5, 1), ("1-2", 1, 2), ("2-5", 2, 5), (">=5", 5, 1e9), (">=0,5", 0.5, 1e9)]
    for L in DELAYS:
        rows, rT, keep, tin = [], [], [], []
        for c in coins:
            p = bevan.path(c)
            lx = lag(L, rng)
            te = c.w[0][0] + lx
            o = outcomes(c, p, te, lx, EX1)
            if o:
                rows.append(o[0]); rT.append(o[1]); keep.append(c.i); tin.append(c.t0 + te)
        keep = np.array(keep)
        db = devbuy[keep]
        masks = np.array([(db >= lo) & (db < hi) for _, lo, hi in bands])
        fams.append(dict(name=f"S1 sniper jeda {L}", fl=[f"devbuy {b[0]} SOL" for b in bands], masks=masks,
                         X=np.array(rows), Tx=np.array(rT), per=per_c[keep], tin=np.array(tin), ci=keep, ex=EX1,
                         feat=db, kind="S1", bands=bands))
        print(f"S1 L{L}: {len(keep)} trade, {time.time()-T0:.0f}s", flush=True)
    for c in coins:
        c.path = None

    # ---------- S1b MOMENTUM
    mcb = [("<35", 0, 35), ("35-60", 35, 60), ("60-120", 60, 120), (">=120", 120, 1e9), ("semua", 0, 1e9)]
    byb, t10b, grb, dvb = (0, 10, 30), (0.25, 0.40, 9), (0, 1.3, 2.0), (0, 0.5)
    for D in (10, 30, 60, 120, 300):
        for L in DELAYS:
            rows, rT, keep, tin, F = [], [], [], [], []
            for c in coins:
                sn = c.snaps.get(D)
                if sn is None or c.end < D + 10:
                    continue
                p = bevan.path(c)
                lx = lag(L, rng)
                o = outcomes(c, p, D + lx, lx, EX1)
                if o:
                    rows.append(o[0]); rT.append(o[1]); keep.append(c.i); tin.append(c.t0 + D + lx)
                    F.append((float(sn[1]), float(sn[FI["unique_buyers"]]), float(sn[FI["top10"]]), float(sn[FI["growth"]]), devbuy[c.i]))
            for c in coins:
                c.path = None
            if len(keep) < 10:
                continue
            F = np.array(F); keep = np.array(keep)
            masks, fl = [], []
            for mn, lo, hi in mcb:
                for b in byb:
                    for t1 in t10b:
                        for g in grb:
                            for d in dvb:
                                masks.append((F[:, 0] >= lo) & (F[:, 0] < hi) & (F[:, 1] >= b) & (F[:, 2] <= t1) & (F[:, 3] >= g) & (F[:, 4] >= d))
                                fl.append(f"D{D}s mcap {mn} buyer>={b} top10<={t1 if t1 < 9 else 'bebas'} growth>={g} dev>={d}")
            fams.append(dict(name=f"S1b momentum D{D} jeda {L}", fl=fl, masks=np.array(masks), X=np.array(rows), Tx=np.array(rT),
                             per=per_c[keep], tin=np.array(tin), ci=keep, ex=EX1, feat=F, kind="S1b", D=D))
            print(f"S1b D{D} L{L}: {len(keep)} trade, {time.time()-T0:.0f}s", flush=True)

    # ---------- S2 GRADUATION
    agb = [("semua", 0, 1e9), ("<5m", 0, 300), ("5-15m", 300, 900), (">15m", 900, 1e9)]
    for pc in (50, 60, 70, 80, 90, 95, 98):
        thr = (30 + pc / 100 * 85) ** 2 / kol.K_CURVE
        hits = []
        for c in coins:
            if c.peak < thr:
                continue
            p = bevan.path(c)
            th = next((t for t, cl, hi, lo in p.points(0.0) if hi >= thr), None)
            if th is not None:
                hits.append((c.i, th))
            c.path = None
        for L in DELAYS:
            rows, rT, keep, tin, ages = [], [], [], [], []
            for ci, th in hits:
                c = coins[ci]
                p = bevan.path(c)
                lx = lag(L, rng)
                o = outcomes(c, p, th + lx, lx, EX2)
                c.path = None
                if o:
                    rows.append(o[0]); rT.append(o[1]); keep.append(ci); tin.append(c.t0 + th + lx); ages.append(th)
            if len(keep) < 5:
                continue
            ages = np.array(ages); keep = np.array(keep)
            masks = np.array([(ages >= lo) & (ages < hi) for _, lo, hi in agb])
            fams.append(dict(name=f"S2 graduation {pc}% jeda {L}", fl=[f"kurva {pc}% umur {b[0]}" for b in agb], masks=masks,
                             X=np.array(rows), Tx=np.array(rT), per=per_c[keep], tin=np.array(tin), ci=keep, ex=EX2,
                             feat=ages, kind="S2", bands=agb))
            print(f"S2 {pc}% L{L}: {len(keep)} trade, {time.time()-T0:.0f}s", flush=True)

    # ---------- S3 COPY WALLET (statistik kausal)
    done = []  # (t_selesai, wallet, win, pnl, hold)
    for c in coins:
        per = {}
        for ag, w, b, s in c.w:
            d = per.setdefault(w, [0.0, 0.0, None, None])
            if b:
                d[0] += s
                d[2] = ag if d[2] is None else d[2]
            else:
                d[1] += s
                if d[2] is not None and d[3] is None:
                    d[3] = ag
        for w, (bs, ss, fb, fs) in per.items():
            if bs > 0 and ss > 0:
                done.append((c.t0 + c.cov, w, ss > bs, ss - bs, (fs - fb) if (fs is not None and fb is not None) else 999))
    done.sort(key=lambda x: x[0])
    hist = {}
    ptr = 0
    ev = []  # (ci, j, a, wallet, statvec_all, statvec_6h)
    for c in coins:
        seen = set()
        for j, (ag, w, b, s) in enumerate(c.w):
            if not b or w in seen:
                continue
            seen.add(w)
            tabs = c.t0 + ag
            while ptr < len(done) and done[ptr][0] <= tabs:
                d = done[ptr]
                hist.setdefault(d[1], []).append(d)
                ptr += 1
            h = hist.get(w)
            if not h or len(h) < 5:
                continue
            def sv(hh):
                if not hh:
                    return (0, 0, 0, 999)
                return (len(hh), sum(x[2] for x in hh) / len(hh), sum(x[3] for x in hh), float(np.median([x[4] for x in hh])))
            h6 = [x for x in h if x[0] >= tabs - 6 * 3600]
            ev.append((c.i, j, ag, w, sv(h), sv(h6)))
    print(f"S3: {len(ev)} event wallet ber-riwayat >=5 koin, {time.time()-T0:.0f}s", flush=True)
    rules = [(mn, wr, hd, wd) for mn in (5, 10, 20) for wr in (0.5, 0.65, 0.8) for hd in ("semua", "<=60", ">60") for wd in ("semua", "6j")]
    if ev:
        SV = np.array([list(e[4]) + list(e[5]) for e in ev])
        evci = np.array([e[0] for e in ev])

        def rule_masks(SV):
            ms_ = []
            for mn, wr, hd, wd in rules:
                o = 0 if wd == "semua" else 4
                m = (SV[:, o] >= mn) & (SV[:, o + 1] >= wr) & (SV[:, o + 2] > 0)
                if hd == "<=60":
                    m &= SV[:, o + 3] <= 60
                elif hd == ">60":
                    m &= (SV[:, o + 3] > 60) & (SV[:, o + 3] < 999)
                ms_.append(m)
            return np.array(ms_)
        base = rule_masks(SV)
        anyq = base.any(0)
        idx_ev = np.where(anyq)[0]
        print(f"S3: {len(idx_ev)} event lolos minimal 1 aturan", flush=True)
        for L in DELAYS:
            rows, rT, keep, tin, okev = [], [], [], [], []
            for q in idx_ev:
                ci, j, ag, w = ev[q][:4]
                c = coins[ci]
                p = kol.Path(c, j)
                lx = lag(L, rng)
                te = ag + lx
                if te >= c.end - 1:
                    continue
                p_in = p.entry(lx)
                if p_in <= 0:
                    continue
                fol = next((a2 for a2, w2, b2, s2 in c.w if w2 == w and not b2 and a2 > ag), None)
                pts = pts_of(p, te)
                xs = np.empty(len(EX3), np.float32); ts = np.empty(len(EX3))
                for k, e in enumerate(EX3):
                    po, tx = run_exit(c, p, pts, te, p_in, e, lx, fol if e.get("follow") else None)
                    xs[k] = mult(p_in, po); ts[k] = c.t0 + tx
                rows.append(xs); rT.append(ts); keep.append(ci); tin.append(c.t0 + te); okev.append(q)
            if len(okev) < 5:
                continue
            okev = np.array(okev)
            fams.append(dict(name=f"S3 copy-wallet jeda {L}", fl=[f"copy min{mn} wr>={wr} hold {hd} jendela {wd}" for mn, wr, hd, wd in rules],
                             X=np.array(rows), Tx=np.array(rT), per=per_c[np.array(keep)], tin=np.array(tin), ci=np.array(keep), ex=EX3,
                             SV=SV[okev], rule_masks=rule_masks, kind="S3"))
            print(f"S3 L{L}: {len(okev)} trade, {time.time()-T0:.0f}s", flush=True)

    def first_per_coin(m, ci, tin):
        # 1 entry per koin (event pertama yg lolos)
        out = np.zeros_like(m)
        seen = set()
        for i in np.argsort(tin):
            if m[i] and ci[i] not in seen:
                seen.add(ci[i]); out[i] = True
        return out

    for f in fams:
        if f["kind"] == "S3":
            f["masks"] = np.array([first_per_coin(m, f["ci"], f["tin"]) for m in f["rule_masks"](f["SV"])])

    # ---------- skor semua kombinasi
    allrows = []
    tot_combo = 0
    real_pass = 0
    real_cand = 0
    real_ab = 0
    for fi, f in enumerate(fams):
        n, m = stats(f["X"], f["masks"], f["per"])
        f["n"], f["m"] = n, m
        tot_combo += f["masks"].shape[0] * f["X"].shape[1]
        cp, cc, cab = count_pass(n, m, f["X"], f["masks"], f["per"])
        cand = (n[:, 2][:, None] >= 30) & (m[:, 0] > 1) & (m[:, 1] > 1) & (m[:, 2] > 1)
        for fl_i, k in zip(*np.where(cand)):
            xs = f["X"][f["masks"][fl_i] & (f["per"] == 2), k].astype(float)
            R.setdefault("passlist", []).append(dict(fam=f["name"], filt=f["fl"][fl_i], exit=exname(f["ex"][k]), nA=n[fl_i,0], nB=n[fl_i,1], nC=n[fl_i,2],
                 A=m[fl_i,0,k], B=m[fl_i,1,k], C=m[fl_i,2,k], nobest=nobest_mean(xs), shuffle_invariant=bool(f["masks"][fl_i].all()), key=(fams.index(f), int(fl_i), int(k))))
        real_pass += cp; real_cand += cc; real_ab += cab
        for fl_i in range(f["masks"].shape[0]):
            for k in range(f["X"].shape[1]):
                if n[fl_i, 0] >= 30 and not math.isnan(m[fl_i, 0, k]):
                    allrows.append((float(m[fl_i, 0, k]), fi, fl_i, k))
    print(f"kombinasi {tot_combo:,}; lulus {real_pass}; kandidat (A,B,C>1 n_C>=30) {real_cand}; A&B>1 {real_ab}", flush=True)

    # ---------- NULL
    nulls = []
    for s in range(a.null):
        r2 = np.random.default_rng(100 + s)
        cnt = 0
        for f in fams:
            if f["kind"] == "S3":
                perm = r2.permutation(len(f["SV"]))
                masks = np.array([first_per_coin(m, f["ci"], f["tin"]) for m in f["rule_masks"](f["SV"][perm])])
            else:
                perm = r2.permutation(f["masks"].shape[1])
                masks = f["masks"][:, perm]
            n, m = stats(f["X"], masks, f["per"])
            cnt += count_pass(n, m, f["X"], masks, f["per"])[0]
        nulls.append(cnt)
        print(f"null {s}: {cnt}", flush=True)

    # ---------- top 5 by A, cek B, final C
    allrows.sort(reverse=True)
    top = []
    seen_keys = set()
    for mA, fi, fl_i, k in allrows:
        key = (fams[fi]["name"], fl_i, k)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        top.append((fi, fl_i, k))
        if len(top) >= 5:
            break
    # top per keluarga juga
    topfam = {}
    for mA, fi, fl_i, k in allrows:
        kd = fams[fi]["kind"]
        if kd not in topfam:
            topfam[kd] = (fi, fl_i, k)

    def detail(fi, fl_i, k, do_c):
        f = fams[fi]
        d = dict(fam=f["name"], filt=f["fl"][fl_i], exit=exname(f["ex"][k]))
        for s, lab in ((0, "A"), (1, "B"), (2, "C")):
            sel = f["masks"][fl_i] & (f["per"] == s)
            xs = f["X"][sel, k].astype(float)
            if s == 2 and not do_c:
                d["C"] = "tidak diuji (gagal di B)"
                continue
            kk = int((xs > 1).sum())
            lo, hi = ms.wilson(kk, len(xs)) if len(xs) else (0, 0)
            gains, losses = (xs[xs > 1] - 1).sum(), (1 - xs[xs < 1]).sum()
            d[lab] = dict(n=len(xs), mean=float(xs.mean()) if len(xs) else None, median=float(np.median(xs)) if len(xs) else None,
                          win=kk / len(xs) if len(xs) else None, wilson=(lo, hi), pf=float(gains / losses) if losses > 0 else None,
                          nobest=nobest_mean(xs), best=float(xs.max()) if len(xs) else None)
            if s == 2:
                d["C"]["p_boot"] = boot_p(xs)
                tr = [(f["tin"][i], float(f["X"][i, k]), f["Tx"][i, k]) for i in np.where(sel)[0]]
                d["C"]["sim"] = {f"{int(fr*100)}% maks{mp}": sim200(tr, fr, mp) for fr in (0.08, 0.10) for mp in (1, 5)}
        return d

    R["top5"] = []
    for fi, fl_i, k in top:
        mB = fams[fi]["m"][fl_i, 1, k]
        R["top5"].append(detail(fi, fl_i, k, do_c=bool(mB > 1)))
    R["topfam"] = {kd: detail(*v, do_c=bool(fams[v[0]]["m"][v[1], 1, v[2]] > 1)) for kd, v in topfam.items()}
    R["passdetail"] = [detail(*p["key"], True) for p in R.get("passlist", []) if "min5 wr>=0.5 hold semua jendela semua" in p["filt"]]
    z = [i for i, f in enumerate(fams) if f["kind"] == "S3"]
    R["zostaff80"] = [detail(fi, fams[fi]["fl"].index("copy min20 wr>=0.8 hold semua jendela semua"), 0, True) for fi in z]
    # versi asli zostaff di C (referensi)
    ref = {}
    for f in fams:
        if f["kind"] == "S1" and f["name"].endswith("1"):
            for lab, (bi, ek) in {"POST devbuy>=0,5 TP2 SL0,5 120s": (6, dict(tp=2, sl=0.5, T=120)),
                                  "ARTIKEL devbuy>=0,5 TP1,5 SL0,7 30s": (6, dict(tp=1.5, sl=0.7, T=30))}.items():
                k = next(i for i, e in enumerate(EX1) if e == ek)
                ref[lab] = detail(fams.index(f), bi, k, True)
    R["ref"] = ref
    R["combos"] = tot_combo
    R["families"] = [(f["name"], int(f["masks"].shape[0]), int(f["X"].shape[1]), int(f["X"].shape[0])) for f in fams]
    R["real_pass"], R["real_cand"], R["real_ab"] = real_pass, real_cand, real_ab
    R["null"] = nulls
    R["secs"] = time.time() - T0
    os.makedirs(a.out, exist_ok=True)
    json.dump(R, open(os.path.join(a.out, "zgrid_result.json"), "w"), indent=1, default=float)
    print(json.dumps({k: R[k] for k in ("combos", "real_pass", "real_cand", "real_ab", "null")}, default=float))
    print(f"selesai {R['secs']:.0f}s")


if __name__ == "__main__":
    main()

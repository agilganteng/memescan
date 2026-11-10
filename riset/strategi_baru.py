"""Keluarga strategi baru. PAPER. Daftar di bawah dikunci sebelum cache dibaca.

Target pembanding, tidak disetel ulang: aturan (b) + gerbang jam lahir 12–16 UTC.
Entri aturan (b): umur 120, jeda 3–8, growth>=3, beli>=0,65, vol>=3, laju>=1,5,
jual parsial 50% di 2x sisa TP5 SL0,7 600 dtk.
Gerbang: jeda 0,4, syarat (b) plus drawdown<=0,35 dan jam UTC [12,16), jual TP5 SL0,7 1800 dtk.

Protokol, dikunci di sini:
- Setel hanya di A (t0 < 2 Nov 2026 17:43 UTC). Di tiap keluarga, ambil satu konfigurasi
  dengan n_A>=30, rata A>1, dan A tanpa koin terbaik >1. Pilihan = rata A tertinggi.
- B (sampai 5 Nov 2026 16:55 UTC) diuji sekali pada pilihan itu. Lulus B: n_B>=30,
  rata B>1, B tanpa koin terbaik >1.
- C tercemar, hanya dilaporkan. t0 sesudah 10 Nov 2026 07:17 UTC tidak masuk A, tidak masuk B,
  tidak memilih. Kalau ada, itu irisan konfirmasi, termasuk untuk gerbang lama.
- Null 20x mengacak urutan hasil di dalam tiap konfigurasi, periode koin tetap.
  Bonferroni 0,05 / jumlah konfigurasi pada uji B pilihan.
- Biaya sama dengan riset sebelumnya: fee 1,25%/sisi, slip 2%/sisi, priority 0,0005 SOL,
  ukuran 0,1 SOL, stop candle x0,72.
- Mengalahkan gerbang hanya jika lulus protokol dan rata B serta B tanpa terbaik
  keduanya lebih tinggi dari gerbang yang dihitung ulang di run ini.
- LAYAK hanya jika itu terjadi dan irisan segar juga lolos (n>=30, rata>1, tanpa terbaik >1).
  Tanpa koin segar, vonis paling tinggi BELUM LAYAK.

Keluarga, ambang tidak digeser setelah hasil:
F1 Exit pada entri (b) saja, jeda dan filter (b) tetap. Jual: parsial baseline;
waktu 120/300/600/1800 SL0,7 tanpa TP; parsial 2x sisa TP3 600 dan 1800;
parsial 2x sisa TP5 1800; parsial 3x sisa TP5 600 dan 1800; trail +50% lebar 20% 600 dan 1800;
trail +50% lebar 30% 1800; trail +100% lebar 30% 1800; moonbag 70% di 2x dan di 3x, sisa trail 30%.
Transfer: jual pemenang F1 dipasang ke entri gerbang. Bukan pencarian jual di gerbang.
F2 Gelombang kedua. Sesudah detik 120 harga menyentuh 2x atau 3x dari jangkar, lalu turun 20% atau 35%
dari puncak, lalu reclaim: kembali ke harga detik 120, atau ke 90% puncak sebelum turun.
Di dalam satu candle puncak diperbarui dari high dulu, baru cek turun. Reclaim hanya di candle berikut.
Jeda 3–8. Jual: parsial baseline, TP2 SL0,7 600, trail +50% lebar 30% 1800.
F3 Dev/pembuat, bukan snipe 0,4 dtk yang sudah gagal. Umur 60 dan 120, jeda 3–8, jual parsial.
Dev beli (0, 0,5) SOL atau [0,5, 2) SOL, dev belum jual, belum pernah rug.
Tambahan di umur 120: dev_pct<=5% dan token pertama; atau dev_pct<=10% dan belum rug.
F4 Ukuran trade dan pertumbuhan pembeli. Tape wallet hanya sampai 5 menit; kalau cakupan
lebih pendek dari umur keputusan, aturan ini gagal tertutup.
Banyak kecil: beli>=20, median<=0,5 SOL, beli terbesar<=25% total, unik>=15.
Sedikit besar: beli 5–15, median>=1 SOL, terbesar>=30% (kontras, bukan harapan untung).
Pertumbuhan unik 120-60 >=10 dan laju pembeli>=1. Gabungan banyak-kecil + pertumbuhan.
Umur 60: unik 60-30>=8, beli>=12, median<=0,5.
F5 Tanpa tekanan jual. Jendela (60,120] atau (30,60]: nol jual dan beli cukup, atau SOL jual <=10%
dan drawdown<=0,35. Gagal tertutup kalau tidak ada volume di jendela.
F6 Jam dan hari untuk aturan LAIN, dipilih di A. Bukan mengulang jam 12–16 pada aturan (b).
Blok jam 0–6, 6–12, 12–18, 18–24 UTC. Hari: semua, hari kerja, akhir pekan.
Dasarnya mom120 dan dev-beli [0,5, 2) umur 120. Kalender data hanya sekitar dua minggu.
F7 Momentum dekat lulus, bukan grid 50–98% dan bukan kontrol 92%. Kurva 70/80/90%,
sinyal pertama pada umur >=120 dtk, harga >=1,5x harga 60 dtk sebelumnya, jeda 3–8.
Jual TP2 SL0,7 600 atau trail +50% lebar 20% SL0,7 600.
F8 Aturan (b) plus gerbang anti-rug. growth<2 TIDAK dipakai karena bertentangan dengan (b).
P1: top10<=30%, dev<=5%, belum jual, belum rug, bundle<5, bukan proksi fresh, drawdown<=40%.
P2: top10<=35%, dev<=10%, belum jual, belum rug, bundle<5, drawdown<=50%.
Proksi fresh: unik>=20, holder<=8, unik/holder>=3. Bundle = pembeli non-dev pada detik pertama.
Satu baris tambahan: entri gerbang 12–16 yang juga lolos P1, jual gerbang tetap.
Anti-honeypot tidak diuji.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import amplify_b as ab  # noqa: E402
import grid_luas as gl  # noqa: E402

CUT1, CUT2, CLEAN = ab.CUT1, ab.CUT2, ab.CLEAN_AFTER
NMIN = 30


def _ex(kind, name, tp=1e9, sl=0.7, T=600.0, arm=0.0, trail=0.0, tp2=0.0, tp3=0.0, w1=1.0, w2=0.0):
    return dict(kind=kind, name=name, tp=tp, sl=sl, T=T, arm=arm, trail=trail, tp2=tp2, tp3=tp3, w1=w1, w2=w2)


F1_EXITS = (
    ab.BASE_EXIT,
    _ex(0, "waktu 120s SL0.7", T=120),
    _ex(0, "waktu 300s SL0.7", T=300),
    _ex(0, "waktu 600s SL0.7", T=600),
    _ex(0, "waktu 1800s SL0.7", T=1800),
    _ex(2, "parsial 50% 2x sisa TP3 SL0.7 600s", tp=2, tp2=3, T=600, w1=0.5, w2=0.5),
    _ex(2, "parsial 50% 2x sisa TP3 SL0.7 1800s", tp=2, tp2=3, T=1800, w1=0.5, w2=0.5),
    _ex(2, "parsial 50% 2x sisa TP5 SL0.7 1800s", tp=2, tp2=5, T=1800, w1=0.5, w2=0.5),
    _ex(2, "parsial 50% 3x sisa TP5 SL0.7 600s", tp=3, tp2=5, T=600, w1=0.5, w2=0.5),
    _ex(2, "parsial 50% 3x sisa TP5 SL0.7 1800s", tp=3, tp2=5, T=1800, w1=0.5, w2=0.5),
    _ex(1, "trail +50% lebar 20% SL0.7 600s", arm=0.5, trail=0.2, T=600),
    _ex(1, "trail +50% lebar 20% SL0.7 1800s", arm=0.5, trail=0.2, T=1800),
    _ex(1, "trail +50% lebar 30% SL0.7 1800s", arm=0.5, trail=0.3, T=1800),
    _ex(1, "trail +100% lebar 30% SL0.7 1800s", arm=1.0, trail=0.3, T=1800),
    _ex(5, "moonbag 70% di 2x sisa trail 30% 1800s", tp=2, sl=0.7, T=1800, trail=0.3, w1=0.7, w2=0),
    _ex(5, "moonbag 70% di 3x sisa trail 30% 1800s", tp=3, sl=0.7, T=1800, trail=0.3, w1=0.7, w2=0),
)
F2_EXITS = (
    ab.BASE_EXIT,
    _ex(0, "TP2 SL0.7 600s", tp=2, sl=0.7, T=600),
    _ex(1, "trail +50% lebar 30% SL0.7 1800s", arm=0.5, trail=0.3, T=1800),
)
F7_EXITS = (
    _ex(0, "TP2 SL0.7 600s", tp=2, sl=0.7, T=600),
    _ex(1, "trail +50% lebar 20% SL0.7 600s", arm=0.5, trail=0.2, T=600),
)
GATE_EXIT = _ex(0, "TP5 SL0.7 1800s", tp=5, sl=0.7, T=1800)


def rule_gate():
    return dict(ab.RULE_B, name="(b)+jam 12-16 UTC", delay="0.4",
                conds=list(ab.RULE_B["conds"]) + [(11, "<=", 0.35), (15, ">=", 12.0), (15, "<", 16.0)],
                exit=GATE_EXIT)


def gt1(x):
    return x is not None and x == x and float(x) > 1.0


def cal(t0):
    dt = datetime.datetime.fromtimestamp(float(t0), datetime.timezone.utc)
    return dt.hour, dt.weekday() >= 5


def g(sn, name):
    return float(sn[gl.FI[name]])


def trade_stats(c, t0, t1):
    buys, buy_sol, sell_n, sell_sol = [], 0.0, 0, 0.0
    for ag, _w, b, s in c.w:
        if ag <= t0 or ag > t1:
            continue
        if b:
            buys.append(float(s))
            buy_sol += float(s)
        else:
            sell_n += 1
            sell_sol += float(s)
    n_b = len(buys)
    if n_b and buy_sol > 0:
        med = float(np.median(buys))
        mx = max(buys) / buy_sol
    else:
        med, mx = 999.0, 1.0
    share = sell_sol / (buy_sol + sell_sol) if (buy_sol + sell_sol) > 0 else 1.0
    return n_b, med, mx, sell_n, share


def fresh_of(sn):
    ub, ho = g(sn, "unique_buyers"), g(sn, "holders")
    return 1.0 if (ub >= 20.0 and ho <= 8.0 and ub / max(ho, 1.0) >= 3.0) else 0.0


def build_feat(c, info, age, prev):
    fr = ab.feat_of(c, age, info)
    sn = c.snaps.get(age)
    if fr is None or sn is None:
        return None
    snp = c.snaps.get(prev)
    sold = 1.0 if (float(fr[5]) >= 1.0 or g(sn, "dev_sold_any") >= 1.0) else 0.0
    nb, med, mx, _ns, _ss = trade_stats(c, -0.1, float(age))
    wb, _m2, _x2, wns, wss = trade_stats(c, float(prev), float(age))
    hour, weekend = cal(c.t0)
    return dict(
        growth=float(fr[9]), bsr=float(fr[10]), vol=float(fr[12]), rate=float(fr[13]),
        dd=float(fr[11]), top10=float(fr[1]), devbuy=float(fr[6]), rugs=float(fr[8]),
        dev=g(sn, "dev_pct"), bundle=g(sn, "bundle"), tokens=g(sn, "creator_prev_tokens"),
        fresh=fresh_of(sn), sold=sold, n_buys=nb, med=med, mx=mx,
        n_buys_w=wb, n_sell_w=wns, sell_share=wss, ub=g(sn, "unique_buyers"),
        uprev=(g(snp, "unique_buyers") if snp is not None else -1.0),
        cov=float(c.cov), hour=hour, weekend=1.0 if weekend else 0.0,
    )


def tape_ok(f, age):
    return f is not None and f["cov"] >= age


def p1_ok(f):
    return (f["top10"] <= 0.30 and f["dev"] <= 0.05 and f["sold"] == 0 and f["rugs"] < 1
            and f["bundle"] < 5 and f["fresh"] == 0 and f["dd"] <= 0.40)


def p2_ok(f):
    return (f["top10"] <= 0.35 and f["dev"] <= 0.10 and f["sold"] == 0 and f["rugs"] < 1
            and f["bundle"] < 5 and f["dd"] <= 0.50)


def dev_band(f, lo, hi):
    return f["sold"] == 0 and f["rugs"] < 1 and lo <= f["devbuy"] < hi and not (lo == 0 and f["devbuy"] == 0)


def second_wave(pa, p0, p_level, pump, dip, mode):
    t, hi, lo = pa["bar_t"], pa["bar_hi"], pa["bar_lo"]
    if t.size == 0 or p0 <= 0 or p_level <= 0:
        return None
    i0 = int(np.searchsorted(t, 120.0, side="left"))
    pumped, dipped, peak, peak_at = False, False, 0.0, 0.0
    dip_i = -1
    for i in range(i0, t.size):
        if not pumped:
            if hi[i] >= p0 * pump:
                pumped = True
                peak = float(hi[i])
            continue
        if not dipped:
            if hi[i] > peak:
                peak = float(hi[i])
            if peak > 0 and lo[i] <= peak * (1.0 - dip):
                dipped = True
                peak_at = peak
                dip_i = i
            continue
        if i == dip_i:
            continue
        if mode == "level120" and hi[i] >= p_level:
            return float(t[i])
        if mode == "peak90" and hi[i] >= 0.90 * peak_at:
            return float(t[i])
    return None


def first_curve(pa, pc, min_age=120.0):
    thr = (30.0 + (pc / 100.0) * 85.0) ** 2 / gl.K_CURVE
    t, hi = pa["bar_t"], pa["bar_hi"]
    if t.size == 0:
        return None
    i0 = int(np.searchsorted(t, min_age, side="left"))
    for i in range(i0, t.size):
        if hi[i] >= thr:
            return float(t[i])
    return None


def enter_row(c, pa, te, lx, exit_):
    if te >= c.end - 1:
        return None
    p_in = gl.price_at_py(pa, te)
    if p_in <= 0:
        return None
    x, to = ab.one_x(pa, te, lx, p_in, exit_)
    return dict(i=c.i, t=c.t0 + te, tout=c.t0 + to, x=float(x), per=ab.period_of(c.t0), te=te, lx=lx)


def stats_of(xs):
    xs = np.asarray(xs, np.float64)
    xs = xs[np.isfinite(xs)]
    n = int(xs.size)
    if n == 0:
        return dict(n=0, mean=None, median=None, win=None, wilson=[0.0, 0.0], nobest=None)
    wins = int(np.sum(xs > 1.0))
    lo, hi = gl.wilson(wins, n)
    return dict(n=n, mean=float(xs.mean()), median=float(np.median(xs)), win=wins / n,
                wilson=[float(lo), float(hi)], nobest=(float(gl.nobest_of(xs)) if n >= 2 else None))


def books_of(rows):
    out = {}
    for frac, mp in ((0.08, 1), (0.08, 5), (0.10, 1), (0.10, 5)):
        out[f"{int(frac * 100)}% m{mp}"] = ab.sim_book(rows, frac, mp, 200.0) if rows else None
    return out


def pack(family, name, rows):
    per = np.array([r["per"] for r in rows], np.int8) if rows else np.zeros(0, np.int8)
    x = np.array([r["x"] for r in rows], np.float64) if rows else np.zeros(0, np.float64)
    basic = {}
    for p, lab in ((0, "A"), (1, "B"), (2, "C"), (3, "segar")):
        basic[lab] = stats_of(x[per == p] if x.size else [])
    return dict(family=family, name=name, rows=rows, per=per, x=x, basic=basic,
                nA=basic["A"]["n"], meanA=basic["A"]["mean"], nobA=basic["A"]["nobest"],
                nB=basic["B"]["n"], meanB=basic["B"]["mean"], nobB=basic["B"]["nobest"],
                role="")


def passes_ab(per, x):
    if x.size == 0:
        return False
    a, b = x[per == 0], x[per == 1]
    return (ok_nob(a) and ok_nob(b))


def ok_nob(x):
    x = np.asarray(x, np.float64)
    x = x[np.isfinite(x)]
    return x.size >= NMIN and float(x.mean()) > 1.0 and float(gl.nobest_of(x)) > 1.0


def eligible(c):
    return c["nA"] >= NMIN and gt1(c["meanA"]) and gt1(c["nobA"])


def pick(family, cfgs):
    pool = [c for c in cfgs if c["family"] == family]
    good = [c for c in pool if eligible(c)]
    good.sort(key=lambda c: (c["meanA"], c["nobA"] or -1, c["nA"]), reverse=True)
    if good:
        good[0]["role"] = "pilihan A"
        return good[0]
    rest = [c for c in pool if c["nA"] >= NMIN and c["meanA"] is not None]
    rest.sort(key=lambda c: (c["meanA"], c["nA"]), reverse=True)
    if rest:
        rest[0]["role"] = "terbaik A, tidak lolos syarat A"
        return rest[0]
    if pool:
        pool[0]["role"] = "tidak ada n_A cukup"
        return pool[0]
    return None


def fmt_x(x):
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"{float(x):.3f}".replace(".", ",") + "x"


def fmt_p(x):
    if x is None or (isinstance(x, float) and x != x):
        return "—"
    return f"{100 * float(x):.1f}%".replace(".", ",")


def fmt_money(bk):
    if not bk:
        return "—"
    return f"${bk['end']:.0f} / DD {fmt_p(bk['max_dd'])}"


def cell(st):
    if not st or not st.get("n"):
        return "0 | — | — | — | — | — | — | —"
    w = st.get("wilson") or [0, 0]
    b = st.get("books") or {}
    return (f"{st['n']} | {fmt_x(st['mean'])} | {fmt_p(st['win'])} [{fmt_p(w[0])}–{fmt_p(w[1])}] | "
            f"{fmt_x(st['nobest'])} | {fmt_money(b.get('8% m1'))} | {fmt_money(b.get('8% m5'))} | "
            f"{fmt_money(b.get('10% m1'))} | {fmt_money(b.get('10% m5'))}")


def with_books(c):
    if c.get("full"):
        return c["full"]
    full = {}
    for p, lab in ((0, "A"), (1, "B"), (2, "C"), (3, "segar")):
        sub = [r for r in c["rows"] if r["per"] == p]
        s = stats_of([r["x"] for r in sub])
        s["books"] = books_of(sub)
        full[lab] = s
    c["full"] = full
    return full


def add_rows(L, name, c):
    name = name.replace("|", "/")
    st = with_books(c)
    L.append(f"| {name} | | | | | | | | | |")
    for lab in ("A", "B", "C", "segar"):
        L.append(f"| | {lab} | {cell(st[lab])} |")


def boot(c):
    xs = c["x"][c["per"] == 1] if c["x"].size else np.zeros(0)
    xs = xs[np.isfinite(xs)]
    if xs.size < 5:
        return None
    p, B = gl.boot_p(xs, B=100000, seed=1)
    return p if p > 0 else 1.0 / B


def self_test():
    t = np.array([120.0, 140.0, 180.0, 220.0, 260.0])
    hi = np.array([12.0, 30.0, 28.0, 16.0, 29.0])
    lo = np.array([11.0, 20.0, 14.0, 15.0, 18.0])
    pa = {"bar_t": t, "bar_hi": hi, "bar_lo": lo}
    # puncak 30 di detik 140, turun ke 14 (=53% turun) di detik 180, reclaim 90% puncak = 27 di detik 260.
    assert second_wave(pa, 10.0, 12.0, 2.0, 0.35, "peak90") == 260.0
    assert second_wave(pa, 10.0, 12.0, 2.0, 0.35, "level120") == 220.0
    assert second_wave(pa, 10.0, 12.0, 5.0, 0.20, "peak90") is None
    assert dev_band(dict(sold=0, rugs=0, devbuy=0.0), 0.0, 0.5) is False
    assert dev_band(dict(sold=0, rugs=0, devbuy=0.2), 0.0, 0.5) is True
    assert dev_band(dict(sold=0, rugs=0, devbuy=0.5), 0.5, 2.0) is True
    assert p1_ok(dict(top10=0.2, dev=0.04, sold=0, rugs=0, bundle=1, fresh=0, dd=0.2))
    assert not p1_ok(dict(top10=0.2, dev=0.04, sold=0, rugs=0, bundle=1, fresh=0, dd=0.2) | {"fresh": 1})
    per = np.array([0] * 40 + [1] * 40, np.int8)
    x = np.concatenate([np.full(40, 1.2), np.full(40, 1.1)])
    assert passes_ab(per, x)
    x2 = x.copy()
    x2[40:] = 0.5
    assert not passes_ab(per, x2)
    assert first_curve({"bar_t": np.array([10.0, 130.0]), "bar_hi": np.array([1.0, 1e9])}, 70) == 130.0
    print("self-test OK. Daftar keluarga sudah dikunci sebelum cache.", flush=True)


def sim_list(coins, paths, specs):
    """specs: list of (name, coin, te, lx, exit)."""
    out = []
    for name, c, te, lx, exit_ in specs:
        row = enter_row(c, paths[c.i], te, lx, exit_)
        if row is not None:
            out.append((name, row))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    ap.add_argument("--out", default="riset/riset-strategi-baru-2026-11-10.md")
    ap.add_argument("--null", type=int, default=20)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    print("DAFTAR PRA-REGISTRASI, sebelum cache dibaca.", flush=True)
    print(__doc__, flush=True)
    self_test()
    if a.self_test:
        return
    t0 = time.time()
    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()
    print(f"sha {sha}", flush=True)
    print(f"cache={os.environ.get('CACHE_MATCHED_KEY', '')}", flush=True)
    gl._need_numba()
    coins, meta = gl.load_coins(a.data)
    for i, c in enumerate(coins):
        c.i = i
        c.full_i = i
    n_fresh_coins = sum(1 for c in coins if c.t0 > CLEAN)
    print("jalur...", flush=True)
    paths = []
    for i, c in enumerate(coins):
        paths.append(gl.extract_path(c))
        if i and i % 5000 == 0:
            print(f"  jalur {i}", flush=True)
    print("anotasi...", flush=True)
    ann = ab.annotate(coins, (30, 60, 120, 180))
    print("basis gerbang, aturan (b), mom120", flush=True)
    gate_rows = ab.sim_rule(coins, paths, ann, rule_gate())
    b_rows = ab.sim_rule(coins, paths, ann, ab.RULE_B)
    mom_rows = ab.sim_rule(coins, paths, ann, ab.RULE_A)
    for rows in (gate_rows, b_rows, mom_rows):
        for r in rows:
            r["per"] = ab.period_of(coins[r["i"]].t0)
    gate = pack("basis", "(b)+jam 12-16 UTC", gate_rows)
    raw_b = pack("basis", "aturan (b) tanpa jam", b_rows)
    print(f"gerbang nB {gate['nB']} rata {gate['meanB']}", flush=True)
    feat120, feat60 = {}, {}
    for i, c in enumerate(coins):
        f = build_feat(c, ann[i], 120, 60)
        if f is not None:
            feat120[i] = f
        f6 = build_feat(c, ann[i], 60, 30)
        if f6 is not None:
            feat60[i] = f6
    cfgs = []
    print("F1 jual pada entri (b)", flush=True)
    for ex in F1_EXITS:
        rows = ab.resim(coins, paths, b_rows, ex) if ex is not ab.BASE_EXIT else [dict(r) for r in b_rows]
        for r in rows:
            r["per"] = ab.period_of(coins[r["i"]].t0)
        cfgs.append(pack("F1", ex["name"], rows))
    print("F2 gelombang kedua", flush=True)
    f2_hits = {k: [] for k in ((p, d, m) for p in (2.0, 3.0) for d in (0.20, 0.35) for m in ("level120", "peak90"))}
    for i, c in enumerate(coins):
        pa = paths[i]
        p0 = gl.price_at_py(pa, 0.0)
        p120 = gl.price_at_py(pa, 120.0)
        if p0 <= 0 or p120 <= 0:
            continue
        for pump, dip, mode in f2_hits:
            ts = second_wave(pa, p0, p120, pump, dip, mode)
            if ts is None:
                continue
            lx = ab.lag_of(3, c.full_i, 120, "3-8")
            f2_hits[(pump, dip, mode)].append((c, ts + lx, lx))
        if i and i % 20000 == 0:
            print(f"  gelombang {i}", flush=True)
    for key, hits in f2_hits.items():
        for ex in F2_EXITS:
            rows = []
            for c, te, lx in hits:
                row = enter_row(c, paths[c.i], te, lx, ex)
                if row is not None:
                    rows.append(row)
            cfgs.append(pack("F2", f"pump {key[0]:g}x turun {key[1]:.0%} reclaim {key[2]} | {ex['name']}", rows))
    print("F3 dev", flush=True)

    def sim_pred(age, pred, feats, label, exit_=ab.BASE_EXIT):
        rows = []
        for i, c in enumerate(coins):
            f = feats.get(i)
            if f is None or not pred(f):
                continue
            lx = ab.lag_of(3, c.full_i, age, "3-8")
            row = enter_row(c, paths[i], age + lx, lx, exit_)
            if row is not None:
                rows.append(row)
        cfgs.append(pack("F3", label, rows))

    for age, feats in ((60, feat60), (120, feat120)):
        sim_pred(age, lambda f: dev_band(f, 0.0, 0.5), feats, f"umur {age} dev beli (0, 0.5) belum jual belum rug")
        sim_pred(age, lambda f: dev_band(f, 0.5, 2.0), feats, f"umur {age} dev beli [0.5, 2) belum jual belum rug")
    sim_pred(120, lambda f: f["dev"] <= 0.05 and f["sold"] == 0 and f["rugs"] < 1 and f["tokens"] == 0, feat120,
             "umur 120 dev<=5% token pertama belum jual")
    sim_pred(120, lambda f: f["dev"] <= 0.10 and f["sold"] == 0 and f["rugs"] < 1, feat120,
             "umur 120 dev<=10% belum jual belum rug")
    print("F4 ukuran trade", flush=True)

    def add_mask(family, name, pred, feats, age):
        rows = []
        for i, c in enumerate(coins):
            f = feats.get(i)
            if f is None or not pred(f):
                continue
            lx = ab.lag_of(3, c.full_i, age, "3-8")
            row = enter_row(c, paths[i], age + lx, lx, ab.BASE_EXIT)
            if row is not None:
                rows.append(row)
        cfgs.append(pack(family, name, rows))

    add_mask("F4", "banyak kecil umur 120", lambda f: tape_ok(f, 120) and f["n_buys"] >= 20 and f["med"] <= 0.5 and f["mx"] <= 0.25 and f["ub"] >= 15, feat120, 120)
    add_mask("F4", "sedikit besar umur 120", lambda f: tape_ok(f, 120) and 5 <= f["n_buys"] <= 15 and f["med"] >= 1.0 and f["mx"] >= 0.30, feat120, 120)
    add_mask("F4", "unik tumbuh umur 120", lambda f: f["uprev"] >= 0 and (f["ub"] - f["uprev"]) >= 10 and f["rate"] >= 1.0 and f["ub"] >= 15, feat120, 120)
    add_mask("F4", "banyak kecil dan unik tumbuh", lambda f: tape_ok(f, 120) and f["n_buys"] >= 20 and f["med"] <= 0.5 and f["mx"] <= 0.25 and f["ub"] >= 15 and f["uprev"] >= 0 and (f["ub"] - f["uprev"]) >= 10, feat120, 120)
    add_mask("F4", "banyak kecil umur 60", lambda f: tape_ok(f, 60) and f["n_buys"] >= 12 and f["med"] <= 0.5 and f["uprev"] >= 0 and (f["ub"] - f["uprev"]) >= 8, feat60, 60)
    print("F5 tanpa jual", flush=True)
    add_mask("F5", "nol jual (60,120] beli>=5", lambda f: tape_ok(f, 120) and f["n_sell_w"] == 0 and f["n_buys_w"] >= 5 and f["dd"] <= 0.35, feat120, 120)
    add_mask("F5", "jual<=10% (60,120] beli>=8", lambda f: tape_ok(f, 120) and f["n_buys_w"] >= 8 and f["sell_share"] <= 0.10 and f["dd"] <= 0.35, feat120, 120)
    add_mask("F5", "nol jual (30,60] beli>=4", lambda f: tape_ok(f, 60) and f["n_sell_w"] == 0 and f["n_buys_w"] >= 4 and f["dd"] <= 0.35, feat60, 60)
    print("F6 jam dan hari", flush=True)
    for lo, hi in ((0, 6), (6, 12), (12, 18), (18, 24)):
        for day, dname in (("all", "semua hari"), ("weekday", "hari kerja"), ("weekend", "akhir pekan")):
            rows = []
            for r in mom_rows:
                hour, weekend = cal(coins[r["i"]].t0)
                if not (lo <= hour < hi):
                    continue
                if day == "weekday" and weekend:
                    continue
                if day == "weekend" and not weekend:
                    continue
                rows.append(r)
            cfgs.append(pack("F6", f"mom120 jam {lo}-{hi} {dname}", rows))
        dev_rows = []
        for i, c in enumerate(coins):
            f = feat120.get(i)
            if f is None or not dev_band(f, 0.5, 2.0):
                continue
            hour = f["hour"]
            if not (lo <= hour < hi):
                continue
            lx = ab.lag_of(3, c.full_i, 120, "3-8")
            row = enter_row(c, paths[i], 120 + lx, lx, ab.BASE_EXIT)
            if row is not None:
                dev_rows.append(row)
        cfgs.append(pack("F6", f"dev beli [0.5, 2) jam {lo}-{hi}", dev_rows))
    print("F7 kurva 70-90", flush=True)
    for pc in (70, 80, 90):
        hits = []
        for i, c in enumerate(coins):
            th = first_curve(paths[i], pc, 120.0)
            if th is None or th < 60:
                continue
            p1 = gl.price_at_py(paths[i], th)
            p0 = gl.price_at_py(paths[i], th - 60.0)
            if p0 <= 0 or p1 < 1.5 * p0:
                continue
            lx = ab.lag_of(4, c.full_i, pc, "3-8")
            hits.append((c, th + lx, lx))
        for ex in F7_EXITS:
            rows = []
            for c, te, lx in hits:
                row = enter_row(c, paths[c.i], te, lx, ex)
                if row is not None:
                    rows.append(row)
            cfgs.append(pack("F7", f"kurva {pc}% umur>=120 momentum 1.5x | {ex['name']}", rows))
        print(f"  kurva {pc} kena {len(hits)}", flush=True)
    print("F8 (b) + anti-rug", flush=True)

    def subset_rows(rows, pred):
        out = []
        for r in rows:
            f = feat120.get(r["i"])
            if f is not None and pred(f):
                out.append(r)
        return out

    cfgs.append(pack("F8", "(b) + P1 jeda 3-8", subset_rows(b_rows, p1_ok)))
    cfgs.append(pack("F8", "(b) + P2 jeda 3-8", subset_rows(b_rows, p2_ok)))
    cfgs.append(pack("F8", "gerbang 12-16 + P1", subset_rows(gate_rows, p1_ok)))
    print("null...", flush=True)
    rng = np.random.default_rng(100)
    real = sum(1 for c in cfgs if passes_ab(c["per"], c["x"]))
    nulls = []
    for s in range(a.null):
        cnt = 0
        for c in cfgs:
            if c["x"].size == 0:
                continue
            perm = rng.permutation(c["x"].size)
            if passes_ab(c["per"], c["x"][perm]):
                cnt += 1
        nulls.append(cnt)
        print(f"  null {s} {cnt}", flush=True)
    k = len(cfgs)
    thr = 0.05 / k if k else None
    nmax = max(nulls) if nulls else 0
    families = ("F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8")
    chosen = []
    for fam in families:
        c = pick(fam, cfgs)
        if c is not None:
            chosen.append(c)
    f1_win = next((c for c in chosen if c["family"] == "F1" and c["role"] == "pilihan A"), None)
    transfer = None
    if f1_win is not None:
        ex = next((e for e in F1_EXITS if e["name"] == f1_win["name"]), ab.BASE_EXIT)
        rows = ab.resim(coins, paths, gate_rows, ex)
        for r in rows:
            r["per"] = ab.period_of(coins[r["i"]].t0)
        transfer = pack("transfer", f"gerbang dengan jual F1: {ex['name']}", rows)
        cfgs.append(transfer)
        # k sudah dikunci sebelum transfer? Transfer dikunci sebagai satu uji tambahan.
        # Hitung ulang k dan null untuk transfer saja supaya Bonferroni mencakupnya.
    if transfer is not None:
        k = len(cfgs)
        thr = 0.05 / k if k else None
        if passes_ab(transfer["per"], transfer["x"]):
            real += 1
        for s in range(a.null):
            perm = rng.permutation(transfer["x"].size) if transfer["x"].size else None
            if perm is not None and passes_ab(transfer["per"], transfer["x"][perm]):
                nulls[s] += 1
        nmax = max(nulls) if nulls else 0
    for c in chosen:
        if c["role"] == "pilihan A":
            c["p"] = boot(c)
        else:
            c["p"] = None
    if transfer is not None:
        transfer["p"] = boot(transfer)
        transfer["role"] = "transfer"
    beat_null = real > nmax

    def protocol(c):
        return (c is not None and c.get("role") == "pilihan A" and ok_nob(c["x"][c["per"] == 1])
                and c.get("p") is not None and thr and c["p"] < thr and beat_null
                and gt1(c["meanB"]) and gt1(c["nobB"]) and c["meanB"] > (gate["meanB"] or 0)
                and (c["nobB"] or 0) > (gate["nobB"] or 0))

    beaters = [c for c in chosen if protocol(c)]
    if transfer is not None and transfer["role"] == "transfer":
        # transfer bukan pilihan A. Syaratnya sama kecuali role.
        if (ok_nob(transfer["x"][transfer["per"] == 1]) and transfer.get("p") is not None and thr
                and transfer["p"] < thr and beat_null and gt1(transfer["meanB"]) and gt1(transfer["nobB"])
                and transfer["meanB"] > (gate["meanB"] or 0) and (transfer["nobB"] or 0) > (gate["nobB"] or 0)):
            beaters.append(transfer)
    fresh_names = []
    for c in beaters:
        st = with_books(c)["segar"]
        if st["n"] >= NMIN and gt1(st["mean"]) and gt1(st["nobest"]):
            fresh_names.append(c["name"])
    if beaters and n_fresh_coins == 0:
        line = ("BELUM LAYAK. Ada pilihan A yang lolos B, null, Bonferroni, dan mengalahkan gerbang pada B, "
                "tetapi tidak ada koin t0 sesudah 10 Nov 07:17 UTC. Ini bukan LAYAK.")
    elif beaters and fresh_names:
        line = "LAYAK sebagai kandidat paper saja, bukan live. Lolos B, koreksi, mengalahkan gerbang, dan irisan segar mengkonfirmasi."
    elif beaters:
        line = "TIDAK LAYAK. Lolos B dan mengalahkan gerbang di data lama, tetapi irisan sesudah 10 Nov 07:17 UTC tidak mengkonfirmasi."
    else:
        line = (f"TIDAK LAYAK. Tidak ada keluarga baru yang lolos protokol dan mengalahkan gerbang (b)+jam 12-16. "
                f"Konfigurasi {k}. Lulus A+B {real}. Null maks {nmax}. Bonferroni {thr}.")
    also = [c for c in cfgs if c.get("role") not in ("pilihan A", "transfer") and passes_ab(c["per"], c["x"])]
    L = ["# Daftar pra-registrasi, ditulis sebelum hasil", "", __doc__.strip(), "",
         "# Vonis", "", line, "",
         "# Keluarga baru dibanding gerbang (b)+jam 12–16, 10 Nov 2026, PAPER", "",
         "Anti-honeypot tidak diuji. Narasi X tidak diukur.",
         f"sha skrip {sha}. Cache `{os.environ.get('CACHE_MATCHED_KEY') or '—'}`.",
         f"Koin standar {meta.get('n_std')}. t0 {meta.get('t_min')} .. {meta.get('t_max')}. Koin segar {n_fresh_coins}.",
         f"Konfigurasi {k}. Lulus A dan B {real}. Null: {', '.join(str(x) for x in nulls)}. Maks {nmax}. Bonferroni {thr}.",
         "Angka gerbang di tabel ini dihitung ulang di run yang sama, bukan disalin dari laporan lama.",
         "",
         "## Perbandingan",
         "",
         "A memilih. B menguji sekali. C tercemar. Segar hanya kalau t0 sesudah 10 Nov 07:17 UTC.",
         "",
         "| Strategi | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8%m1 / DD | 8%m5 / DD | 10%m1 / DD | 10%m5 / DD |",
         "|---|---|---:|---:|---|---:|---|---|---|---|"]
    add_rows(L, "Gerbang lama: (b)+jam 12-16 UTC", gate)
    add_rows(L, "Aturan (b) tanpa jam", raw_b)
    for c in chosen:
        add_rows(L, f"{c['family']} {c['role']}: {c['name']}", c)
    if transfer is not None:
        add_rows(L, "Transfer jual F1 ke entri gerbang", transfer)
    L += ["", "## Pilihan tiap keluarga", ""]
    for c in chosen:
        stB = c["basic"]["B"]
        L.append(f"- {c['family']} ({c['role']}): {c['name']}")
        L.append(f"  A n={c['nA']} rata {fmt_x(c['meanA'])} tanpa terbaik {fmt_x(c['nobA'])}. "
                 f"B n={c['nB']} rata {fmt_x(c['meanB'])} tanpa terbaik {fmt_x(c['nobB'])} menang {fmt_p(stB['win'])}. "
                 f"p B {c.get('p')}.")
        if c["role"] == "pilihan A":
            L.append(f"  Mengalahkan gerbang dan lolos protokol: {'ya' if c in beaters else 'tidak'}.")
    if transfer is not None:
        L.append(f"- Transfer: {transfer['name']}. B n={transfer['nB']} rata {fmt_x(transfer['meanB'])} "
                 f"tanpa terbaik {fmt_x(transfer['nobB'])}. p {transfer.get('p')}.")
    gate_f = with_books(gate)["segar"]
    L += ["", "## Irisan segar dan C", "",
          f"Gerbang pada segar: n={gate_f['n']} rata {fmt_x(gate_f['mean'])} tanpa terbaik {fmt_x(gate_f['nobest'])}.",
          f"Gerbang pada C tercemar: n={gate['basic']['C']['n']} rata {fmt_x(gate['basic']['C']['mean'])} "
          f"tanpa terbaik {fmt_x(gate['basic']['C']['nobest'])}.",
          ""]
    if also:
        L.append(f"Konfigurasi yang lolos A+B tetapi bukan pilihan A: {len(also)}. Mereka tidak menjadi pemenang.")
        for c in also[:12]:
            L.append(f"- {c['family']} {c['name']}: A {fmt_x(c['meanA'])} (n={c['nA']}), B {fmt_x(c['meanB'])} (n={c['nB']}).")
    else:
        L.append("Tidak ada konfigurasi non-pilihan yang lolos A dan B.")
    L += ["", "## Batas", "",
          "- Setel di A, uji di B. C tidak memilih. Segar tidak memilih.",
          "- Jam 12–16 pada aturan (b) tidak dicari ulang.",
          "- Anti-honeypot, mint, freeze, Token-2022, Jupiter, narasi: tidak ada di rekaman.",
          "- Tape wallet putus di 5 menit dan 150 baris. Aturan ukuran trade gagal tertutup kalau cakupan lebih pendek.",
          "- Akhir pekan hanya punya sekitar dua minggu kalender.",
          "- Umur 30 menit dan 1–3 hari tidak dicoba: rekaman sebelumnya kosong di 30 menit.",
          f"- Waktu {time.time() - t0:.0f} dtk.",
          "", "Paper saja.", ""]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write("\n".join(L))
    print(line, flush=True)
    print("tulis", a.out, flush=True)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        traceback.print_exc()
        dest = "riset/riset-strategi-baru-2026-11-10.md"
        argv = sys.argv
        if "--out" in argv:
            dest = argv[argv.index("--out") + 1]
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w") as f:
            f.write("GAGAL sebelum ada hasil.\n\n```\n" + traceback.format_exc() + "```\n")
        raise

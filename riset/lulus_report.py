#!/usr/bin/env python3
"""lulus_report: uji beli koin pump.fun yang baru LULUS ke PumpSwap (data perekam maju lulus.py, sejak 8 Nov 2026).

Aturan ditulis 18 Nov 2026 SEBELUM melihat data harga (pra-registrasi):
  Masuk  : M1 60 dtk setelah terdeteksi lulus; M30 30 menit; M120 2 jam; M360 6 jam.
  Filter : F0 semua; F1 rugcheck bersih (tanpa mint/freeze authority, tanpa danger, top10 <= 30%, insiders 0);
           F2 punya X + website; F3 likuiditas saat masuk >= $20k; F4 beli > jual di 5 menit terakhir;
           F5 (hanya M30/M120/M360) harga saat masuk >= harga pertama terekam (bertahan/naik);
           F6 = F1 + F3; F7 = F3 + F5.
  Keluar : H1, H6, H24, H72 (tahan); X1 TP2x SL30%; X3 trail30% setelah +50% SL40%; X5 TP5x SL50% 72j;
           X6 jual 1/2 di 2x + trail30% 72j.
  Biaya 1,5% per sisi. Harga dicek tiap ~60 dtk (6 jam pertama) lalu tiap 5 menit: stop terisi di harga terlihat.
  Pool hilang / harga 0 / likuiditas < $500 = nilai 0.
  KOREKSI 18 Nov (setelah run pertama, karena bug data, bukan pilih parameter): exit "TP 2x" rata-rata 14x, mustahil;
  DexScreener punya baris harga lonjakan palsu. Perbaikan: buang baris yang harganya > 3x atau < 1/3 median 5
  tetangga, dan isi TP / jual-separuh dibatasi maksimal 1,1 x level target (order limit).
  A/B: paruh waktu pertama / kedua. LULUS: n_B >= 30, rata A > 1, rata B > 1, rata B tanpa koin terbaik > 1.
"""
import argparse
import gzip
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telecall as tc  # noqa: E402

ENTRIES = {"M1": 60, "M30": 1800, "M120": 7200, "M360": 21600}
EXITS = {
    "H1": dict(T=3600), "H6": dict(T=6 * 3600), "H24": dict(T=24 * 3600), "H72": dict(T=72 * 3600),
    "X1 TP2x SL30%": dict(tp=2.0, sl=0.30),
    "X3 trail30% stlh +50% SL40%": dict(arm=1.5, trail=0.30, sl=0.40),
    "X5 TP5x SL50% 72j": dict(tp=5.0, sl=0.50, T=72 * 3600),
    "X6 1/2 di 2x + trail30% 72j": dict(half=2.0, trail=0.30, T=72 * 3600),
}


def sim(series, t_in, ex):
    """Sama dengan telecall.sim, tapi isi TP / jual-separuh dibatasi 1,1 x level."""
    COST = tc.COST
    pts = [x for x in series if x[0] >= t_in]
    if not pts or pts[0][1] <= 0 or pts[0][0] - t_in > 300:
        return None
    t0, p0 = pts[0][0], pts[0][1]
    T = ex.get("T", 24 * 3600)
    held, got, peak, armed, last = 1.0, 0.0, p0, False, p0
    for q in pts[1:]:
        t, p = q[0], q[1]
        if t - t0 > T:
            break
        if p <= 0:
            return got * (1 - COST) * (1 - COST)
        last = p
        r = p / p0
        peak = max(peak, p)
        if ex.get("half") and held == 1.0 and r >= ex["half"]:
            got += 0.5 * min(r, ex["half"] * 1.1)
            held = 0.5
            armed = True
        if ex.get("tp") and r >= ex["tp"]:
            got += held * min(r, ex["tp"] * 1.1)
            held = 0
            break
        if ex.get("arm") and r >= ex["arm"]:
            armed = True
        if ex.get("trail") and armed and p <= peak * (1 - ex["trail"]):
            got += held * r
            held = 0
            break
        if ex.get("sl") and r <= 1 - ex["sl"]:
            got += held * r
            held = 0
            break
    if held:
        got += held * last / p0
    return got * (1 - COST) * (1 - COST)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    d = os.path.join(a.data, "lulus")
    toks = {}
    for line in open(os.path.join(d, "tokens.jsonl")):
        try:
            x = json.loads(line)
            toks[x["mint"]] = x
        except (ValueError, KeyError):
            pass
    px = {}
    t_last = 0
    for fn in sorted(os.listdir(d)):
        if fn.startswith("px-"):
            with gzip.open(os.path.join(d, fn), "rt") as f:
                for line in f:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    t, m, p, liq = r[0], r[1], r[2], r[3]
                    if liq < 500:
                        p = 0.0
                    px.setdefault(m, []).append((t, p, liq, r[6], r[7]))
                    t_last = max(t_last, t)
    n_drop = 0
    for m, v in px.items():
        v.sort()
        keep = []
        for i, q in enumerate(v):
            nb = sorted(z[1] for z in v[max(0, i - 2):i + 3] if z[1] > 0)
            med = nb[len(nb) // 2] if nb else 0
            if q[1] > 0 and med > 0 and (q[1] > 3 * med or q[1] < med / 3):
                n_drop += 1
                continue
            keep.append(q)
        px[m] = keep
    print(f"baris harga lonjakan palsu dibuang: {n_drop:,}")
    seen = sorted(x["t_seen"] for x in toks.values())
    t_split = seen[len(seen) // 2]
    f = lambda t: time.strftime("%d/%m %H:%M", time.gmtime(t))
    print(f"== {len(toks)} koin lulus, {sum(len(v) for v in px.values()):,} baris harga, {f(seen[0])} s/d {f(seen[-1])} UTC, "
          f"data harga terakhir {f(t_last)}; batas A/B {f(t_split)}")
    lags = sorted(x["t_seen"] - x["t_pool"] for x in toks.values() if x.get("t_pool"))
    if lags:
        print(f"   telat deteksi median {lags[len(lags) // 2]:.0f} dtk, p90 {lags[int(len(lags) * .9)]:.0f} dtk")
    # ---- gambaran umum: nasib koin yang punya 72 jam penuh
    full = [m for m, x in toks.items() if x["t_seen"] + 72 * 3600 <= t_last and px.get(m)]
    mx, fin, dead = [], [], 0
    for m in full:
        s = [q for q in px[m] if q[0] >= toks[m]["t_seen"]]
        p0 = next((q[1] for q in s if q[1] > 0), 0)
        if not p0:
            continue
        mx.append(max(q[1] for q in s) / p0)
        fin.append(s[-1][1] / p0)
        dead += s[-1][1] <= 0 or s[-1][1] / p0 < 0.1
    if mx:
        n = len(mx)
        fs = sorted(fin)
        print(f"\n## Nasib {n} koin dengan 72 jam penuh (dari harga pertama terekam): pernah >=2x {sum(x >= 2 for x in mx) / n:.1%}, "
              f">=5x {sum(x >= 5 for x in mx) / n:.1%}, >=10x {sum(x >= 10 for x in mx) / n:.1%}, >=50x {sum(x >= 50 for x in mx) / n:.2%}; "
              f"harga akhir median {fs[n // 2]:.3f}x, rata {sum(fin) / n:.3f}x, akhir >1x {sum(x > 1 for x in fin) / n:.1%}, "
              f"mati/turun >90% {dead / n:.1%}")
    # ---- kejadian masuk
    events = []
    for m, x in toks.items():
        s = px.get(m) or []
        if not s:
            continue
        first = next((q[1] for q in s if q[1] > 0), 0)
        rc, ds = x.get("rc") or {}, x.get("ds") or {}
        clean = bool(rc) and not rc.get("mint_authority") and not rc.get("freeze_authority") and not rc.get("danger") \
            and (rc.get("top10_pct") is not None and rc["top10_pct"] <= 30) and (rc.get("insiders") or 0) == 0
        xweb = bool(ds.get("x")) and bool(ds.get("web"))
        for en, lag in ENTRIES.items():
            t_in = x["t_seen"] + lag
            pts = [q for q in s if q[0] >= t_in]
            if not pts or pts[0][0] - t_in > 300 or pts[0][1] <= 0:
                continue
            q = pts[0]
            events.append({"m": m, "en": en, "t": t_in, "seen": x["t_seen"], "clean": clean, "xweb": xweb,
                           "liq": q[2] >= 20000, "flow": q[3] > q[4], "up": first > 0 and q[1] >= first})
    FILTERS = {
        "F0 semua": lambda e: True, "F1 rugcheck bersih": lambda e: e["clean"], "F2 X+web": lambda e: e["xweb"],
        "F3 liq>=$20k": lambda e: e["liq"], "F4 beli>jual m5": lambda e: e["flow"],
        "F5 harga>=awal": lambda e: e["en"] != "M1" and e["up"], "F6 F1+F3": lambda e: e["clean"] and e["liq"],
        "F7 F3+F5": lambda e: e["en"] != "M1" and e["liq"] and e["up"],
    }
    print(f"\n## TABEL rata x per trade setelah biaya (A -> B). kejadian masuk: "
          f"{ {en: sum(e['en'] == en for e in events) for en in ENTRIES} }")
    passed, allrows = [], []
    for en in ENTRIES:
        for fn, flt in FILTERS.items():
            sel = [e for e in events if e["en"] == en and flt(e)]
            if not sel:
                continue
            for xn, ex in EXITS.items():
                T = ex.get("T", 24 * 3600)
                A, B = [], []
                for e in sel:
                    if e["t"] + T > t_last:
                        continue
                    r = sim(px[e["m"]], e["t"], ex)
                    if r is None:
                        continue
                    (A if e["seen"] < t_split else B).append(r)
                if len(A) + len(B) < 10:
                    continue
                ma = sum(A) / len(A) if A else 0
                mb = sum(B) / len(B) if B else 0
                nb = (sum(B) - max(B)) / (len(B) - 1) if len(B) > 1 else 0
                ok = len(B) >= 30 and ma > 1 and mb > 1 and nb > 1
                allrows.append((en, fn, xn, A, B, ma, mb, nb, ok))
                if ok:
                    passed.append(f"{en} | {fn} | {xn}")
                print(f"  {en:5s} {fn:20s} {xn:28s} A {ma:6.3f}x n={len(A):5d} | B {mb:6.3f}x n={len(B):5d} tanpa-terbaik {nb:6.3f}"
                      f"{'  <== LULUS' if ok else ''}")
    print(f"\n## LULUS: {len(passed)} dari {len(allrows)}: {passed}")
    print(f"## untung di A dan B (n_B>=30): {sum(1 for r in allrows if r[5] > 1 and r[6] > 1 and len(r[4]) >= 30)}; "
          f"dan tetap >1 tanpa koin terbaik: {len(passed)}")
    print("\n## Simulasi $200 (10% per trade, urut waktu), paruh B saja:")
    show = [r for r in allrows if r[1] == "F0 semua"] + sorted([r for r in allrows if len(r[4]) >= 30], key=lambda r: -r[6])[:8]
    for en, fn, xn, A, B, ma, mb, nb, ok in show:
        if not B:
            continue
        srt = sorted(B)
        k = sum(x > 1 for x in B)
        lo, hi = tc.wilson(k, len(B))
        print(f"  {en} | {fn} | {xn}: n={len(B)} rata {mb:.3f}x median {srt[len(B) // 2]:.3f}x menang {k / len(B):.0%} "
              f"[{lo:.0%}-{hi:.0%}] $200 -> ${tc.bank(B, 200, 0.10):,.0f}")


if __name__ == "__main__":
    main()

"""Gabungkan hasil grid per keluarga dan uji holdout menjadi satu laporan. PAPER."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import grid_luas as gl


def load_tree(root):
    hold = None
    parts = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            path = os.path.join(dirpath, fn)
            if fn == "holdout.json":
                with open(path) as f:
                    hold = json.load(f)
            elif fn == "grid_luas_result.json":
                with open(path) as f:
                    parts.append(json.load(f))
    if hold is None or not parts:
        raise SystemExit(f"Butuh holdout.json dan minimal satu grid_luas_result.json di {root}")
    return hold, parts


def merge(parts):
    nulls = None
    real = 0
    combos, pass_by, null_by = {}, {}, {}
    top, desc, fam_rows = [], [], []
    meta = None
    secs = 0.0
    for p in parts:
        real += int(p["real_pass"])
        n = p.get("null") or []
        if nulls is None:
            nulls = [0] * len(n)
        for i, v in enumerate(n):
            nulls[i] += int(v)
        combos.update(p.get("combos") or {})
        pass_by.update(p.get("pass_by") or {})
        for fam, arr in (p.get("null_by") or {}).items():
            null_by[fam] = arr
        top.extend(p.get("top5") or [])
        desc.extend(p.get("top10") or [])
        fam_rows.extend(p.get("per_family") or [])
        secs += float(p.get("secs") or 0)
        if meta is None or (p.get("meta") or {}).get("n_used", 0) > (meta or {}).get("n_used", 0):
            meta = p.get("meta") or meta
    top.sort(key=lambda r: (r.get("A") or {}).get("mean") or -1, reverse=True)
    picked, seen = [], set()
    for r in top:
        A = r.get("A") or {}
        sig = (r.get("name"), r.get("filt"), A.get("n"), round(A.get("mean") or 0, 5))
        if sig in seen:
            continue
        seen.add(sig)
        picked.append(r)
        if len(picked) >= 5:
            break
    desc.sort(key=lambda r: r.get("nobest_rank") or -1, reverse=True)
    dsel, dseen = [], set()
    for r in desc:
        C = r.get("C") or {}
        sig = (r.get("name"), r.get("filt"), C.get("n"), round(C.get("nobest") or 0, 5))
        if sig in dseen:
            continue
        dseen.add(sig)
        dsel.append(r)
        if len(dsel) >= 10:
            break
    k = int(sum(combos.values()))
    k_c = sum(1 for r in picked if r.get("tested_c"))
    return dict(real_pass=real, null=nulls or [], null_by=null_by, pass_by=pass_by, combos=combos,
                k_combo=k, k_c=k_c, bonferroni_full=(0.05 / k) if k else None,
                bonferroni_c=(0.05 / k_c) if k_c else None,
                top5=picked, top10=dsel, per_family=fam_rows, secs_eval=secs, secs=secs, meta=meta or {})


def holdout_fails(rule):
    c = (rule.get("slices") or {}).get("C") or {}
    return not (c.get("n", 0) >= 30 and (c.get("mean") or 0) > 1 and (c.get("nobest") or 0) > 1)


def opening(R, hold):
    grid = gl.build_report(R).splitlines()[0]
    failed = [r for r in hold["rules"] if holdout_fails(r)]
    if len(failed) == len(hold["rules"]):
        return ("TIDAK LAYAK. Empat aturan yang dikunci dari sampel 30.000 gagal di holdout "
                "(koin yang tidak masuk sampel itu): di irisan C, n<30 atau rata ≤1 atau rata tanpa koin terbaik ≤1. "
                + grid)
    names = ", ".join(r["key"] for r in hold["rules"] if not holdout_fails(r))
    return (f"BELUM LAYAK DIPAKAI. Di holdout, aturan {names} masih rata di atas 1 di C setelah buang koin terbaik, "
            f"tetapi ini satu uji terkunci, bukan izin live. {grid}")


def holdout_md(hold):
    meta = hold["meta"]
    L = ["## Holdout: koin di luar sampel 30.000",
         "",
         "Aturan dikunci sebelum uji ini. Tidak ada ambang yang digeser. "
         "Pembagian A/B/C 50/20/30 dihitung ulang hanya pada koin holdout, urut waktu lahir.",
         f"- Koin standar: {meta.get('n_std')}. Sampel lama: {meta.get('n_sample')}. Holdout: {meta.get('n_hold')}.",
         f"- A/B/C holdout: {meta.get('nA')}/{meta.get('nB')}/{meta.get('nC')}.",
         f"- Periode holdout: {gl.fmt_t(meta.get('t_first'))} – {gl.fmt_t(meta.get('t_last'))}.",
         f"- Potongan: {gl.fmt_t(meta.get('cut1'))} / {gl.fmt_t(meta.get('cut2'))}.",
         "- Riwayat wallet pintar dihitung dulu pada semua koin standar, baru koin sampel dibuang dari skor.",
         "",
         "| Aturan | Irisan | n | Rata | Menang (Wilson) | Tanpa terbaik | $200 8% maks1 | 8% maks5 | 10% maks1 | 10% maks5 |",
         "|---|---|---:|---:|---|---:|---:|---:|---:|---:|"]
    for rule in hold["rules"]:
        L.append(f"| {rule['judul']} | | | | | | | | | |")
        L.append(f"| {rule['teks']} | | | | | | | | | |")
        for lab in ("A", "B", "C"):
            d = rule["slices"][lab]
            w = d.get("wilson") or [0, 0]
            sim = d.get("sim") or {}

            def money(k):
                v = sim.get(k)
                return "—" if not v else f"${v[0]:.0f} ({v[1]})"

            if not d.get("n"):
                L.append(f"| | {lab} | 0 | — | — | — | — | — | — | — |")
                continue
            L.append(f"| | {lab} | {d['n']} | {gl.fmt_x(d.get('mean'))} | "
                     f"{gl.fmt_n((d.get('win') or 0) * 100)}% [{gl.fmt_n(w[0] * 100)}–{gl.fmt_n(w[1] * 100)}%] | "
                     f"{gl.fmt_x(d.get('nobest'))} | {money('8% maks1')} | {money('8% maks5')} | "
                     f"{money('10% maks1')} | {money('10% maks5')} |")
        L.append(f"| | gagal syarat C | {'ya' if holdout_fails(rule) else 'tidak'} | | | | | | | |")
    L += ["",
          "Syarat gagal di C: n<30, atau rata ≤1, atau rata tanpa koin terbaik ≤1. "
          "Simulasi $200 memakai kelipatan bersih urut waktu pada irisan itu saja.",
          ""]
    return "\n".join(L)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "hasil"
    dest = sys.argv[2] if len(sys.argv) > 2 else "riset/riset-grid-full-2026-11-10.md"
    hold, parts = load_tree(root)
    R = merge(parts)
    body = gl.build_report(R)
    lines = body.splitlines()
    lines[0] = opening(R, hold)
    lines[2] = "# Riset grid penuh (semua koin standar) + holdout di luar sampel, 10 Nov 2026, PAPER"
    text = "\n".join(lines) + "\n\n" + holdout_md(hold)
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w") as f:
        f.write(text)
    print(text, flush=True)


if __name__ == "__main__":
    main()

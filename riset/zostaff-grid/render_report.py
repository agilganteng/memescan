"""Ubah zgrid_result.json jadi laporan markdown. Tidak mengubah hitungan zgrid."""
import json
import sys
import time


def num(x, nd=3):
    if x is None or isinstance(x, str):
        return "—" if x is None else str(x)
    try:
        if x != x:
            return "—"
    except Exception:
        return str(x)
    return f"{float(x):.{nd}f}".replace(".", ",")


def tstr(ts):
    if not ts:
        return "—"
    return time.strftime("%d %b %Y %H:%M UTC", time.gmtime(ts))


def block(name, d):
    if d is None:
        return f"{name}: —"
    if isinstance(d, str):
        return f"{name}: {d}"
    n = int(d.get("n") or 0)
    w = d.get("wilson") or [None, None]
    return (f"{name}: n={n} rata {num(d.get('mean'))}x median {num(d.get('median'))}x "
            f"menang {num((d.get('win') or 0) * 100, 1)}% "
            f"Wilson [{num((w[0] or 0) * 100, 1)}–{num((w[1] or 0) * 100, 1)}%] "
            f"tanpa terbaik {num(d.get('nobest'))}x")


def simline(d):
    if not isinstance(d, dict):
        return ""
    sim = d.get("sim") or {}
    if not sim:
        return ""
    bits = []
    for k, v in sim.items():
        if isinstance(v, (list, tuple)) and v:
            eq = v[0]
            nt = v[1] if len(v) > 1 else "?"
            bits.append(f"{k}: ${num(eq, 2)} ({nt} trade)")
    return "sim $200 " + "; ".join(bits) if bits else ""


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "out/zgrid_result.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "out/zgrid_report.md"
    with open(src) as f:
        R = json.load(f)
    nulls = R.get("null") or []
    nmean = sum(nulls) / len(nulls) if nulls else float("nan")
    nmax = max(nulls) if nulls else float("nan")
    passed = R.get("real_pass")
    combos = R.get("combos")
    top = R.get("top5") or []
    n_final = 0
    for row in top:
        c = row.get("C")
        if isinstance(c, dict) and (c.get("mean") or 0) > 1 and (c.get("nobest") or 0) > 1 and (c.get("n") or 0) >= 30:
            b = row.get("B")
            a = row.get("A")
            if isinstance(b, dict) and isinstance(a, dict) and (b.get("mean") or 0) > 1 and (a.get("mean") or 0) > 1:
                n_final += 1
    beat = isinstance(passed, (int, float)) and nulls and passed > nmean
    if n_final and beat and passed > nmax:
        line1 = (f"LIHAT ANGKA. zgrid menemukan {n_final} baris top-5 yang lolos A/B/C, "
                 f"dan jumlah lulus {passed} di atas null maks {num(nmax, 1)}. "
                 f"Ini belum koreksi Bonferroni penuh atas {combos} kombinasi.")
    else:
        line1 = (f"TIDAK LAYAK. Dari {combos} kombinasi, lulus {passed}; "
                 f"null rata-rata {num(nmean, 2)} (maks {num(nmax, 1)}). "
                 f"Finalis A→B→C di top 5: {n_final}.")
    lines = [line1, "", "# Grid zostaff (zgrid.py, file tidak diubah), PAPER", "",
             "## Data",
             f"- Koin standar yang diuji: {R.get('N')} dari {R.get('n_all')} rekaman berisi wallet.",
             f"- Periode t0: {tstr(R.get('t_first'))} – {tstr(R.get('t_last'))}.",
             f"- Potongan A/B/C: {tstr(R.get('cut1'))} / {tstr(R.get('cut2'))}.",
             f"- n A/B/C: {R.get('nA')}/{R.get('nB')}/{R.get('nC')}.",
             f"- Dev-buy ≥0,5 SOL: {num((R.get('devbuy_share') or {}).get('0.5', (R.get('devbuy_share') or {}).get(0.5)), 3)} bagian koin.",
             "",
             "## Hitung",
             f"- Kombinasi: {combos}. Lulus syarat (n_C≥30, A,B,C>1, C tanpa terbaik >1): {passed}.",
             f"- Kandidat A,B,C>1 dan n_C≥30 (sebelum buang koin terbaik): {R.get('real_cand')}. A dan B >1: {R.get('real_ab')}.",
             f"- Null ({len(nulls)} acak): {', '.join(str(int(x)) for x in nulls) if nulls else '—'}.",
             f"- Rata null {num(nmean, 2)}, maks {num(nmax, 1)}.",
             f"- Waktu jalan: {num(R.get('secs'), 0)} detik.",
             "",
             "## Top 5 menurut A",
             "C diuji hanya kalau B>1. Skrip ini tidak mengulang seleksi; angka diambil dari JSON zgrid.",
             ""]
    for i, row in enumerate(top, 1):
        lines.append(f"### {i}. {row.get('fam')} | {row.get('filt')} | {row.get('exit')}")
        lines.append(f"- {block('A', row.get('A'))}")
        lines.append(f"- {block('B', row.get('B'))}")
        lines.append(f"- {block('C', row.get('C'))}")
        c = row.get("C")
        if isinstance(c, dict):
            if c.get("p_boot") is not None:
                lines.append(f"- p bootstrap C: {num(c.get('p_boot'), 4)}")
            s = simline(c)
            if s:
                lines.append(f"- {s}")
        lines.append("")
    lines.append("## Lulus yang kebetulan berlabel copy min5 wr≥50% (kalau ada)")
    lines.append("")
    pdet = R.get("passdetail") or []
    if not pdet:
        lines.append("Tidak ada.")
    for row in pdet[:12]:
        lines.append(f"- {row.get('fam')} | {row.get('filt')} | {row.get('exit')}: {block('A', row.get('A'))}; {block('B', row.get('B'))}; {block('C', row.get('C'))}")
        c = row.get("C")
        if isinstance(c, dict):
            s = simline(c)
            if s:
                lines.append(f"  {s}")
    lines.append("")
    lines.append("## Keluarga terbaik di A")
    lines.append("")
    for name, row in (R.get("topfam") or {}).items():
        lines.append(f"- {name}: {row.get('fam')} | {row.get('filt')} | {row.get('exit')}; {block('A', row.get('A'))}; {block('B', row.get('B'))}; {block('C', row.get('C'))}")
    lines.append("")
    lines.append("Paper saja. zgrid.py tidak diubah. Perekam GitHub tidak menyimpan signature; zgrid tidak mendedupe trade di dalam skrip.")
    text = "\n".join(lines) + "\n"
    with open(dst, "w") as f:
        f.write(text)
    print(text, flush=True)


if __name__ == "__main__":
    main()

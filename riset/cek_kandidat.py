"""Bedah koin yang lolos kandidat trailing stop #1 (umur 45 dtk, inflow_rate <= 0.01087, growth >= 1.153):
apakah polanya nyata atau cuma data aneh (event terlewat, kurva tidak standar)."""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import memescan as ms  # noqa: E402

F = ms.FEATURES
i_ir, i_g, i_in = F.index("inflow_rate"), F.index("growth"), F.index("inflow_sol")
i_ub, i_h, i_dev, i_bsr = F.index("unique_buyers"), F.index("holders"), F.index("dev_pct"), F.index("buy_sell_ratio")
hit, n_all, m0s = [], 0, collections.Counter()
d = os.path.join(sys.argv[1], "rec")
for fn in sorted(os.listdir(d)):
    for line in open(os.path.join(d, fn)):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        s = next((x for x in r["snaps"] if x[0] == 45), None)
        if not s:
            continue
        n_all += 1
        f = s[2:]
        m0s[round(r.get("m0", 0))] += 1
        if f[i_ir] <= 0.01087 and f[i_g] >= 1.153:
            hit.append((r["s"], r.get("m0"), s[1], f[i_in], f[i_g], f[i_ub], f[i_h], f[i_dev], f[i_bsr], r.get("why"), r["end"]))
print(f"koin dengan foto umur 45 dtk: {n_all:,}; lolos aturan: {len(hit):,} ({len(hit) / max(1, n_all):.2%})")
print("mcap awal (m0, SOL) semua koin, 8 terbanyak:", m0s.most_common(8))
print("\nlolos aturan: simbol | mcap awal | mcap umur 45 dtk | inflow SOL | growth | pembeli unik | holder | dev% | rasio beli | alasan selesai | umur akhir")
for h in hit[:40]:
    print("  ", " | ".join(str(x) for x in h))
c = collections.Counter(round(h[1] or 0) for h in hit)
print("\nmcap awal koin yang lolos:", c.most_common(8))
print("rata pembeli unik:", sum(h[5] for h in hit) / max(1, len(hit)), "rata inflow:", sum(h[3] for h in hit) / max(1, len(hit)))

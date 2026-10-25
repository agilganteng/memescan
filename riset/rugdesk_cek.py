"""Cek data rugdesk: apakah harga 0 ('pool hilang') itu nyata atau cuma token yang tidak ikut terbawa
di jawaban DexScreener untuk 30 alamat sekaligus."""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rugdesk as rd  # noqa: E402

leads, px = rd.load_all(sys.argv[1] if len(sys.argv) > 1 else "data")
zero_then_back = zero_end = never = 0
per_t = collections.Counter()
for mint, s in px.items():
    z = [i for i, x in enumerate(s) if x[1] <= 0]
    if not z:
        continue
    for i in z:
        per_t[s[i][0]] += 1
    if len(z) == len(s):
        never += 1
    elif any(s[i][1] > 0 for i in range(z[0], len(s))):
        zero_then_back += 1
    else:
        zero_end += 1
print(f"token dengan harga: {len(px)}; ada harga 0 lalu muncul lagi: {zero_then_back}; 0 sampai akhir: {zero_end}; selalu 0: {never}")
rows = collections.Counter(x[0] for s in px.values() for x in s)
print("contoh menit: jumlah token / yang 0:", [(rows[t], per_t[t]) for t in sorted(rows)[-10:]])
for mint, x in list(leads.items())[:12]:
    s = px.get(mint, [])
    print(x["verdict"], (x.get("pool") or {}).get("dex"), (x.get("pool") or {}).get("liq_usd"),
          "harga awal", s[0][1] if s else None, "akhir", s[-1][1] if s else None, "n", len(s))

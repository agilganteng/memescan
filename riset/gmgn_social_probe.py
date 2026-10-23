"""Cari di repo resmi GMGNAI/gmgn-skills apakah OpenAPI GMGN punya endpoint data X/Twitter
(social tracking). Hanya baca kode publik, tanpa API key."""
import os
import re
import subprocess

d = "/tmp/gmgn-skills"
subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/GMGNAI/gmgn-skills", d], check=True)
files = [os.path.join(r, f) for r, _, fs in os.walk(d) if ".git" not in r for f in fs]
print("== file:", len(files))
for f in sorted(files):
    print("  ", f[len(d) + 1:])
print("\n== endpoint / path API yang disebut")
paths = set()
for f in files:
    try:
        t = open(f, encoding="utf-8", errors="replace").read()
    except OSError:
        continue
    paths |= set(re.findall(r"/(?:v\d|defi|api)/[A-Za-z0-9_/{}\-]+", t))
for p in sorted(paths):
    print("  ", p)
print("\n== baris yang menyebut twitter / x tracker / social / kol / callout")
for f in files:
    for i, line in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
        if re.search(r"twitter|x[_ -]?tracker|social|\bkol\b|callout|tweet", line, re.I):
            print(f"  {f[len(d) + 1:]}:{i}: {line.strip()[:180]}")

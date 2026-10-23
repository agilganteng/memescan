"""Baca dokumentasi lengkap GMGN Agent API / OpenAPI (versi markdown) untuk melihat endpoint apa
saja yang tersedia, terutama data X/Twitter (social tracking). Hanya baca."""
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=25) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"GAGAL {type(e).__name__}: {e}"


llms = get("https://docs.gmgn.ai/llms.txt")
print("===== llms.txt (baris yang menyebut api/agent/twitter/x tracker)")
for line in llms.splitlines():
    if re.search(r"api|agent|twitter|x tracker|social|openapi|skill", line, re.I):
        print(" ", line[:200])
for slug in ["gmgn-agent-api", "x-tracker"]:
    md = get(f"https://docs.gmgn.ai/index/{slug}.md")
    print(f"\n===== {slug}.md ({len(md)} char)\n{md[:9000]}")
for u in ["https://gmgn.ai/ai", "https://github.com/GMGNAI", "https://api.github.com/orgs/GMGNAI/repos", "https://api.github.com/search/repositories?q=gmgn+agent+api"]:
    b = get(u)
    print(f"\n===== {u}\n{b[:2500] if 'api.github.com' in u else re.sub(r'<[^>]+>', ' ', b)[:800]}")

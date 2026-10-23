"""Baca halaman dokumentasi GMGN tentang API (whitelist IP, agent API, callout OpenAPI) dan cek
apakah halaman web GMGN (di browser asli) memanggil API data yang lolos Cloudflare. Hanya baca."""
import html
import re
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
for slug in ["cooperation-api-data-crawling-ip-whitelist", "gmgn-agent-api", "gmgn-callout-openapi"]:
    with urllib.request.urlopen(urllib.request.Request(f"https://docs.gmgn.ai/index/{slug}", headers=UA), timeout=20) as r:
        b = r.read().decode("utf-8", "replace")
    b = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", b, flags=re.S)
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b)))
    i = t.find("Powered by")
    print(f"\n===== {slug}\n{t[:3500]}")

from playwright.sync_api import sync_playwright  # noqa: E402
print("\n===== panggilan API dari halaman GMGN di browser")
with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    pg = br.new_page(user_agent=UA["User-Agent"])
    seen = []
    pg.on("response", lambda r: seen.append((r.status, r.url)) if "gmgn.ai/" in r.url and ("/api/" in r.url or "/defi/" in r.url or "/vas/" in r.url) else None)
    for u in ["https://gmgn.ai/?chain=sol", "https://gmgn.ai/follow?chain=sol&tab=social"]:
        try:
            pg.goto(u, timeout=45000)
            pg.wait_for_timeout(15000)
            print(f"  {u}: judul={pg.title()!r}")
            print("   teks:", re.sub(r"\s+", " ", pg.inner_text("body"))[:600])
        except Exception as e:  # noqa: BLE001
            print(f"  {u}: gagal {type(e).__name__}")
    for s, u in seen[:40]:
        print(f"  {s} {u[:150]}")
    br.close()

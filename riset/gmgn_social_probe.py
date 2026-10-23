"""Cek jalur supaya bot bisa membaca social tracking GMGN (update X tentang token):
1) dokumentasi/API resmi GMGN, 2) browser asli (Playwright Chromium) lewat Cloudflare,
3) nitter (cermin X) untuk pencarian twit tentang token. Hanya baca, tanpa login."""
import re
import sys
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}


def get(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


print("== 1. API / dokumentasi resmi GMGN")
for u in ["https://docs.gmgn.ai/", "https://docs.gmgn.ai/index/cooperation-api-integrate-gmgn-solana-trading-api",
          "https://gmgn.ai/api", "https://openapi.gmgn.ai/"]:
    c, b = get(u)
    title = re.search(r"<title>(.*?)</title>", b, re.S)
    print(f"  {u:<80} HTTP {c} {title.group(1).strip()[:80] if title else b[:100]!r}")
c, b = get("https://docs.gmgn.ai/")
links = sorted(set(re.findall(r'href="(/[^"#]+)"', b)))
print("  isi menu dokumentasi:", ", ".join(links[:60]))

print("\n== 3. nitter (cermin X)")
for q in ["pumpfun", "%24BONK", "pump.fun%20CA"]:
    c, b = get(f"https://nitter.net/search?f=tweets&q={q}")
    tweets = re.findall(r'class="tweet-content[^"]*"[^>]*>(.*?)</div>', b, re.S)
    print(f"  q={q:<16} HTTP {c}, {len(tweets)} twit" + (f"; contoh: {re.sub('<[^>]+>', '', tweets[0])[:120]!r}" if tweets else f"; awal halaman: {b[:150]!r}"))

print("\n== 2. browser asli (Playwright Chromium) ke GMGN")
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("  playwright tidak terpasang")
    sys.exit(0)
with sync_playwright() as p:
    br = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    pg = br.new_page(user_agent=UA["User-Agent"])
    for u in ["https://gmgn.ai/?chain=sol", "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps/1h?orderby=swaps&direction=desc"]:
        try:
            r = pg.goto(u, timeout=45000)
            pg.wait_for_timeout(12000)
            txt = pg.content()
            print(f"  {u[:70]:<70} HTTP {r.status if r else '?'} judul={pg.title()!r} panjang={len(txt)} awal={pg.inner_text('body')[:150]!r}")
        except Exception as e:  # noqa: BLE001
            print(f"  {u[:70]:<70} gagal {type(e).__name__}: {str(e)[:120]}")
    br.close()

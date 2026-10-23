"""Cek apakah GMGN dan fomo (web dan API publiknya) bisa diakses dari GitHub Actions. Hanya baca, tanpa login."""
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept": "application/json, text/html"}
URLS = [
    ("gmgn.ai (web)", "https://gmgn.ai/"),
    ("trending koin SOL", "https://gmgn.ai/defi/quotation/v1/rank/sol/swaps/1h?orderby=swaps&direction=desc"),
    ("info token (BONK)", "https://gmgn.ai/defi/quotation/v1/tokens/sol/DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"),
    ("wallet top trader", "https://gmgn.ai/defi/quotation/v1/rank/sol/wallets/7d?orderby=pnl_7d&direction=desc"),
    ("pump.fun baru", "https://gmgn.ai/defi/quotation/v1/rank/sol/pump?limit=5&orderby=created_timestamp&direction=desc"),
    ("fomo.family (web)", "https://fomo.family/"),
    ("fomo api", "https://api.fomo.family/"),
    ("copyfomo.com", "https://copyfomo.com/"),
    ("copyfomo.app", "https://copyfomo.app/"),
]
for name, url in URLS:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            body = r.read()
            print(f"{name:<22} HTTP {r.status} {len(body)} byte: {body[:160]!r}")
    except urllib.error.HTTPError as e:
        print(f"{name:<22} HTTP {e.code} {e.read()[:160]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"{name:<22} gagal {type(e).__name__}: {e}")

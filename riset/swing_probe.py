"""Cek sumber data harga multi-hari dari GitHub Actions (7 Nov 2026): pump.fun frontend API, GeckoTerminal, DexScreener."""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 memescan-riset", "Accept": "application/json"}


def get(url):
    t = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25) as r:
            b = r.read()
            return r.status, b, time.time() - t
    except Exception as e:  # noqa: BLE001
        return getattr(e, "code", str(e)[:120]), b"", time.time() - t


urls = [
    "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=created_timestamp&order=DESC&includeNsfw=true&complete=true",
    "https://frontend-api-v3.pump.fun/coins?offset=5000&limit=5&sort=created_timestamp&order=DESC&includeNsfw=true&complete=true",
    "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=last_trade_timestamp&order=DESC&includeNsfw=true",
    "https://api.geckoterminal.com/api/v2/networks/solana/tokens/multi/DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "https://api.dexscreener.com/latest/dex/tokens/DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
]
for u in urls:
    s, b, dt = get(u)
    print(f"{s} {dt:.1f}s {u[:110]}\n   {b[:600]!r}\n")
# GeckoTerminal OHLCV untuk pool BONK teratas
s, b, dt = get(urls[3])
try:
    pool = json.loads(b)["data"][0]["relationships"]["top_pools"]["data"][0]["id"].split("_", 1)[1]
    for tf in ("minute?aggregate=15", "hour?aggregate=1"):
        u = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/{tf}&limit=1000&before_timestamp={int(time.time()) - 200 * 86400}"
        s, b, dt = get(u)
        d = json.loads(b) if s == 200 else {}
        l = d.get("data", {}).get("attributes", {}).get("ohlcv_list", [])
        print(f"OHLCV {tf}: {s} {len(l)} candle, {l[-1] if l else ''} .. {l[0] if l else ''}")
except Exception as e:  # noqa: BLE001
    print("gecko parse gagal", e)

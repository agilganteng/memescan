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
# GeckoTerminal OHLCV untuk pool BONK teratas, berbagai jarak waktu
s, b, dt = get(urls[3])
pool = json.loads(b)["data"][0]["relationships"]["top_pools"]["data"][0]["id"].split("_", 1)[1]
for tf in ("minute?aggregate=15", "hour?aggregate=1", "day?aggregate=1"):
    for back in (None, 3, 20, 60, 150):
        q = f"&before_timestamp={int(time.time()) - back * 86400}" if back else ""
        u = f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/{tf}&limit=1000{q}"
        s, b, dt = get(u)
        l = json.loads(b).get("data", {}).get("attributes", {}).get("ohlcv_list", []) if s == 200 else []
        print(f"OHLCV {tf} mundur {back} hari: {s} {len(l)} candle, terlama {time.strftime('%Y-%m-%d', time.gmtime(l[-1][0])) if l else ''} {b[:150] if s != 200 else ''}")
        time.sleep(2.5)

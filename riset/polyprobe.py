"""Probe sekali: format pasar Polymarket crypto Up/Down 5 menit + histori harga (API publik, tanpa key)."""
import json
import time
import urllib.parse
import urllib.request

G = "https://gamma-api.polymarket.com"
C = "https://clob.polymarket.com"


def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as r:
            return json.load(r)
    except Exception as e:  # noqa: BLE001
        return {"ERR": str(e)}


now = int(time.time())
base = now - now % 300 - 3600


def ev(coin, t):
    e = get(f"{G}/events?slug={coin}-updown-5m-{t}")
    return e[0] if isinstance(e, list) and e else None


e = ev("btc", base)
print("DESC NOW:", e["description"])
m = e["markets"][0]
print("MARKET KEYS:", sorted(m.keys()))
print({k: m.get(k) for k in ("outcomes", "outcomePrices", "clobTokenIds", "eventStartTime", "startDate", "endDate", "feesEnabled",
                             "takerBaseFee", "makerBaseFee", "feeSchedule", "feeType", "orderMinSize", "orderPriceMinTickSize",
                             "volumeNum", "liquidityNum", "spread", "bestBid", "bestAsk", "lastTradePrice", "umaResolutionStatus")})
tok = json.loads(m["clobTokenIds"])
for fid in (1,):
    h = get(f"{C}/prices-history?market={tok[0]}&startTs={base-900}&endTs={base+600}&fidelity={fid}")
    print("HIST fid", fid, json.dumps(h)[:2500])
h = get(f"{C}/prices-history?market={tok[0]}&interval=max&fidelity=1")
print("HIST max", json.dumps(h)[:800])
# kapan TWAP mulai dipakai + histori pasar lama
for days in (2, 7, 14, 30, 45, 60, 90, 120, 150, 180, 210, 240):
    t = base - days * 86400
    x = ev("btc", t)
    if not x:
        print(days, "hari lalu: tidak ada")
        continue
    mm = x["markets"][0]
    tk = json.loads(mm["clobTokenIds"])
    hh = get(f"{C}/prices-history?market={tk[0]}&startTs={t-900}&endTs={t+600}&fidelity=1")
    n = len(hh.get("history", [])) if isinstance(hh, dict) else hh
    print(days, "hari lalu:", "TWAP" if "TWAP" in x["description"] else "start/end", mm.get("outcomePrices"), "vol", mm.get("volumeNum"),
          "hist", n, json.dumps(hh)[:300])

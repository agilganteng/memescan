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
for coin in ("btc", "eth", "sol", "xrp"):
    for fmt in ("{c}-updown-5m-{t}", "{c}-up-or-down-5m-{t}"):
        slug = fmt.format(c=coin, t=base)
        m = get(f"{G}/markets?slug={slug}")
        print(slug, "->", json.dumps(m)[:600])
        e = get(f"{G}/events?slug={slug}")
        print("  event ->", json.dumps(e)[:300])
s = get(f"{G}/public-search?q=" + urllib.parse.quote("Bitcoin Up or Down 5") + "&limit_per_type=5")
print("search ->", json.dumps(s)[:1500])
m = get(f"{G}/markets?slug=btc-updown-5m-{base}")
if isinstance(m, list) and m:
    tok = json.loads(m[0]["clobTokenIds"])
    print("outcomes", m[0].get("outcomes"), "prices", m[0].get("outcomePrices"), "start", m[0].get("startDate"), m[0].get("eventStartTime"))
    for fid in (1,):
        h = get(f"{C}/prices-history?market={tok[0]}&startTs={base-900}&endTs={base+600}&fidelity={fid}")
        print("history", json.dumps(h)[:1500])
    # tanggal pasar 5 menit pertama
    for days in (30, 90, 180, 270):
        t = base - days * 86400
        mm = get(f"{G}/markets?slug=btc-updown-5m-{t}")
        print(days, "hari lalu:", "ada" if isinstance(mm, list) and mm else "tidak", str(mm)[:120])
    print("fee:", {k: m[0].get(k) for k in ("feesEnabled", "takerBaseFee", "makerBaseFee", "feeSchedule", "orderMinSize", "liquidityNum", "volumeNum", "spread")})

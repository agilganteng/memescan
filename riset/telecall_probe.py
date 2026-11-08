"""Cek sekali dari GitHub Actions: sumber callout mana yang bisa dibaca tanpa login."""
import os, re, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telecall import SEEDS, http, UA_HTML, UA_JSON, parse_channel, cas_in, tg_names

print("== Telegram t.me/s")
found = set()
for s in SEEDS:
    try:
        page = http(f"https://t.me/s/{s}", UA_HTML, as_json=False)
        msgs = parse_channel(page) if page else []
        n = sum(1 for m in msgs if cas_in(m))
        last = max((m["t"] or 0) for m in msgs) if msgs else 0
        for m in msgs:
            found |= tg_names(m)
        print(f"  {s:28s} post {len(msgs):3d} ber-CA {n:3d} post terakhir {time.strftime('%d/%m %H:%M', time.gmtime(last)) if last else '-'}")
    except Exception as e:
        print(f"  {s:28s} ERR {e}")
    time.sleep(0.5)
print("  channel lain yang disebut:", sorted(found)[:80])

handles = [l.split()[1] for l in open(os.path.join(os.path.dirname(__file__), "kol_wallets.txt")) if l.strip() and not l.startswith("#")][:6]
print("== X lewat mirror (RSS)", handles)
for inst in ["https://nitter.net", "https://xcancel.com", "https://nitter.poast.org", "https://nitter.privacydev.net",
             "https://nitter.tiekoetter.com", "https://nitter.space", "https://lightbrd.com", "https://nitter.kareem.one"]:
    for h in handles[:2]:
        try:
            body = http(f"{inst}/{h}/rss", UA_HTML, as_json=False, tries=1, timeout=15)
            items = len(re.findall(r"<item>", body or ""))
            print(f"  {inst} {h}: {'OK' if items else 'kosong'} items={items} len={len(body or '')}")
        except Exception as e:
            print(f"  {inst} {h}: ERR {str(e)[:80]}")
print("== fxtwitter user")
for h in handles[:3]:
    try:
        d = http(f"https://api.fxtwitter.com/{h}", UA_JSON, tries=1)
        u = (d or {}).get("user") or {}
        print(f"  {h}: followers={u.get('followers')} joined={u.get('joined')}")
    except Exception as e:
        print(f"  {h}: ERR {str(e)[:80]}")
print("== pump.fun")
for u in ["https://frontend-api-v3.pump.fun/coins/latest", "https://frontend-api-v3.pump.fun/coins?offset=0&limit=5&sort=last_trade_timestamp&order=DESC",
          "https://frontend-api-v3.pump.fun/callouts?limit=5", "https://frontend-api-v3.pump.fun/coins/callouts?limit=5",
          "https://advanced-api-v2.pump.fun/coins/list?sortBy=creationTime&limit=5"]:
    try:
        req = urllib.request.Request(u, headers=UA_JSON)
        with urllib.request.urlopen(req, timeout=15) as r:
            b = r.read(400)
        print(f"  {u}: {r.status} {b[:200]!r}")
    except Exception as e:
        print(f"  {u}: ERR {str(e)[:100]}")

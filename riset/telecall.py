"""Uji maju (paper): callout channel Telegram GRATIS + cek latar belakang koin.

Ide user (8 Nov 2026): gabung grup call gratis, tiap ada callout cek dulu latar belakang koin
(X, website, rugcheck, holder, narasi), baru beli kalau lolos. Ditambah alat dari 3 reel IG:
bot cek koin (Soul Scanner / SolSniffer / Rick = rugcheck + holder), Bubblemaps (cluster
insider), salpha (narasi X), whale/wallet alert.

Cara kerja (tanpa login, tanpa akun Telegram):
  run    : tiap ~90 dtk baca halaman publik t.me/s/<channel> semua channel yang dipantau, ambil
           contract address (CA) Solana dari teks + link. Tiap CA baru langsung dicek SEKALI:
           DexScreener (harga, likuiditas, mcap, umur pool, link X/website), rugcheck (mint/freeze,
           risiko, top10, insider/cluster, dev), profil X lewat api.fxtwitter.com (follower, umur
           akun). Harga semua CA dicatat tiap 60 dtk selama 24 jam.
           Channel baru ditemukan otomatis dari link t.me/... dan 'forwarded from' di postingan.
  report : simulasi beli di harga pertama SETELAH callout terdeteksi (latensi nyata), biaya 1.5%/sisi,
           filter + exit yang sudah dipraregistrasi (riset/telecall-praregistrasi.md), split waktu A/B.
Paper saja. Tidak ada wallet, tidak ada kunci, tidak ada login.

Pakai: python3 riset/telecall.py run --data data --duration 20700
       python3 riset/telecall.py report --data data
"""
import argparse
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rugdesk import rc_report  # noqa: E402

DS = "https://api.dexscreener.com/tokens/v1/solana"
FX = "https://api.fxtwitter.com"
UA_JSON = {"User-Agent": "memescan-riset/1.0 (github.com/agilganteng/memescan)", "Accept": "application/json"}
UA_HTML = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}

SEEDS = """RiskyGemsHuntersCalls solana_millionaires solanacalls04 ramcalls solanagemcall Cabal777xbt
solalphacalls solmemesignals spacemancallzsolana SIGNALCALLS SolanaMemeCoinss solana100xcall solmemecoincall
SolanaTopDogz solearlytrending Pumpfunpremium shitcoingemsalert SolanaMemePit PumpFunSolana1
SolanaMemeCryptoCoins solanagemdegencall""".split()
MAX_CHANNELS = 150
TRACK_H = 24
POLL_S = 90
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
CA_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
SKIP_CA = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
           "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY9NAZsXEbUYsWDb", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
           "11111111111111111111111111111111", "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
           "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"}
TG_RE = re.compile(r"(?:https?://)?t\.me/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?=[\s/?\"'#<),.]|$)")
TG_SKIP = {"joinchat", "share", "addstickers", "proxy", "socks", "iv", "c", "s", "durov", "telegram",
           "BotFather", "contest", "addlist", "boost"}


def b58_ok(s):
    n = 0
    for ch in s:
        i = B58.find(ch)
        if i < 0:
            return False
        n = n * 58 + i
    return n.bit_length() <= 256 and len(n.to_bytes(32, "big")) == 32 and n > 2 ** 200


def http(url, headers, as_json=True, tries=3, timeout=20):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                body = r.read()
                return json.loads(body) if as_json else body.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 400):
                return None
            if i == tries - 1:
                raise
            time.sleep(20 * (i + 1) if e.code == 429 else 3 * (i + 1))
        except Exception:   # noqa: BLE001
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))
    return None


# ---------------------------------------------------------------- Telegram publik (t.me/s)
MSG_SPLIT = re.compile(r'<div class="tgme_widget_message_wrap')


def parse_channel(page):
    """Return list of dict(id, t, text, links, fwd) dari halaman t.me/s/<name> (20 post terakhir)."""
    out = []
    for blk in MSG_SPLIT.split(page)[1:]:
        m = re.search(r'data-post="([^"/]+)/(\d+)"', blk)
        if not m:
            continue
        tm = re.search(r'<time[^>]*datetime="([^"]+)"', blk)
        t = None
        if tm:
            try:
                t = time.mktime(time.strptime(tm.group(1)[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
                off = tm.group(1)[19:]
                if off and off[0] in "+-" and len(off) >= 6:
                    sgn = 1 if off[0] == "+" else -1
                    t -= sgn * (int(off[1:3]) * 3600 + int(off[4:6]) * 60)
            except ValueError:
                t = None
        txt = ""
        tx = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', blk, re.S)
        if tx:
            txt = html.unescape(re.sub(r"<br\s*/?>", "\n", tx.group(1)))
            txt = re.sub(r"<[^>]+>", " ", txt)
        links = [html.unescape(h) for h in re.findall(r'href="([^"]+)"', blk)]
        fwd = re.search(r'tgme_widget_message_forwarded_from_name"[^>]*href="https?://t\.me/([A-Za-z0-9_]+)', blk)
        out.append({"id": int(m.group(2)), "t": t, "text": txt.strip(), "links": links,
                    "fwd": fwd.group(1) if fwd else None})
    return out


def cas_in(msg):
    found = []
    for s in [msg["text"]] + msg["links"]:
        for c in CA_RE.findall(s or ""):
            if c not in SKIP_CA and c not in found and b58_ok(c):
                found.append(c)
    return found


def tg_names(msg):
    names = set()
    for s in [msg["text"]] + msg["links"]:
        for n in TG_RE.findall((s or "") + " "):
            if n not in TG_SKIP and not n.lower().endswith("bot"):
                names.add(n)
    if msg.get("fwd"):
        names.add(msg["fwd"])
    return names


# ---------------------------------------------------------------- latar belakang koin
def best_pair(mint, pairs):
    pairs = [p for p in pairs or [] if (p.get("baseToken") or {}).get("address") == mint]
    if not pairs:
        return None
    return max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)


def pair_row(p, now):
    born = p.get("pairCreatedAt")
    info = p.get("info") or {}
    socials = info.get("socials") or []
    xs = [s.get("url") for s in socials if (s.get("type") or "").lower() in ("twitter", "x")]
    tgs = [s.get("url") for s in socials if (s.get("type") or "").lower() == "telegram"]
    h1 = (p.get("txns") or {}).get("h1") or {}
    return {"symbol": (p.get("baseToken") or {}).get("symbol"), "name": (p.get("baseToken") or {}).get("name"),
            "price": float(p.get("priceUsd") or 0), "liq": (p.get("liquidity") or {}).get("usd") or 0,
            "mcap": p.get("marketCap") or p.get("fdv") or 0, "dex": p.get("dexId"),
            "age_min": round((now * 1000 - born) / 60000) if born else None,
            "vol_h1": (p.get("volume") or {}).get("h1") or 0, "buys_h1": h1.get("buys", 0),
            "sells_h1": h1.get("sells", 0), "chg_h1": (p.get("priceChange") or {}).get("h1"),
            "x": xs[0] if xs else None, "tg": tgs[0] if tgs else None,
            "web": bool(info.get("websites")), "boosts": (p.get("boosts") or {}).get("active", 0)}


def x_profile(url):
    """Akun X dari link DexScreener. Link /status/ atau /i/communities/ = bukan akun sendiri."""
    if not url:
        return {"kind": "none"}
    u = url.split("?")[0].rstrip("/")
    m = re.search(r"(?:twitter|x)\.com/([^/]+)(/.*)?$", u)
    if not m:
        return {"kind": "other"}
    user, rest = m.group(1), m.group(2) or ""
    if user in ("i", "search", "hashtag") or "communities" in rest:
        return {"kind": "community"}
    if "/status/" in rest:
        return {"kind": "status", "user": user}
    try:
        d = http(f"{FX}/{user}", UA_JSON)
    except Exception:   # noqa: BLE001
        return {"kind": "account", "user": user, "err": 1}
    us = (d or {}).get("user") or {}
    created = us.get("joined") or us.get("created_at")
    age_d = None
    if created:
        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                ts = time.mktime(time.strptime(created.replace("+0000", "UTC").replace(" UTC", " +0000")
                                               if "%z" in fmt else created, fmt))
                age_d = round((time.time() - ts) / 86400, 1)
                break
            except (ValueError, OverflowError):
                continue
    return {"kind": "account", "user": user, "followers": us.get("followers"), "tweets": us.get("tweets"),
            "age_d": age_d}


def background(mint):
    now = time.time()
    rec = {"mint": mint, "t_bg": round(now, 1)}
    try:
        pr = http(f"{DS}/{mint}", UA_JSON) or []
        p = best_pair(mint, pr if isinstance(pr, list) else pr.get("pairs"))
        rec["ds"] = pair_row(p, now) if p else None
    except Exception as e:   # noqa: BLE001
        rec["ds"], rec["ds_err"] = None, type(e).__name__
    try:
        rec["rc"] = rc_report(mint)
    except Exception as e:   # noqa: BLE001
        rec["rc"], rec["rc_err"] = None, type(e).__name__
    rec["xp"] = x_profile((rec.get("ds") or {}).get("x"))
    return rec


# ---------------------------------------------------------------- perekam
def load_json(fp, default):
    try:
        return json.load(open(fp))
    except (OSError, ValueError):
        return default


def run(data, duration):
    d = os.path.join(data, "telecall")
    os.makedirs(d, exist_ok=True)
    st_fp = os.path.join(d, "state.json")
    st = load_json(st_fp, {"channels": {}, "dead": [], "queue": []})
    for s in SEEDS:
        if s not in st["channels"] and s not in st["dead"] and s not in st["queue"]:
            st["queue"].append(s)
    tokens = {}   # mint -> first call t
    for line in open(os.path.join(d, "tokens.jsonl")) if os.path.exists(os.path.join(d, "tokens.jsonl")) else []:
        try:
            x = json.loads(line)
            tokens[x["mint"]] = x["t_bg"]
        except (ValueError, KeyError):
            pass
    t_end = time.time() + duration
    next_poll = next_px = 0.0
    n_calls = n_tok = 0
    print(f"telecall mulai: {len(st['channels'])} channel, antre {len(st['queue'])}, {len(tokens)} token lama",
          flush=True)
    while time.time() < t_end:
        now = time.time()
        if now >= next_poll:
            next_poll = now + POLL_S
            # 1) coba channel baru dari antrean (maks 8 per putaran)
            for _ in range(min(8, len(st["queue"]))):
                if len(st["channels"]) >= MAX_CHANNELS:
                    st["queue"] = []
                    break
                name = st["queue"].pop(0)
                try:
                    page = http(f"https://t.me/s/{name}", UA_HTML, as_json=False)
                except Exception:   # noqa: BLE001
                    page = None
                msgs = parse_channel(page) if page else []
                n_ca = sum(1 for m in msgs if cas_in(m))
                if not msgs or n_ca == 0:
                    st["dead"].append(name)
                    continue
                st["channels"][name] = {"last": max(m["id"] for m in msgs), "added": round(now), "ca_posts0": n_ca,
                                        "calls": 0}
                print(f"+ channel {name}: {len(msgs)} post, {n_ca} berisi CA", flush=True)
                for m in msgs:
                    for nm in tg_names(m):
                        if nm not in st["channels"] and nm not in st["dead"] and nm not in st["queue"]:
                            st["queue"].append(nm)
                time.sleep(1.0)
            # 2) baca semua channel, cari post baru
            new_calls = []
            for name, ch in list(st["channels"].items()):
                try:
                    page = http(f"https://t.me/s/{name}", UA_HTML, as_json=False)
                except Exception:   # noqa: BLE001
                    continue
                if not page:
                    continue
                for m in parse_channel(page):
                    if m["id"] <= ch["last"]:
                        continue
                    ch["last"] = max(ch["last"], m["id"])
                    for nm in tg_names(m):
                        if nm not in st["channels"] and nm not in st["dead"] and nm not in st["queue"]:
                            st["queue"].append(nm)
                    for ca in cas_in(m):
                        new_calls.append({"ch": name, "msg": m["id"], "mint": ca, "t_post": m["t"],
                                          "t_seen": round(time.time(), 1), "fwd": m["fwd"],
                                          "text": m["text"][:300]})
                time.sleep(0.4)
            # 3) tiap call: cek latar belakang SEKALI per token
            for c in new_calls:
                if c["mint"] not in tokens:
                    rec = background(c["mint"])
                    rec["first_ch"] = c["ch"]
                    if not rec.get("ds"):
                        rec["note"] = "no_pair"
                    tokens[c["mint"]] = rec["t_bg"]
                    with open(os.path.join(d, "tokens.jsonl"), "a") as f:
                        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
                    n_tok += 1
                    ds = rec.get("ds") or {}
                    print(f"CALL {c['ch']} {ds.get('symbol')} {c['mint']} mcap ${ds.get('mcap') or 0:,.0f} "
                          f"liq ${ds.get('liq') or 0:,.0f} X {rec['xp'].get('kind')} {rec['xp'].get('followers')}",
                          flush=True)
                    time.sleep(0.5)
                st["channels"][c["ch"]]["calls"] = st["channels"][c["ch"]].get("calls", 0) + 1
                with open(os.path.join(d, "calls.jsonl"), "a") as f:
                    f.write(json.dumps(c, separators=(",", ":"), ensure_ascii=False) + "\n")
                n_calls += 1
            json.dump(st, open(st_fp, "w"))
        if now >= next_px:
            next_px = now + 60
            live = [m for m, t0 in tokens.items() if now - t0 < TRACK_H * 3600]
            rows = []
            for i in range(0, len(live), 30):
                chunk = live[i:i + 30]
                try:
                    pr = http(f"{DS}/{','.join(chunk)}", UA_JSON) or []
                except Exception:   # noqa: BLE001
                    continue
                pr = pr if isinstance(pr, list) else pr.get("pairs") or []
                for mint in chunk:
                    p = best_pair(mint, pr)
                    if p:
                        rows.append([round(now), mint, float(p.get("priceUsd") or 0),
                                     round((p.get("liquidity") or {}).get("usd") or 0)])
                    else:
                        rows.append([round(now), mint, 0.0, 0])
            if rows:
                with open(os.path.join(d, time.strftime("px-%Y%m%d.jsonl", time.gmtime(now))), "a") as f:
                    for r in rows:
                        f.write(json.dumps(r, separators=(",", ":")) + "\n")
        time.sleep(3)
    json.dump(st, open(st_fp, "w"))
    print(f"telecall selesai: {n_calls} call, {n_tok} token baru, {len(st['channels'])} channel aktif, "
          f"{len(st['dead'])} channel ditolak, antre {len(st['queue'])}", flush=True)


# ---------------------------------------------------------------- laporan
COST = 0.015      # fee + slippage per sisi
ENTRY_LAG = 30    # detik tambahan setelah terdeteksi (manusia/bot butuh waktu klik)


def load_all(data):
    d = os.path.join(data, "telecall")
    toks, calls, px = {}, [], {}
    for line in open(os.path.join(d, "tokens.jsonl")) if os.path.exists(os.path.join(d, "tokens.jsonl")) else []:
        try:
            x = json.loads(line)
            toks[x["mint"]] = x
        except ValueError:
            pass
    for line in open(os.path.join(d, "calls.jsonl")) if os.path.exists(os.path.join(d, "calls.jsonl")) else []:
        try:
            calls.append(json.loads(line))
        except ValueError:
            pass
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if fn.startswith("px-"):
            for line in open(os.path.join(d, fn)):
                try:
                    t, mint, p, liq = json.loads(line)
                except ValueError:
                    continue
                px.setdefault(mint, []).append((t, p, liq))
    for v in px.values():
        v.sort()
    return toks, calls, px


def sim(series, t_in, ex):
    """Return x setelah biaya (2 sisi) atau None. Harga dicek tiap ~60 dtk = isi stop realistis."""
    pts = [x for x in series if x[0] >= t_in]
    if not pts or pts[0][1] <= 0 or pts[0][0] - t_in > 300:
        return None
    t0, p0 = pts[0][0], pts[0][1]
    T = ex.get("T", 24 * 3600)
    held, got, peak, armed = 1.0, 0.0, p0, False
    last = p0
    for t, p, liq in pts[1:]:
        if t - t0 > T:
            break
        if p <= 0:          # pool hilang / rug: anggap nol
            return got * (1 - COST) * (1 - COST)
        last = p
        r = p / p0
        peak = max(peak, p)
        if ex.get("half") and held == 1.0 and r >= ex["half"]:
            got += 0.5 * r
            held = 0.5
            armed = True
        if ex.get("tp") and r >= ex["tp"]:
            got += held * r
            held = 0
            break
        if ex.get("arm") and r >= ex["arm"]:
            armed = True
        if ex.get("trail") and armed and p <= peak * (1 - ex["trail"]):
            got += held * r
            held = 0
            break
        if ex.get("sl") and r <= 1 - ex["sl"]:
            got += held * r
            held = 0
            break
    if held:
        got += held * last / p0
    return got * (1 - COST) * (1 - COST)


EXITS = {
    "H1 tahan 1j": dict(T=3600),
    "H6 tahan 6j": dict(T=6 * 3600),
    "H24 tahan 24j": dict(T=24 * 3600),
    "X1 TP2x SL30%": dict(tp=2.0, sl=0.30),
    "X2 jual 1/2 di 2x + trail30%": dict(half=2.0, trail=0.30),
    "X3 trail30% stlh +50% SL40%": dict(arm=1.5, trail=0.30, sl=0.40),
    "X4 TP+50% SL25% 6j": dict(tp=1.5, sl=0.25, T=6 * 3600),
}


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    ph = k / n
    den = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / den
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def bank(xs, start, frac):
    b = start
    for x in xs:
        b += b * frac * (x - 1)
    return b


def report(data):
    toks, calls, px = load_all(data)
    if not calls:
        print("belum ada call")
        return
    calls.sort(key=lambda c: c["t_seen"])
    first_seen, chans_by_mint = {}, {}
    events = []
    for c in calls:
        m = c["mint"]
        chans_by_mint.setdefault(m, [])
        prior = list(chans_by_mint[m])
        if c["ch"] not in chans_by_mint[m]:
            chans_by_mint[m].append(c["ch"])
        tk = toks.get(m) or {}
        ds, rc, xp = tk.get("ds") or {}, tk.get("rc") or {}, tk.get("xp") or {}
        ev = {"mint": m, "ch": c["ch"], "t": c["t_seen"] + ENTRY_LAG, "lag": (c["t_seen"] - c["t_post"]) if c.get("t_post") else None,
              "n_ch": len(chans_by_mint[m]), "first": m not in first_seen,
              "late": (m in first_seen and c["t_seen"] - first_seen[m] >= 1800), "new_ch": c["ch"] not in prior}
        first_seen.setdefault(m, c["t_seen"])
        ev["clean"] = bool(rc) and not rc.get("mint_authority") and not rc.get("freeze_authority") and \
            not rc.get("danger") and (rc.get("top10_pct") is not None and rc["top10_pct"] <= 30) and \
            (rc.get("insiders") or 0) == 0
        ev["xgood"] = xp.get("kind") == "account" and (xp.get("followers") or 0) >= 1000 and (xp.get("age_d") or 0) >= 30
        ev["mkt"] = (ds.get("liq") or 0) >= 10000 and 20000 <= (ds.get("mcap") or 0) <= 5_000_000
        ev["xweb"] = bool(ds.get("x")) and bool(ds.get("web"))
        events.append(ev)
    t_split = sorted(e["t"] for e in events)[len(events) // 2]
    FILTERS = {
        "F0 semua call": lambda e: e["new_ch"],
        "F1 >=2 channel (masuk saat channel ke-2)": lambda e: e["new_ch"] and e["n_ch"] == 2,
        "F2 rugcheck bersih": lambda e: e["new_ch"] and e["clean"],
        "F3 akun X >=1k follower & >=30 hari": lambda e: e["new_ch"] and e["xgood"],
        "F4 liq>=$10k, mcap $20k-5M": lambda e: e["new_ch"] and e["mkt"],
        "F5 punya X + website": lambda e: e["new_ch"] and e["xweb"],
        "F6 screening penuh F2+F3+F4": lambda e: e["new_ch"] and e["clean"] and e["xgood"] and e["mkt"],
        "F7 F1+F2+F4": lambda e: e["new_ch"] and e["n_ch"] == 2 and e["clean"] and e["mkt"],
        "F8 call pertama koin itu": lambda e: e["first"],
        "F9 call telat (>=30 mnt stlh call pertama)": lambda e: e["new_ch"] and e["late"],
    }
    n_tok = len(toks)
    lags = sorted(e["lag"] for e in events if e["lag"] is not None)
    print(f"== {len(calls)} call, {n_tok} token, {len(set(c['ch'] for c in calls))} channel; "
          f"split A/B di {time.strftime('%d/%m %H:%M', time.gmtime(t_split))} UTC")
    if lags:
        print(f"   jeda post -> terdeteksi: median {lags[len(lags)//2]:.0f} dtk, p90 {lags[int(len(lags)*0.9)]:.0f} dtk"
              f" (+{ENTRY_LAG} dtk waktu klik)")
    print("\n## TABEL (rata x per trade setelah biaya 1.5%/sisi)  A -> B")
    passed = []
    for fn, f in FILTERS.items():
        sel = [e for e in events if f(e)]
        for xn, ex in EXITS.items():
            res = {"A": [], "B": []}
            for e in sel:
                x = sim(px.get(e["mint"], []), e["t"], ex)
                if x is not None:
                    res["A" if e["t"] < t_split else "B"].append(x)
            a, b = res["A"], res["B"]
            ma = sum(a) / len(a) if a else 0
            mb = sum(b) / len(b) if b else 0
            nb_best = (sum(b) - max(b)) / (len(b) - 1) if len(b) > 1 else 0
            ok = len(b) >= 30 and ma > 1 and mb > 1 and nb_best > 1
            if ok:
                passed.append((fn, xn))
            print(f"  {fn:44s} {xn:30s} A {ma:6.3f}x n={len(a):4d} | B {mb:6.3f}x n={len(b):4d} "
                  f"tanpa-terbaik {nb_best:5.3f}{'  <<< LULUS' if ok else ''}")
    print(f"\n## LULUS (n_B>=30, A>1, B>1, B tanpa koin terbaik >1): {len(passed)}")
    for fn, xn in passed:
        print("  ", fn, "|", xn)
    # simulasi modal pada semua data untuk F0 dan F6
    print("\n## Simulasi modal (urut waktu, 10%/trade), semua data:")
    for fn in ("F0 semua call", "F6 screening penuh F2+F3+F4", "F1 >=2 channel (masuk saat channel ke-2)"):
        for xn in ("H1 tahan 1j", "X1 TP2x SL30%", "X3 trail30% stlh +50% SL40%"):
            xs = [x for x in (sim(px.get(e["mint"], []), e["t"], EXITS[xn]) for e in events if FILTERS[fn](e)) if x is not None]
            if not xs:
                continue
            k = sum(1 for x in xs if x > 1)
            lo, hi = wilson(k, len(xs))
            print(f"  {fn} | {xn}: n={len(xs)} rata {sum(xs)/len(xs):.3f}x median {sorted(xs)[len(xs)//2]:.3f}x "
                  f"menang {k/len(xs):.0%} [{lo:.0%}-{hi:.0%}]  $100->${bank(xs,100,.1):,.0f} "
                  f"$200->${bank(xs,200,.1):,.0f} $1000->${bank(xs,1000,.1):,.0f}")
    # per channel
    print("\n## Per channel (F0, tahan 1 jam):")
    per = {}
    for e in events:
        if not e["new_ch"]:
            continue
        x = sim(px.get(e["mint"], []), e["t"], EXITS["H1 tahan 1j"])
        if x is not None:
            per.setdefault(e["ch"], []).append(x)
    for ch, xs in sorted(per.items(), key=lambda kv: -len(kv[1]))[:40]:
        print(f"  {ch:28s} n={len(xs):4d} rata {sum(xs)/len(xs):.3f}x median {sorted(xs)[len(xs)//2]:.3f}x")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--data", default="data")
    ap.add_argument("--duration", type=int, default=20700)
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.data, a.duration)
    else:
        report(a.data)


if __name__ == "__main__":
    main()

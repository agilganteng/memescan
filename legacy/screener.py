#!/usr/bin/env python3
"""memescan: screener memecoin + notifikasi Telegram.

Ambil coin yang lagi trending/baru dari DexScreener (gratis, tanpa API key),
nilai momentum + risiko (likuiditas, umur, rasio buy/sell, RugCheck untuk
Solana), lalu kirim BEBERAPA kandidat per scan ke Telegram.

Ini sinyal, bukan saran beli. Mayoritas memecoin baru berakhir ke nol.

Pakai:
    python3 memescan.py                 # sekali scan, print ke terminal
    python3 memescan.py --loop 300      # scan tiap 5 menit
    TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... python3 memescan.py --loop 300

Hanya pakai library bawaan Python 3.9+.
"""
import argparse
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEX = "https://api.dexscreener.com"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{}/report/summary"
UA = {"User-Agent": "memescan/0.1", "Accept": "application/json"}

# Ambang default. Ubah lewat flag CLI kalau mau lebih agresif/konservatif.
DEFAULTS = dict(
    chain="solana",
    min_liq=15_000,       # USD. Di bawah ini gampang dimanipulasi / susah jual
    min_vol_h1=20_000,    # USD volume 1 jam terakhir
    max_age_h=72,         # coin lebih tua dari ini bukan "fresh pump" lagi
    min_score=50,         # skor minimal untuk dikirim (0-100)
    top=5,                # maksimal coin per notifikasi
    cooldown_h=6,         # coin yang sama tidak dikirim ulang dalam periode ini
    tp_pct=50.0,          # take profit +50% dari harga entry
    sl_pct=25.0,          # stop loss -25%
    max_hold_h=24.0,      # posisi paper ditutup paksa setelah ini
    stake=10.0,           # USD per posisi paper
    paper_start=100.0,    # saldo awal paper trading (USD)
    cost_pct=3.0,         # asumsi biaya+slippage per sisi; memecoin kecil sering lebih
)


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------- sumber data

def candidate_tokens(chain):
    """Alamat token dari daftar profil terbaru + boost DexScreener."""
    addrs = []
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1"):
        try:
            rows = get_json(DEX + path)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"[warn] {path}: {e}", file=sys.stderr)
            continue
        for row in rows if isinstance(rows, list) else []:
            if row.get("chainId") == chain and row.get("tokenAddress"):
                addrs.append(row["tokenAddress"])
    return list(dict.fromkeys(addrs))  # dedup, urutan tetap


def best_pairs(chain, addrs):
    """Satu pair per token: yang likuiditasnya paling besar."""
    best = {}
    for i in range(0, len(addrs), 30):  # endpoint menerima maks 30 alamat
        chunk = ",".join(addrs[i:i + 30])
        try:
            pairs = get_json(f"{DEX}/tokens/v1/{chain}/{chunk}")
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"[warn] tokens batch: {e}", file=sys.stderr)
            continue
        for p in pairs or []:
            addr = (p.get("baseToken") or {}).get("address")
            if addr not in addrs:
                continue  # token kita ada di sisi quote, skip
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if addr not in best or liq > ((best[addr].get("liquidity") or {}).get("usd") or 0):
                best[addr] = p
    return list(best.values())


def rugcheck(mint):
    """Ringkasan RugCheck (Solana saja). None kalau gagal."""
    try:
        return get_json(RUGCHECK.format(urllib.parse.quote(mint)), timeout=15)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


# ---------------------------------------------------------------- penilaian

def _n(d, *keys):
    for k in keys:
        d = (d or {}).get(k)
    return d or 0


def assess(p, now_ms, cfg):
    """Return (score 0-100, list sinyal positif, list red flag, hard_reject)."""
    liq = _n(p, "liquidity", "usd")
    mcap = p.get("marketCap") or p.get("fdv") or 0
    vol_h1 = _n(p, "volume", "h1")
    vol_h24 = _n(p, "volume", "h24")
    ch_m5, ch_h1, ch_h6 = (_n(p, "priceChange", k) for k in ("m5", "h1", "h6"))
    buys, sells = _n(p, "txns", "h1", "buys"), _n(p, "txns", "h1", "sells")
    created = p.get("pairCreatedAt")
    age_h = (now_ms - created) / 3_600_000 if created else None

    good, flags = [], []

    # Filter keras: tidak layak dilihat sama sekali.
    if liq < cfg["min_liq"]:
        return 0, good, [f"likuiditas cuma ${liq:,.0f}"], True
    if vol_h1 < cfg["min_vol_h1"]:
        return 0, good, [f"volume 1j cuma ${vol_h1:,.0f}"], True
    if age_h is not None and age_h > cfg["max_age_h"]:
        return 0, good, [f"umur {age_h:.0f} jam"], True

    score = 0.0
    # Momentum harga (dibatasi supaya satu candle gila tidak mendominasi).
    score += min(max(ch_h1, 0), 200) / 200 * 25
    score += min(max(ch_m5, 0), 50) / 50 * 10
    if ch_h1 > 20:
        good.append(f"+{ch_h1:.0f}% 1j")
    if ch_m5 < -15:
        flags.append(f"lagi dump {ch_m5:.0f}% 5m")
        score -= 15

    # Aktivitas: volume relatif ke likuiditas = seberapa ramai diperdagangkan.
    turnover = vol_h1 / liq if liq else 0
    score += min(turnover, 5) / 5 * 20
    if turnover > 1:
        good.append(f"volume 1j {turnover:.1f}x likuiditas")

    # Tekanan beli: lebih banyak transaksi beli dari jual.
    tx = buys + sells
    if tx >= 50:
        ratio = buys / tx
        score += max(ratio - 0.5, 0) / 0.5 * 20
        if ratio > 0.6:
            good.append(f"{ratio:.0%} transaksi beli")
        if ratio < 0.4:
            flags.append(f"jual mendominasi ({1 - ratio:.0%})")
    else:
        flags.append(f"transaksi 1j sedikit ({tx})")

    # Kesehatan likuiditas relatif ke market cap.
    if mcap:
        lm = liq / mcap
        if lm < 0.05:
            flags.append(f"likuiditas tipis vs mcap ({lm:.1%})")
            score -= 10
        else:
            score += min(lm, 0.3) / 0.3 * 10

    # Umur: sangat baru = potensi besar tapi paling rawan rug.
    if age_h is not None:
        if age_h < 1:
            flags.append(f"umur {age_h * 60:.0f} menit (sangat rawan)")
        score += 15 if 1 <= age_h <= 24 else 5

    if ch_h6 > 1000:
        flags.append(f"sudah +{ch_h6:.0f}% 6j (risiko beli di pucuk)")

    return max(0, min(100, round(score))), good, flags, False


def apply_rugcheck(rc, score, flags):
    """Tambah red flag dari RugCheck. Return (score, reject)."""
    if not rc:
        flags.append("RugCheck tidak tersedia")
        return score - 5, False
    reject = False
    for r in rc.get("risks") or []:
        level, name = r.get("level"), r.get("name", "?")
        if level == "danger":
            flags.append(f"🚨 {name}")
            score -= 25
            low = name.lower()
            if "mint" in low or "freeze" in low or "rug" in low:
                reject = True  # dev masih bisa cetak/bekukan token = hampir pasti jebakan
        elif level == "warn":
            flags.append(f"⚠️ {name}")
            score -= 8
    return max(0, score), reject


# ---------------------------------------------------------------- analisa teknikal

GECKO = "https://api.geckoterminal.com/api/v2/networks/{}/pools/{}/ohlcv/minute?aggregate=5&limit=100"
GECKO_NET = {"solana": "solana", "base": "base", "bsc": "bsc", "ethereum": "eth"}


def candles(chain, pool):
    """Candle 5 menit dari GeckoTerminal, urut lama -> baru: [ts, o, h, l, c, v]."""
    net = GECKO_NET.get(chain)
    if not net:
        return []
    try:
        d = get_json(GECKO.format(net, urllib.parse.quote(pool)), timeout=15)
        rows = d["data"]["attributes"]["ohlcv_list"]
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
        return []
    return sorted(rows, key=lambda r: r[0])


def ema(xs, n):
    k, out = 2 / (n + 1), [xs[0]]
    for x in xs[1:]:
        out.append(x * k + out[-1] * (1 - k))
    return out


def rsi(xs, n=14):
    if len(xs) <= n:
        return None
    gains = [max(b - a, 0) for a, b in zip(xs, xs[1:])]
    losses = [max(a - b, 0) for a, b in zip(xs, xs[1:])]
    g, l = sum(gains[:n]) / n, sum(losses[:n]) / n
    for gi, li in zip(gains[n:], losses[n:]):  # smoothing Wilder
        g, l = (g * (n - 1) + gi) / n, (l * (n - 1) + li) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)


def technicals(rows):
    """Return (score_delta, sinyal, flags) dari candle. Butuh >= 21 candle."""
    if len(rows) < 21:
        return 0, [], ["data candle belum cukup untuk TA"]
    close = [float(r[4]) for r in rows]
    vol = [float(r[5]) for r in rows]
    e9, e21 = ema(close, 9), ema(close, 21)
    r = rsi(close)
    delta, good, flags = 0, [], []

    if e9[-1] > e21[-1]:
        delta += 5
        if e9[-4] <= e21[-4]:
            good.append("EMA9 baru cross ke atas EMA21 (5m)")
            delta += 5
    else:
        flags.append("EMA9 di bawah EMA21 (tren 5m turun)")
        delta -= 10

    if r is not None:
        if r > 85:
            flags.append(f"RSI {r:.0f} overbought")
            delta -= 10
        elif 50 <= r <= 75:
            good.append(f"RSI {r:.0f}")
            delta += 5

    base = sorted(vol[-21:-1])[10] or 1  # median 20 candle sebelumnya
    if vol[-1] > 3 * base:
        good.append(f"volume candle terakhir {vol[-1] / base:.0f}x median")
        delta += 5
    return delta, good, flags


# ---------------------------------------------------------------- output

def fmt_usd(x):
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if x >= div:
            return f"${x / div:.1f}{suf}"
    return f"${x:.0f}"


def fmt_price(x):
    if x >= 1:
        return f"${x:,.2f}"
    from decimal import Decimal
    return "$" + format(Decimal(f"{x:.3g}"), "f")


def render(items, chain, cfg=None, footer=""):
    e = html.escape  # nama/simbol token bebas diisi siapa saja, jangan dipercaya
    lines = [f"📡 <b>memescan</b> · {chain} · {len(items)} sinyal", ""]
    for i, (p, score, good, flags) in enumerate(items, 1):
        b = p.get("baseToken") or {}
        mcap = p.get("marketCap") or p.get("fdv") or 0
        lines.append(f"<b>{i}. {e(b.get('symbol', '?'))}</b> — skor {score}/100")
        lines.append(f"MC {fmt_usd(mcap)} · Liq {fmt_usd(_n(p, 'liquidity', 'usd'))} · "
                     f"1j {_n(p, 'priceChange', 'h1'):+.0f}% · Vol1j {fmt_usd(_n(p, 'volume', 'h1'))}")
        if good:
            lines.append("✅ " + e(", ".join(good)))
        if flags:
            lines.append("🚩 " + e(", ".join(flags)))
        price = float(p.get("priceUsd") or 0)
        if price and cfg:
            lines.append(f"🎯 Entry ~{fmt_price(price)} · TP {fmt_price(price * (1 + cfg['tp_pct'] / 100))} "
                         f"(+{cfg['tp_pct']:.0f}%) · SL {fmt_price(price * (1 - cfg['sl_pct'] / 100))} "
                         f"(-{cfg['sl_pct']:.0f}%)")
        lines.append(f"<code>{e(b.get('address', ''))}</code>")
        lines.append(e(p.get("url", "")))
        lines.append("")
    if footer:
        lines.append(footer)
    lines.append("<i>Sinyal otomatis, bukan saran beli. Cek sendiri, pakai uang yang siap hilang.</i>")
    return "\n".join(lines)


_CHAT = None  # chat id Telegram; dari env, state, atau ditemukan otomatis


def find_chat(token):
    """Cari chat id dari /start pertama ke bot, supaya user tidak perlu nyari
    TELEGRAM_CHAT_ID sendiri. Setelah ketemu, chat ini dikunci di state dan tidak
    pernah dicari ulang, jadi orang lain yang /start belakangan diabaikan."""
    try:
        d = get_json(f"https://api.telegram.org/bot{token}/getUpdates")
    except urllib.error.HTTPError as e:
        print(f"[warn] telegram: token ditolak ({e.code}), cek lagi TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"[warn] telegram getUpdates gagal: {e!r}", file=sys.stderr)
        return None
    try:
        me = get_json(f"https://api.telegram.org/bot{token}/getMe").get("result") or {}
        print(f"[info] telegram: token ini milik bot @{me.get('username')}", file=sys.stderr)
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    kinds = [c.get("type") for u in d.get("result") or [] for c in [(u.get("message") or {}).get("chat") or {}]]
    print(f"[info] telegram: {len(kinds)} pesan masuk ke bot, tipe chat {kinds}", file=sys.stderr)
    for u in d.get("result") or []:  # chat pertama yang pernah /start, bukan yang terakhir
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private":
            return str(chat["id"])
    return None


def send_telegram(text):
    global _CHAT
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()  # spasi/enter ikut ter-paste
    if not token:
        return False
    if not _CHAT:
        _CHAT = find_chat(token)
        if not _CHAT:
            print("[warn] telegram: chat belum ketemu, kirim /start ke bot kamu dulu", file=sys.stderr)
            return False
        lock = urllib.parse.urlencode({"chat_id": _CHAT, "text": (
            f"🔒 memescan terkunci ke chat ini (ID {_CHAT}). Orang lain yang /start bot ini diabaikan. "
            "Biar lebih aman, simpan ID ini sebagai secret TELEGRAM_CHAT_ID.")}).encode()
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", lock, timeout=20)
        except urllib.error.URLError:
            pass
    chat = _CHAT
    data = urllib.parse.urlencode({
        "chat_id": chat, "text": text, "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=20)
        return True
    except urllib.error.URLError as e:
        print(f"[warn] telegram: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------- paper trading
# Simulasi pakai uang bohongan untuk mengukur apakah sinyal ini memang menghasilkan.
# Harga dicek tiap scan, jadi di GitHub Actions (tiap ~15 menit) TP/SL bisa
# "kelewat" jauh; hasil nyata dengan bot cepat bisa lebih baik ATAU lebih buruk.

def paper_open(st, p, cfg, now_ms):
    pp = st["paper"]
    addr = p["baseToken"]["address"]
    price = float(p.get("priceUsd") or 0)
    if not price or addr in pp["open"] or pp["balance"] < cfg["stake"]:
        return
    if now_ms - pp.get("closed", {}).get(addr, 0) < cfg["cooldown_h"] * 3_600_000:
        return  # jangan langsung beli lagi coin yang baru ditutup
    pp["balance"] -= cfg["stake"]
    pp["open"][addr] = {
        "sym": (p.get("baseToken") or {}).get("symbol", "?"),
        "entry": price, "usd": cfg["stake"], "t": now_ms,
        "liq": _n(p, "liquidity", "usd"), "pool": p.get("pairAddress", ""), "checked": now_ms,
        "tp": price * (1 + cfg["tp_pct"] / 100), "sl": price * (1 - cfg["sl_pct"] / 100),
    }


def touched(pos, rows, price):
    """Cek high/low candle sejak cek terakhir, bukan cuma harga sekarang, supaya
    TP/SL yang kesentuh di antara dua scan tetap tercatat. Kalau TP dan SL kena di
    candle yang sama, anggap SL (asumsi terburuk). Return (alasan, harga isi)."""
    since = pos.get("checked", pos["t"]) / 1000 - 300  # candle 5m yang sedang berjalan ikut
    for r in rows:
        if r[0] < since:
            continue
        hi, lo = float(r[2]), float(r[3])
        if lo <= pos["sl"]:
            return "🛑 SL", pos["sl"]
        if hi >= pos["tp"]:
            return "🎯 TP", pos["tp"]
    if price >= pos["tp"]:
        return "🎯 TP", price
    if price <= pos["sl"]:
        return "🛑 SL", price
    return None, price


def paper_update(st, cfg, now_ms):
    """Tutup posisi yang kena TP/SL/timeout/likuiditas ditarik. Return list pesan."""
    pp, msgs = st["paper"], []
    if not pp["open"]:
        return msgs
    live = {q["baseToken"]["address"]: q for q in best_pairs(cfg["chain"], list(pp["open"]))}
    for addr, pos in list(pp["open"].items()):
        q = live.get(addr)
        if not q:
            continue  # API gagal / pair hilang dari daftar: jangan tebak, cek lagi scan berikutnya
        price = float(q.get("priceUsd") or 0)
        liq = _n(q, "liquidity", "usd")
        reason = None
        if liq < pos["liq"] * 0.3:
            reason, price = "🪤 likuiditas hilang (rug)", price * 0.1  # anggap hampir nol
        else:
            reason, hit = touched(pos, candles(cfg["chain"], pos.get("pool", "")), price)
            if reason:
                price = hit
        if reason:
            pass
        elif now_ms - pos["t"] > cfg["max_hold_h"] * 3_600_000:
            reason = "⏱ waktu habis"
        pos["checked"] = now_ms
        if not reason:
            continue
        gross = pos["usd"] * price / pos["entry"]
        net = gross * (1 - cfg["cost_pct"] / 100) ** 2 if gross else 0
        pnl = net - pos["usd"]
        pp["balance"] += net
        pp["wins" if pnl > 0 else "losses"] += 1
        del pp["open"][addr]
        pp.setdefault("closed", {})[addr] = now_ms
        msgs.append(f"{'✅' if pnl > 0 else '❌'} {html.escape(pos['sym'])} ditutup ({reason}): "
                    f"harga {price / pos['entry'] - 1:+.0%}, bersih setelah biaya {pnl:+.2f} USD "
                    f"({pnl / pos['usd']:+.0%})")
    return msgs


def paper_summary(st):
    pp = st["paper"]
    held = sum(x["usd"] for x in pp["open"].values())
    n = pp["wins"] + pp["losses"]
    wr = f"{pp['wins'] / n:.0%}" if n else "-"
    return (f"💼 <b>Paper</b>: saldo ${pp['balance']:.2f} + ${held:.2f} di {len(pp['open'])} posisi "
            f"(modal awal ${pp['start']:.0f}) · menang {pp['wins']} / kalah {pp['losses']} · winrate {wr}")


# ---------------------------------------------------------------- main loop

def load_state(path, cfg):
    try:
        with open(path) as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    if "seen" not in st:  # format lama: {alamat: waktu}
        st = {"seen": st}
    st.setdefault("paper", {"start": cfg["paper_start"], "balance": cfg["paper_start"],
                            "open": {}, "wins": 0, "losses": 0})
    return st


def save_state(path, state):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def scan(cfg, state, use_rugcheck=True, use_ta=True):
    now_ms = time.time() * 1000
    closed = paper_update(state, cfg, now_ms)
    if closed:
        text = "\n".join(["📒 <b>Update paper trade</b>", *closed, "", paper_summary(state)])
        print(text)
        send_telegram(text)
    addrs = candidate_tokens(cfg["chain"])
    pairs = best_pairs(cfg["chain"], addrs)
    picked = []
    for p in pairs:
        score, good, flags, reject = assess(p, now_ms, cfg)
        if reject or score < cfg["min_score"]:
            continue
        addr = p["baseToken"]["address"]
        last = state["seen"].get(addr, 0)
        if now_ms - last < cfg["cooldown_h"] * 3_600_000:
            continue
        picked.append([p, score, good, flags])

    picked.sort(key=lambda x: -x[1])
    final = []  # RugCheck + TA hanya untuk kandidat teratas, hemat rate limit
    for item in picked:  # RugCheck hanya untuk kandidat lolos, hemat request
        if len(final) >= cfg["top"]:
            break
        if use_rugcheck and cfg["chain"] == "solana":
            item[1], reject = apply_rugcheck(rugcheck(item[0]["baseToken"]["address"]), item[1], item[3])
            if reject or item[1] < cfg["min_score"]:
                continue
        if use_ta:
            d, g, f = technicals(candles(cfg["chain"], item[0].get("pairAddress", "")))
            item[1] = max(0, min(100, item[1] + d))
            item[2] += g
            item[3] += f
            if item[1] < cfg["min_score"]:
                continue
        final.append(item)

    print(f"[{time.strftime('%H:%M:%S')}] {len(addrs)} token dicek, {len(pairs)} pair, {len(final)} lolos",
          file=sys.stderr)
    if not final:
        return state
    if not cfg.get("no_paper"):
        for p, *_ in final:
            paper_open(state, p, cfg, now_ms)
    footer = "" if cfg.get("no_paper") else paper_summary(state)
    text = render(final, cfg["chain"], cfg, footer)
    print(text)
    sent = send_telegram(text)
    if sent or not os.getenv("TELEGRAM_BOT_TOKEN"):
        for p, *_ in final:
            state["seen"][p["baseToken"]["address"]] = now_ms
    return state


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for k, v in DEFAULTS.items():
        ap.add_argument("--" + k.replace("_", "-"), type=type(v), default=v)
    ap.add_argument("--loop", type=int, default=0, help="detik antar scan; 0 = sekali saja")
    ap.add_argument("--no-rugcheck", action="store_true")
    ap.add_argument("--no-ta", action="store_true", help="matikan analisa candle (EMA/RSI/volume)")
    ap.add_argument("--no-paper", action="store_true", help="matikan simulasi paper trading")
    ap.add_argument("--state", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json"))
    a = ap.parse_args()
    cfg = {k: getattr(a, k) for k in DEFAULTS}
    cfg["no_paper"] = a.no_paper
    if a.loop and a.loop < 60:
        ap.error("--loop minimal 60 detik (batas rate DexScreener ~60 req/menit)")

    state = load_state(a.state, cfg)
    global _CHAT
    _CHAT = os.getenv("TELEGRAM_CHAT_ID") or state.get("tg_chat")
    if os.getenv("TELEGRAM_BOT_TOKEN") and not _CHAT:
        # Run pertama setelah token dipasang: langsung sapa, jangan tunggu ada sinyal.
        send_telegram("👋 memescan aktif. Sinyal dan update paper trade akan masuk ke sini.\n\n"
                      + paper_summary(state))
        if _CHAT:
            state["tg_chat"] = _CHAT
            save_state(a.state, state)
    while True:
        try:
            state = scan(cfg, state, not a.no_rugcheck, not a.no_ta)
            cutoff = time.time() * 1000 - 7 * 86_400_000
            state["seen"] = {k: v for k, v in state["seen"].items() if v > cutoff}
            if _CHAT:
                state["tg_chat"] = _CHAT
            save_state(a.state, state)
        except Exception as e:  # loop harus tetap hidup walau satu scan gagal
            print(f"[error] {e!r}", file=sys.stderr)
        if not a.loop:
            break
        time.sleep(a.loop)


if __name__ == "__main__":
    main()

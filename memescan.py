#!/usr/bin/env python3
"""memescan: sniper memecoin pump.fun (Solana), MODE PAPER SAJA.

Mengikuti spesifikasi MemeSniper:
  gate cepat (detik 6-60) -> filter holder (+cek ulang 5 detik) -> kandidat
  gate lambat (tiap 15 detik s/d 30 menit) untuk koin yang naik pelan
  skor 0-100% dari regresi logistik yang dikalibrasi (`memescan.py calibrate`)
  TP 50% di 2x, sisanya trailing; SL -35%; time stop; koin basi
  simulasi realistis: jeda eksekusi 3 detik, harga dari kurva bonding,
  slippage, fee pump.fun, priority fee

TIDAK ADA mode live. Bot ini tidak pernah menyentuh private key dan tidak
pernah mengirim transaksi. Selama ambang skor belum terbukti di data validasi
(SCORE_ALLIN_MIN / SCORE_HALF_MIN = kosong), saldo paper tidak dipakai beli;
setiap kandidat hanya dicatat dan diberi "shadow trade" untuk mengukur hasil.

Pakai:
    python3 memescan.py                 # jalan terus (systemd / Termux)
    python3 memescan.py --resume        # lanjut setelah auto-stop saldo minimum
    python3 memescan.py --duration 300  # jalan 5 menit lalu berhenti (tes)
    python3 memescan.py status          # ringkasan hasil
    python3 memescan.py calibrate       # latih skor + uji ambang di data hold-out
    python3 memescan.py setup           # simpan token bot, chat id, RPC ke .env

Butuh: Python 3.9+ dan `pip install websockets`.
"""
import argparse
import asyncio
import base64
import collections
import html
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUBLIC_RPC_WS = "wss://api.mainnet-beta.solana.com"
SOL_MINT = "So11111111111111111111111111111111111111112"
SUPPLY = 1_000_000_000      # supply token pump.fun (unit UI)
VIRTUAL_SOL = 30.0          # SOL virtual awal di kurva bonding

# ---------------------------------------------------------------- konfigurasi
# Semua angka bisa diubah lewat .env (nama sama, huruf besar).
DEFAULTS = {
    # gate cepat
    "FAST_MIN_AGE": 6.0, "FAST_MAX_AGE": 60.0, "FAST_EVERY": 1.5,
    "FAST_INFLOW": 1.0, "FAST_GROWTH": 1.05, "FAST_MCAP_MAX": 150.0, "FAST_DD": 0.20,
    # filter holder
    "HOLD_MIN": 5, "TOP10_MAX": 0.35, "TOP20_MAX": 0.50, "DEV_MAX": 0.10, "HOLD_RECHECK": 5.0,
    # gate lambat
    "SLOW_EVERY": 15.0, "SLOW_MAX_AGE": 1800.0, "SLOW_WINDOW": 180.0,
    "SLOW_GROWTH": 1.5, "SLOW_INFLOW": 2.5, "SLOW_LIQ": 12.0, "SLOW_DD": 0.10,
    # eksekusi simulasi
    "EXEC_DELAY": 3.0, "SLIPPAGE": 0.02, "FEE_PCT": 0.0125, "PRIORITY_FEE": 0.0005,
    # aturan jual
    "TP1_X": 2.0, "TP1_FRAC": 0.5, "TRAIL": 0.45, "TRAIL_TIGHT_X": 6.0, "TRAIL_TIGHT": 0.35,
    "SL": 0.35, "TIME_STOP_S": 600.0, "TIME_STOP_X": 1.3, "STALE_S": 1200.0,
    # modal & ukuran posisi
    # saldo paper dalam USD; tiap beli ditukar ke SOL di harga SOL saat itu
    "START_USD": 100.0, "MIN_BALANCE_USD": 20.0, "PAPER_STAKE_USD": 10.0, "SHADOW_SOL": 0.5,
    "SCORE_ALLIN_MIN": None, "SCORE_HALF_MIN": None,
    # lain-lain
    "BUNDLE_WINDOW": 1.0, "PRUNE_AGE": 120.0, "PRUNE_INFLOW": 0.5, "IDLE_DROP": 300.0,
    "MAX_TRACKED": 800, "SUMMARY_EVERY_H": 1.0, "NOTIFY_CANDIDATES": 0, "NOTIFY_MAX_PER_H": 10,
    # rekam semua koin baru (data untuk menguji aturan beli lain), simpan sekian hari
    "RECORD": 1, "REC_KEEP_DAYS": 14,
    # 1 = beli paper ukuran tetap walau belum ada aturan yang terbukti (hasil 13 Okt: rugi)
    "PAPER_FLAT": 0,
}


def load_config(data_dir):
    env = {}
    path = os.path.join(data_dir, ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k.startswith("export "):
                        k = k[7:].strip()
                    env[k] = v.strip().strip("'\"")
    env.update({k: v for k, v in os.environ.items() if k in DEFAULTS or k.startswith("TELEGRAM") or k == "RPC_WS_URL"})
    cfg = {}
    for k, d in DEFAULTS.items():
        v = env.get(k)
        if v is None or v == "" or v.lower() in ("null", "none"):
            cfg[k] = d
        else:
            cfg[k] = int(float(v)) if isinstance(d, int) else float(v)
    cfg["RPC_WS_URL"] = env.get("RPC_WS_URL", "").strip()
    cfg["TELEGRAM_BOT_TOKEN"] = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    cfg["TELEGRAM_CHAT_ID"] = env.get("TELEGRAM_CHAT_ID", "").strip()
    return cfg


# ---------------------------------------------------------------- format

def fmt_bal(x):
    """Saldo/PnL dalam dolar dengan sen."""
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


def fmt_usd(x):
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if x >= div:
            return f"${x / div:.1f}{suf}"
    return f"${x:.0f}"


def fmt_price(x, cur="$"):
    if x >= 1:
        return f"{cur}{x:,.2f}"
    from decimal import Decimal
    return cur + format(Decimal(f"{x:.3g}"), "f")


def fetch_sol_usd():
    """Harga SOL dalam USD (CoinGecko, cadangan Kraken). None kalau gagal."""
    for url, pick in (("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd",
                       lambda d: d["solana"]["usd"]),
                      ("https://api.kraken.com/0/public/Ticker?pair=SOLUSD",
                       lambda d: next(iter(d["result"].values()))["c"][0])):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "memescan"})
            with urllib.request.urlopen(req, timeout=10) as r:
                v = float(pick(json.load(r)))
            if v > 0:
                return v
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, StopIteration):
            continue
    return None


# ---------------------------------------------------------------- statistik

def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def mean_ci(xs, z=1.96):
    n = len(xs)
    if n < 2:
        return (xs[0] if xs else 0.0), float("nan"), float("nan")
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, m - z * sd / math.sqrt(n), m + z * sd / math.sqrt(n)


# ---------------------------------------------------------------- kurva bonding

def curve_buy(v_sol, v_tok, sol_in):
    """Token yang didapat untuk sol_in (setelah fee) di kurva x*y=k."""
    return v_tok * sol_in / (v_sol + sol_in)


def curve_sell(v_sol, v_tok, tok_in):
    """SOL yang didapat untuk menjual tok_in (sebelum fee)."""
    return v_sol * tok_in / (v_tok + tok_in)


# ---------------------------------------------------------------- data token

# ---------------------------------------------------------------- rekaman semua koin
# Tiap koin baru direkam sampai 30 menit: candle harga (market cap SOL) + volume beli/jual,
# plus foto fitur di umur tertentu. Dipakai `research` untuk menguji aturan beli lain.

REC_SNAPS = (10, 20, 30, 45, 60, 90, 120, 180, 300, 600)


def rec_bucket(age):
    """Candle 5 dtk sampai umur 2 menit, 15 dtk sampai 10 menit, 60 dtk sampai 30 menit."""
    if age < 120:
        return int(max(0.0, age) // 5)
    if age < 600:
        return 24 + int((age - 120) // 15)
    return min(75, 56 + int((age - 600) // 60))


def rec_bucket_start(b):
    if b < 24:
        return b * 5.0
    if b < 56:
        return 120 + (b - 24) * 15.0
    return 600 + (b - 56) * 60.0


def rec_bucket_end(b):
    return rec_bucket_start(b + 1) if b < 75 else 1800.0


def sig(x, n=4):
    return float(f"{x:.{n}g}") if x else 0.0


class Token:
    def __init__(self, ev, now, bundle_window=1.0):
        self.mint = ev["mint"]
        self.bundle_window = bundle_window
        self.sym = str(ev.get("symbol") or "?")[:20]
        self.name = str(ev.get("name") or "")[:40]
        self.creator = ev.get("traderPublicKey") or ""
        self.t0 = now
        self.v_sol = float(ev.get("vSolInBondingCurve") or VIRTUAL_SOL)
        self.v_tok = float(ev.get("vTokensInBondingCurve") or 1.073e9)
        self.mcap = float(ev.get("marketCapSol") or 0)
        self.pool = ev.get("pool") or "pump"
        self.price0 = self.price
        self.peak = self.price
        dev_tok = float(ev.get("initialBuy") or 0)
        self.bal = {self.creator: dev_tok} if dev_tok else {}
        self.dev_max = dev_tok
        self.dev_sold_flag = False
        self.inflow = self.liq   # SOL bersih yang masuk kurva (dari cadangan, tetap benar walau ada event terlewat)
        self.buyers = set()
        self.n_buys = self.n_sells = 0
        self.bundle = 0
        self.last_trade = now
        self.hist = [(now, self.price, self.inflow)]     # (t, harga, inflow kumulatif)
        self.next_fast = now + 0.0
        self.next_slow = now + 60.0
        self.recheck_at = None
        self.recheck_gate = None
        self.decided = False
        self.rec_c = {}            # candle: bucket -> [high, low, close, sol beli, sol jual, n beli, n jual]
        self.rec_snaps = []
        self.rec_next = 0
        self.rec_cand = None

    @property
    def price(self):
        return self.v_sol / self.v_tok if self.v_tok else 0.0

    @property
    def liq(self):
        return max(0.0, self.v_sol - VIRTUAL_SOL)

    def age(self, now):
        return now - self.t0

    def on_trade(self, ev, now):
        sol = float(ev.get("solAmount") or 0)
        trader = ev.get("traderPublicKey") or ""
        side = ev.get("txType")
        if ev.get("marketCapSol") is not None:
            self.mcap = float(ev["marketCapSol"])
        if ev.get("vSolInBondingCurve") is not None and ev.get("vTokensInBondingCurve"):
            self.v_sol = float(ev["vSolInBondingCurve"])
            self.v_tok = float(ev["vTokensInBondingCurve"])
        elif self.mcap > 0:
            # Pool sudah migrasi (tanpa data kurva): harga dari market cap, kedalaman
            # dianggap sama dengan cadangan SOL terakhir (perkiraan slippage).
            self.v_tok = self.v_sol / (self.mcap / SUPPLY)
        self.pool = ev.get("pool") or self.pool
        if side == "buy":
            self.n_buys += 1
            if trader != self.creator:
                self.buyers.add(trader)
                if now - self.t0 <= self.bundle_window:
                    self.bundle += 1
        elif side == "sell":
            self.n_sells += 1
        if ev.get("newTokenBalance") is not None and trader:
            self.bal[trader] = float(ev["newTokenBalance"])
            if trader == self.creator:
                self.dev_max = max(self.dev_max, self.bal[trader])
        self.inflow = self.liq
        self.peak = max(self.peak, self.price)
        self.last_trade = now
        self.hist.append((now, self.price, self.inflow))
        if len(self.hist) > 50 and now - self.hist[0][0] > 400:
            self.hist = [h for h in self.hist if now - h[0] <= 400]

    # --- ukuran-ukuran untuk gate & skor
    def holders(self):
        return sorted((b for b in self.bal.values() if b > 0), reverse=True)

    def top_pct(self, n):
        return sum(self.holders()[:n]) / SUPPLY

    def dev_pct(self):
        return self.bal.get(self.creator, 0.0) / SUPPLY

    def dev_sold_all(self):
        return self.dev_max > 0 and self.bal.get(self.creator, 0.0) <= self.dev_max * 0.01

    def dd(self):
        return 1 - self.price / self.peak if self.peak else 0.0

    def window(self, now, secs):
        """(harga awal jendela, inflow dalam jendela)."""
        start = now - secs
        p0, f0 = self.hist[0][1], self.hist[0][2]
        for t, p, f in self.hist:
            if t > start:
                break
            p0, f0 = p, f
        return p0, self.inflow - f0


FEATURES = [
    "age_s", "inflow_sol", "inflow_rate", "unique_buyers", "buyer_rate", "holders",
    "top10", "top20", "dev_pct", "dev_sold_any", "creator_prev_tokens", "creator_prev_rugs",
    "bundle", "mcap_sol", "liq_sol", "growth", "drawdown", "buy_sell_ratio",
]


def features(tok, now, creators, gate):
    age = max(tok.age(now), 1e-6)
    c = creators.get(tok.creator, {})
    return {
        "age_s": age, "inflow_sol": tok.inflow, "inflow_rate": tok.inflow / age,
        "unique_buyers": len(tok.buyers), "buyer_rate": len(tok.buyers) / age,
        "holders": len(tok.holders()), "top10": tok.top_pct(10), "top20": tok.top_pct(20),
        "dev_pct": tok.dev_pct(), "dev_sold_any": float(tok.bal.get(tok.creator, 0) < tok.dev_max * 0.99),
        "creator_prev_tokens": c.get("tokens", 1) - 1, "creator_prev_rugs": c.get("rugs", 0),
        "bundle": tok.bundle, "mcap_sol": tok.mcap, "liq_sol": tok.liq,
        "growth": tok.price / tok.price0 if tok.price0 else 0.0, "drawdown": tok.dd(),
        "buy_sell_ratio": tok.n_buys / max(1, tok.n_buys + tok.n_sells),
        "_gate": gate,
    }


def score(model, feats):
    """Peluang menang 0-1 dari model terkalibrasi, None kalau belum ada model."""
    if not model:
        return None
    z = model["bias"]
    for k, w, mu, sd in zip(model["features"], model["weights"], model["mean"], model["std"]):
        z += w * ((feats.get(k, 0.0) - mu) / sd)
    return 1 / (1 + math.exp(-max(-30, min(30, z))))


# ---------------------------------------------------------------- posisi simulasi

class Position:
    """Posisi simulasi. Semua order diisi EXEC_DELAY detik setelah keputusan,
    pakai cadangan kurva saat itu + slippage + fee + priority fee."""

    def __init__(self, cand_id, tok, size_sol, kind, now, cfg):
        self.id, self.mint, self.sym, self.kind = cand_id, tok.mint, tok.sym, kind
        self.size = size_sol
        self.cfg = cfg
        self.tokens = 0.0
        self.cost = 0.0
        self.out = 0.0
        self.entry_px = None
        self.peak_x = 1.0
        self.tp1_done = False
        self.won = False
        self.opened = now
        self.pending = [("buy", now + cfg["EXEC_DELAY"], 1.0, "entry")]
        self.closed = False
        self.reason = ""
        self.cost_usd, self.sol_usd = 0.0, None   # khusus posisi paper

    def x(self, tok):
        return tok.price / self.entry_px if self.entry_px else 1.0

    def _fill(self, tok, side, frac):
        c = self.cfg
        fee, slip, prio = c["FEE_PCT"], c["SLIPPAGE"], c["PRIORITY_FEE"]
        if side == "buy":
            sol_in = self.size * (1 - fee)
            got = curve_buy(tok.v_sol, tok.v_tok, sol_in) * (1 - slip)
            self.tokens, self.cost = got, self.size + prio
            self.entry_px = self.cost / got if got else None
        else:
            amt = self.tokens * frac
            sol = curve_sell(tok.v_sol, tok.v_tok, amt) * (1 - slip) * (1 - fee) - prio
            self.tokens -= amt
            self.out += max(0.0, sol)

    def step(self, tok, now):
        """Proses order yang jatuh tempo, lalu cek pemicu jual. Return True kalau baru ditutup."""
        c = self.cfg
        due = [p for p in self.pending if p[1] <= now]
        self.pending = [p for p in self.pending if p[1] > now]
        for side, _, frac, why in due:
            self._fill(tok, side, frac)
            if side == "sell" and why == "tp1" and self.x(tok) >= 1.0:
                self.won = True  # TP 2x tercapai sebelum SL/time stop
            if side == "sell" and frac >= 1.0:
                self.closed, self.reason = True, why
                return True
        if self.entry_px is None or any(p[0] == "sell" and p[2] >= 1.0 for p in self.pending):
            return False
        x = self.x(tok)
        self.peak_x = max(self.peak_x, x)
        held = now - self.opened
        sell_all = None
        if x <= 1 - c["SL"]:
            sell_all = "sl"
        elif not self.tp1_done and x >= c["TP1_X"]:
            self.tp1_done = True
            self.pending.append(("sell", now + c["EXEC_DELAY"], c["TP1_FRAC"], "tp1"))
        elif self.tp1_done:
            trail = c["TRAIL_TIGHT"] if self.peak_x >= c["TRAIL_TIGHT_X"] else c["TRAIL"]
            if x <= self.peak_x * (1 - trail):
                sell_all = "trailing"
        if not sell_all and held >= c["TIME_STOP_S"] and self.peak_x < c["TIME_STOP_X"]:
            sell_all = "time_stop"
        if not sell_all and now - tok.last_trade >= c["STALE_S"]:
            sell_all = "basi"
        if sell_all:
            self.pending.append(("sell", now + c["EXEC_DELAY"], 1.0, sell_all))
        return False

    @property
    def multiple(self):
        return self.out / self.cost if self.cost else 0.0


# ---------------------------------------------------------------- telegram

class Telegram:
    def __init__(self, cfg):
        self.token, self.chat = cfg["TELEGRAM_BOT_TOKEN"], cfg["TELEGRAM_CHAT_ID"]

    def send(self, text):
        if not (self.token and self.chat):
            print("[tg]", text.replace("\n", " | ")[:300])
            return
        data = urllib.parse.urlencode({"chat_id": self.chat, "text": text, "parse_mode": "HTML",
                                       "disable_web_page_preview": "true"}).encode()
        for _ in range(3):
            try:
                urllib.request.urlopen(f"https://api.telegram.org/bot{self.token}/sendMessage", data, timeout=20)
                return
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    print(f"[warn] telegram HTTP {e.code}: {e.read()[:200]!r}", file=sys.stderr)
                    return
                try:
                    wait = json.loads(e.read())["parameters"]["retry_after"]
                except (ValueError, KeyError, TypeError):
                    wait = 5
                time.sleep(min(float(wait), 60))
            except (urllib.error.URLError, OSError) as e:
                print(f"[warn] telegram: {e}", file=sys.stderr)
                return

    async def asend(self, text):
        await asyncio.get_running_loop().run_in_executor(None, self.send, text)


# ---------------------------------------------------------------- mesin utama

class Engine:
    def __init__(self, cfg, data_dir, tg, model=None):
        self.cfg, self.dir, self.tg, self.model = cfg, data_dir, tg, model
        self.tokens = {}
        self.positions = []          # shadow + portfolio yang masih terbuka
        self.outbox = []             # pesan telegram yang menunggu dikirim
        self.stats = {"create": 0, "trade": 0, "cepat": 0, "lambat": 0, "recheck_gagal": 0}
        st = self._load("state.json", {})
        self.seen = dict.fromkeys(st.get("seen", []))  # mint yang pernah jadi kandidat (urut waktu)
        self.creators = self._load("creators.json", {})
        self.port = st.get("portfolio")
        reset = self.port is not None and "usd" not in self.port
        if self.port is None or reset:
            self.port = {"usd": cfg["START_USD"], "start_usd": cfg["START_USD"], "stopped": False,
                         "since": time.time()}
        self.n_cand = st.get("n_cand", 0)
        self.last_summary = st.get("last_summary", time.time())
        self._recover_from = st
        self.last_welcome = st.get("last_welcome", 0)
        self.tg_chat = st.get("tg_chat", "")
        self.notified = set()
        self.n_rec = st.get("n_rec", 0)
        self.rec_cleanup()
        self.sol_usd = None
        if reset:   # saldo lama dalam SOL (sebelum modal $100) tidak dipakai lagi
            self.outbox.append(f"♻️ Modal paper direset ke {fmt_bal(cfg['START_USD'])}. "
                               "Saldo dan posisi paper lama dihapus.")
        else:
            self.recover(self._recover_from)
        del self._recover_from
        self.orphans, self.orphan_q = {}, collections.deque()
        self.sample = set()        # id kandidat yang dikirim ke Telegram
        self.hour_start, self.n_hour, self.suppressed = time.time(), 0, 0

    # --- persistensi
    def _load(self, name, default):
        try:
            with open(os.path.join(self.dir, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return default

    def _save(self, name, obj):
        p = os.path.join(self.dir, name)
        with open(p + ".tmp", "w") as f:
            json.dump(obj, f)
        os.replace(p + ".tmp", p)

    def open_paper(self):
        """Posisi paper terbuka + nilainya dalam USD kalau dijual sekarang (untuk pemulihan)."""
        out = []
        for p in self.positions:
            if p.kind != "portfolio":
                continue
            tok = self.tokens.get(p.mint)
            px = self.sol_usd or p.sol_usd
            if p.entry_px is None:
                value = p.cost_usd                  # order beli belum terisi: uang kembali
            else:
                sol = p.out
                if tok and p.tokens:
                    c = self.cfg
                    sol += max(0.0, curve_sell(tok.v_sol, tok.v_tok, p.tokens) * (1 - c["SLIPPAGE"])
                               * (1 - c["FEE_PCT"]) - c["PRIORITY_FEE"])
                value = sol * px
            out.append({"id": p.id, "mint": p.mint, "sym": p.sym, "cost_usd": p.cost_usd,
                        "cost": p.cost or p.size, "value_usd": value, "opened": p.opened})
        return out

    def save_state(self):
        self._save("state.json", {"seen": list(self.seen)[-50000:], "portfolio": self.port,
                                  "n_cand": self.n_cand, "last_summary": self.last_summary,
                                  "last_welcome": self.last_welcome, "tg_chat": self.tg_chat,
                                  "n_rec": self.n_rec,
                                  "open_paper": self.open_paper()})

    def recover(self, st):
        """Bot sebelumnya mati mendadak dengan posisi paper terbuka: tutup di nilai terakhir
        yang tersimpan (paling lama 60 detik sebelumnya) supaya saldo tetap benar."""
        now = time.time()
        for o in st.get("open_paper") or []:
            got = o["value_usd"]
            self.port["usd"] += got
            mult = got / o["cost_usd"] if o["cost_usd"] else 0.0
            self.log({"id": o["id"], "t": now, "mint": o["mint"], "kind": "portfolio", "outcome": {
                "won": False, "multiple": round(mult, 4), "reason": "bot mati mendadak", "peak_x": None,
                "held_s": round(now - o["opened"], 1), "usd_cost": o["cost_usd"], "usd_out": got}})
            self.outbox.append(f"⚠️ <b>{html.escape(o['sym'])}</b> #{o['id']}: bot sempat mati mendadak, "
                               f"posisi paper ditutup di nilai terakhir {fmt_bal(got - o['cost_usd'])}. "
                               f"💼 Sisa saldo {fmt_bal(self.port['usd'])}")

    def save(self):
        self.save_state()
        if len(self.creators) > 200000:
            self.creators = dict(list(self.creators.items())[-100000:])
        self._save("creators.json", self.creators)

    def log(self, rec):
        with open(os.path.join(self.dir, "candidates.jsonl"), "a") as f:
            f.write(json.dumps(rec) + "\n")

    # --- event dari websocket
    def on_create(self, ev, now):
        """Return True kalau token baru (perlu subscribe trade-nya)."""
        mint = ev.get("mint")
        if not mint or mint in self.tokens or mint in self.seen:
            return False
        self.stats["create"] += 1
        tok = Token(ev, now, self.cfg["BUNDLE_WINDOW"])
        self.tokens[mint] = tok
        c = self.creators.setdefault(tok.creator, {"tokens": 0, "rugs": 0})
        c["tokens"] += 1
        return True

    def on_trade(self, ev, now):
        tok = self.tokens.get(ev.get("mint"))
        if not tok:
            return
        self.stats["trade"] += 1
        was_sold = tok.dev_sold_flag
        tok.on_trade(ev, now)
        if self.cfg["RECORD"]:
            self.rec_trade(tok, ev, now)
        if not was_sold and tok.dev_max > 0 and tok.bal.get(tok.creator, 0) <= tok.dev_max * 0.1:
            tok.dev_sold_flag = True
            self.creators.setdefault(tok.creator, {"tokens": 1, "rugs": 0})["rugs"] += 1

    # --- rekaman
    def rec_cleanup(self):
        d = os.path.join(self.dir, "rec")
        if not os.path.isdir(d):
            return
        keep = time.strftime("%Y%m%d", time.gmtime(time.time() - self.cfg["REC_KEEP_DAYS"] * 86400))
        for fn in os.listdir(d):
            if fn.startswith("rec-") and fn[4:12] < keep:
                os.remove(os.path.join(d, fn))

    def rec_trade(self, tok, ev, now):
        m = tok.price * SUPPLY
        b = rec_bucket(tok.age(now))
        c = tok.rec_c.get(b)
        if c is None:
            c = tok.rec_c[b] = [m, m, m, 0.0, 0.0, 0, 0]
        c[0], c[1], c[2] = max(c[0], m), min(c[1], m), m
        sol = float(ev.get("solAmount") or 0)
        if ev.get("txType") == "buy":
            c[3] += sol
            c[5] += 1
        else:
            c[4] += sol
            c[6] += 1

    def rec_snap(self, tok, now):
        age = tok.age(now)
        while tok.rec_next < len(REC_SNAPS) and age >= REC_SNAPS[tok.rec_next]:
            a = REC_SNAPS[tok.rec_next]
            tok.rec_next += 1
            if age - a <= 2.0:     # foto telat (bot sempat tersendat) tidak dipakai
                f = features(tok, now, self.creators, "")
                tok.rec_snaps.append([a, sig(tok.price * SUPPLY)] + [sig(f[k]) for k in FEATURES])

    def rec_write(self, tok, now, why):
        if not self.cfg["RECORD"]:
            return
        d = os.path.join(self.dir, "rec")
        os.makedirs(d, exist_ok=True)
        rec = {"m": tok.mint, "s": tok.sym, "t0": round(tok.t0, 1), "m0": sig(tok.price0 * SUPPLY),
               "snaps": tok.rec_snaps,
               "c": [[b] + [sig(v) for v in c[:5]] + c[5:] for b, c in sorted(tok.rec_c.items())],
               "end": round(min(tok.age(now), 1800.0), 1), "why": why, "cand": tok.rec_cand}
        with open(os.path.join(d, time.strftime("rec-%Y%m%d.jsonl", time.gmtime(tok.t0))), "a") as f:
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        self.n_rec += 1

    # --- filter
    def holder_ok(self, tok):
        c = self.cfg
        if tok.dev_sold_all():
            return False, "dev sudah jual semua"
        if len(tok.holders()) < c["HOLD_MIN"]:
            return False, "holder kurang"
        if tok.top_pct(10) > c["TOP10_MAX"]:
            return False, "top10 terlalu besar"
        if tok.top_pct(20) > c["TOP20_MAX"]:
            return False, "top20 terlalu besar"
        if tok.dev_pct() > c["DEV_MAX"]:
            return False, "dev pegang terlalu banyak"
        return True, ""

    def fast_ok(self, tok):
        c = self.cfg
        return (tok.inflow >= c["FAST_INFLOW"] and tok.price >= tok.price0 * c["FAST_GROWTH"]
                and tok.mcap <= c["FAST_MCAP_MAX"] and tok.dd() <= c["FAST_DD"])

    def slow_ok(self, tok, now):
        c = self.cfg
        p0, inflow_w = tok.window(now, c["SLOW_WINDOW"])
        return (p0 > 0 and tok.price / p0 >= c["SLOW_GROWTH"] and inflow_w >= c["SLOW_INFLOW"]
                and tok.liq >= c["SLOW_LIQ"] and tok.dd() <= c["SLOW_DD"])

    # --- detak jam: gate, order, exit, pruning
    def tick(self, now):
        c = self.cfg
        for tok in list(self.tokens.values()):
            if c["RECORD"] and tok.rec_next < len(REC_SNAPS):
                self.rec_snap(tok, now)
            if tok.decided:
                continue
            age = tok.age(now)
            if tok.recheck_at is not None:
                if now >= tok.recheck_at:
                    ok, why = self.holder_ok(tok)
                    gate = tok.recheck_gate
                    tok.recheck_at = tok.recheck_gate = None
                    # harga/drawdown juga harus masih lolos, bukan cuma holder
                    ok = ok and (self.fast_ok(tok) if gate == "cepat" else self.slow_ok(tok, now))
                    if ok:
                        self.candidate(tok, now, gate)
                    else:
                        self.stats["recheck_gagal"] += 1
                continue
            if c["FAST_MIN_AGE"] <= age <= c["FAST_MAX_AGE"] and now >= tok.next_fast:
                tok.next_fast = now + c["FAST_EVERY"]
                if self.fast_ok(tok):
                    ok, why = self.holder_ok(tok)
                    self.stats["cepat"] += 1
                    if not ok:
                        self.stats[why] = self.stats.get(why, 0) + 1
                        continue
                    tok.recheck_at, tok.recheck_gate = now + c["HOLD_RECHECK"], "cepat"
                    continue
            if c["FAST_MAX_AGE"] < age <= c["SLOW_MAX_AGE"] and now >= tok.next_slow:
                tok.next_slow = now + c["SLOW_EVERY"]
                if self.slow_ok(tok, now):
                    ok, why = self.holder_ok(tok)
                    self.stats["lambat"] += 1
                    if not ok:
                        self.stats[why] = self.stats.get(why, 0) + 1
                        continue
                    tok.recheck_at, tok.recheck_gate = now + c["HOLD_RECHECK"], "lambat"

        for pos in list(self.positions):
            tok = self.tokens.get(pos.mint)
            if not tok:
                continue
            done = pos.step(tok, now)
            if pos.kind == "portfolio" and pos.entry_px and not getattr(pos, "announced", False):
                pos.announced = True
                self.outbox.append(self.entry_msg(pos, tok, now))
                self.save_state()
            if done:
                self.positions.remove(pos)
                self.close(pos, now)
                if pos.kind == "portfolio":
                    self.save_state()

        self.prune(now)
        if now - self.last_summary >= c["SUMMARY_EVERY_H"] * 3600:
            self.last_summary = now
            self.outbox.append(self.summary())

    def flush(self, now):
        """Bot berhenti (misal ganti run GitHub): posisi paper yang masih terbuka dijual di
        harga saat itu supaya saldo tidak hilang; order beli yang belum terisi dibatalkan."""
        for pos in [p for p in self.positions if p.kind == "portfolio"]:
            tok = self.tokens.get(pos.mint)
            self.positions.remove(pos)
            if pos.entry_px is None or not tok:
                self.port["usd"] += pos.cost_usd if pos.entry_px is None else pos.out * (self.sol_usd or pos.sol_usd)
                continue
            pos._fill(tok, "sell", 1.0)
            pos.closed, pos.reason = True, "bot berhenti"
            self.close(pos, now)
        for tok in self.tokens.values():
            self.rec_write(tok, now, "run selesai")
        self.tokens = {}

    def prune(self, now):
        c = self.cfg
        held = {p.mint for p in self.positions}
        drop = {}
        for m, tok in self.tokens.items():
            if m in held:
                continue
            age = tok.age(now)
            if age > c["SLOW_MAX_AGE"]:
                drop[m] = "30 menit"
            elif now - tok.last_trade > c["IDLE_DROP"]:
                drop[m] = "sepi"
            elif age > c["PRUNE_AGE"] and tok.inflow < c["PRUNE_INFLOW"]:
                drop[m] = "inflow kecil"
            elif tok.decided and not c["RECORD"]:
                drop[m] = "kandidat"
        if len(self.tokens) - len(drop) > c["MAX_TRACKED"]:
            rest = sorted((t for m, t in self.tokens.items() if m not in drop and m not in held),
                          key=lambda t: t.inflow)
            for t in rest[:len(self.tokens) - len(drop) - int(c["MAX_TRACKED"])]:
                drop[t.mint] = "batas memori"
        for m, why in drop.items():
            tok = self.tokens.pop(m, None)
            if tok:
                self.rec_write(tok, now, why)

    # --- kandidat & posisi
    def candidate(self, tok, now, gate):
        tok.decided = True
        tok.rec_cand = [gate, round(tok.age(now), 1)]
        self.seen[tok.mint] = None  # tidak pernah dibeli ulang
        self.n_cand += 1
        feats = features(tok, now, self.creators, gate)
        s = score(self.model, feats)
        rec = {"id": self.n_cand, "t": now, "mint": tok.mint, "sym": tok.sym, "gate": gate,
               "score": s, "features": feats}
        self.log(rec)
        self.positions.append(Position(self.n_cand, tok, self.cfg["SHADOW_SOL"], "shadow", now, self.cfg))
        size, why = self.sizing(s)
        if size:
            # total SOL yang keluar (termasuk priority fee) = size USD / harga SOL
            sol = size / self.sol_usd - self.cfg["PRIORITY_FEE"]
            pos = Position(self.n_cand, tok, sol, "portfolio", now, self.cfg)
            pos.cost_usd, pos.sol_usd = size, self.sol_usd
            pos.signal = (gate, s, feats)
            self.positions.append(pos)
            self.save_state()   # saldo langsung tersimpan
            return              # pesan dikirim waktu order beli terisi
        if now - self.hour_start >= 3600:
            self.hour_start, self.n_hour = now, 0
        if self.cfg["NOTIFY_CANDIDATES"] and self.n_hour >= self.cfg["NOTIFY_MAX_PER_H"]:
            self.suppressed += 1     # batas pesan per jam, tetap dicatat & disimulasikan
        elif self.cfg["NOTIFY_CANDIDATES"]:
            self.n_hour += 1
            self.notified.add(self.n_cand)
            self.outbox.append(self.signal_msg(tok, now, gate, s, why, feats))

    def usd(self, sol):
        return sol * self.sol_usd if self.sol_usd else None

    def money(self, sol):
        """Nilai SOL ditampilkan dalam USD kalau harga SOL tersedia."""
        u = self.usd(sol)
        return fmt_usd(u) if u is not None else f"{sol:.1f} SOL"

    def px(self, price_sol):
        u = self.usd(price_sol)
        return fmt_price(u) if u is not None else fmt_price(price_sol, "") + " SOL"

    def entry_msg(self, pos, tok, now):
        e, c = html.escape, self.cfg
        gate, s, feats = pos.signal
        p = pos.entry_px                    # harga rata-rata isi, termasuk fee & slippage
        sc = f"{s:.0%}" if s is not None else "belum dikalibrasi"
        flags = []
        if tok.bundle >= 3:
            flags.append(f"bundle {tok.bundle}")
        if feats["dev_sold_any"]:
            flags.append("dev sudah jual sebagian")
        if feats["creator_prev_rugs"]:
            flags.append(f"pembuat pernah dump {feats['creator_prev_rugs']}x")
        lines = [f"🟢 <b>BELI (paper) {e(tok.sym)}</b> #{pos.id} · gate {gate} · skor {sc}",
                 f"Masuk {fmt_bal(pos.cost_usd)} ({pos.cost:.3f} SOL) @ {self.px(p)} · MC {self.money(tok.mcap)} · "
                 f"umur {tok.age(now):.0f} detik",
                 f"✅ {len(tok.buyers)} pembeli, top10 {tok.top_pct(10):.0%}, dev {tok.dev_pct():.0%}"]
        if flags:
            lines.append("🚩 " + e(", ".join(flags)))
        lines += [f"🎯 TP {self.px(p * c['TP1_X'])} (+{c['TP1_X'] - 1:.0%}, jual {c['TP1_FRAC']:.0%}) · "
                  f"SL {self.px(p * (1 - c['SL']))} (-{c['SL']:.0%}) · sisanya trailing {c['TRAIL']:.0%}",
                  f"💼 Sisa saldo: {fmt_bal(self.port['usd'])}",
                  f"https://pump.fun/coin/{e(tok.mint)}"]
        return "\n".join(lines)

    def signal_msg(self, tok, now, gate, s, why, feats):
        e, c = html.escape, self.cfg
        sc = f"{s:.0%}" if s is not None else "belum dikalibrasi"
        good = [f"{len(tok.buyers)} pembeli", f"{len(tok.holders())} holder",
                f"top10 {tok.top_pct(10):.0%}", f"dev pegang {tok.dev_pct():.0%}"]
        flags = []
        if tok.bundle >= 3:
            flags.append(f"{tok.bundle} beli bareng di detik pertama (bundle)")
        if feats["dev_sold_any"]:
            flags.append("dev sudah jual sebagian")
        if feats["creator_prev_rugs"]:
            flags.append(f"pembuat pernah dump {feats['creator_prev_rugs']}x")
        if feats["drawdown"] >= 0.10:
            flags.append(f"turun {feats['drawdown']:.0%} dari puncak")
        p = tok.price
        lines = [f"📡 <b>memescan</b> · pump.fun · sinyal #{self.n_cand} (gate {gate})", "",
                 f"<b>{e(tok.sym)}</b>{' ' + e(tok.name) if tok.name and tok.name != tok.sym else ''} — skor {sc}",
                 f"MC {self.money(tok.mcap)} · Liq {self.money(tok.liq)} · umur {tok.age(now):.0f} detik · "
                 f"naik {feats['growth'] - 1:+.0%} sejak launch",
                 "✅ " + e(", ".join(good))]
        if flags:
            lines.append("🚩 " + e(", ".join(flags)))
        lines += [f"🎯 Entry ~{self.px(p)} · TP {self.px(p * c['TP1_X'])} (+{c['TP1_X'] - 1:.0%}, jual "
                  f"{c['TP1_FRAC']:.0%}) · SL {self.px(p * (1 - c['SL']))} (-{c['SL']:.0%})",
                  f"   Sisanya trailing {c['TRAIL']:.0%} dari puncak. Keluar kalau {c['TIME_STOP_S'] / 60:.0f} "
                  f"menit belum +{c['TIME_STOP_X'] - 1:.0%}.",
                  f"💼 Paper: {e(why)}",
                  f"<code>{e(tok.mint)}</code>",
                  f"https://pump.fun/coin/{e(tok.mint)}", "",
                  "<i>Sinyal otomatis, bukan saran beli. Hasil uji sejauh ini rugi. Pakai uang yang siap hilang.</i>"]
        return "\n".join(lines)

    def sizing(self, s):
        c, p = self.cfg, self.port
        if p["stopped"]:
            return 0, "auto-stop aktif (saldo di bawah minimum)"
        if any(x.kind == "portfolio" for x in self.positions):
            return 0, "skip, masih ada posisi terbuka (rotasi 1 posisi)"
        if not self.sol_usd:
            return 0, "skip, harga SOL belum didapat"
        if c["SCORE_ALLIN_MIN"] is None and c["SCORE_HALF_MIN"] is None:
            if not c["PAPER_FLAT"]:
                return 0, "skip, belum ada aturan beli yang terbukti"
            # skor belum terbukti: paper trading tetap jalan dengan ukuran kecil tetap
            size, why = min(c["PAPER_STAKE_USD"], p["usd"]), "ukuran tetap, skor belum terbukti"
        elif s is None:
            return 0, "skip, model skor belum ada"
        elif c["SCORE_ALLIN_MIN"] is not None and s >= c["SCORE_ALLIN_MIN"]:
            size, why = p["usd"], "ALL-IN"
        elif c["SCORE_HALF_MIN"] is not None and s >= c["SCORE_HALF_MIN"]:
            size, why = p["usd"] / 2, "setengah saldo"
        else:
            return 0, "skip, skor di bawah ambang"
        if size / self.sol_usd <= c["PRIORITY_FEE"] * 4:
            return 0, "saldo paper habis"
        p["usd"] -= size
        return size, f"beli paper {fmt_bal(size)} ({why})"

    def close(self, pos, now):
        e = html.escape
        out_usd = None
        if pos.kind == "portfolio":
            out_usd = pos.out * (self.sol_usd or pos.sol_usd)
            self.port["usd"] += out_usd
            if self.port["usd"] < self.cfg["MIN_BALANCE_USD"] and not self.port["stopped"]:
                self.port["stopped"] = True
                self.outbox.append(f"⛔ Saldo paper {fmt_bal(self.port['usd'])} di bawah minimum. "
                                   "Pembelian berhenti. Lanjutkan dengan <code>memescan.py --resume</code>.")
        oc = {"won": pos.won, "multiple": round(pos.multiple, 4), "reason": pos.reason,
              "peak_x": round(pos.peak_x, 3), "held_s": round(now - pos.opened, 1),
              "cost": pos.cost, "out": pos.out}
        if out_usd is not None:
            oc.update(usd_cost=round(pos.cost_usd, 4), usd_out=round(out_usd, 4))
        self.log({"id": pos.id, "t": now, "mint": pos.mint, "kind": pos.kind, "outcome": oc})
        # posisi paper selalu dilaporkan; shadow hanya kalau kandidatnya dikirim ke Telegram
        if pos.kind == "portfolio" or pos.id in self.notified:
            if pos.kind == "shadow":
                self.notified.discard(pos.id)
            tag = "Paper" if pos.kind == "portfolio" else f"Shadow {pos.size:g} SOL"
            if pos.kind == "portfolio":
                pnl, pct = out_usd - pos.cost_usd, out_usd / pos.cost_usd - 1
                pnl_s = fmt_bal(pnl) if pnl < 0 else "+" + fmt_bal(pnl)
            else:
                pnl, pct = pos.out - pos.cost, pos.multiple - 1
                pnl_s = f"{pnl:+.3f} SOL"
            why = {"sl": "🛑 SL", "trailing": "📉 trailing stop", "time_stop": "⏱ time stop",
                   "basi": "💤 koin sepi", "bot berhenti": "🔁 bot ganti run, dijual di harga pasar"}.get(pos.reason, pos.reason)
            tail = (f"\n💼 Sisa saldo {fmt_bal(self.port['usd'])}"
                    if pos.kind == "portfolio" else "")
            self.outbox.append(
                f"{'✅' if pnl > 0 else '❌'} <b>{e(pos.sym)}</b> #{pos.id} ditutup ({why}): "
                f"bersih setelah biaya {pnl_s} ({pct:+.0%}) · puncak {pos.peak_x:.1f}x · "
                f"{(now - pos.opened) / 60:.0f} menit{' · TP 2x kena' if pos.won else ''} [{tag}]{tail}")

    def results(self, kind="shadow", since=0):
        outs = []
        try:
            with open(os.path.join(self.dir, "candidates.jsonl")) as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("kind") == kind and "outcome" in r and r.get("t", 0) >= since:
                        outs.append(r["outcome"])
        except OSError:
            pass
        return outs

    def summary(self):
        outs = self.results("shadow")
        n = len(outs)
        k = sum(o["won"] for o in outs)
        lo, hi = wilson(k, n)
        m, mlo, mhi = mean_ci([o["multiple"] for o in outs]) if outs else (0, 0, 0)
        lines = [f"📊 <b>memescan</b> · {self.n_cand} koin lolos filter · {n} diuji (shadow)"]
        if n:
            lines.append(f"Uji semua sinyal: kena TP 2x {k}/{n} = {k / n:.0%} (CI 95% {lo:.0%}–{hi:.0%}), "
                         f"rata-rata {m:.2f}x per trade")
        if n < 30:
            lines.append("<i>Belum 30 trade, belum bisa disimpulkan apa-apa.</i>")
        if self.suppressed:
            lines.append(f"({self.suppressed} kandidat tidak dikirim karena batas "
                         f"{self.cfg['NOTIFY_MAX_PER_H']} pesan/jam, tetap dicatat)")
            self.suppressed = 0
        if self.cfg["RECORD"]:
            lines.append(f"📼 Rekaman: {self.n_rec} koin baru terekam (data untuk cari aturan beli baru)")
        pf = self.results("portfolio", self.port.get("since", 0))
        held = sum(x.cost_usd for x in self.positions if x.kind == "portfolio")
        total = self.port["usd"] + held
        start = self.port["start_usd"]
        w = sum(o.get("usd_out", 0) > o.get("usd_cost", 0) for o in pf)
        lines.append(f"💼 <b>Paper</b>: sisa saldo {fmt_bal(self.port['usd'])}"
                     f"{f' + {fmt_bal(held)} di posisi terbuka (harga beli)' if held else ''}"
                     f"{' · AUTO-STOP' if self.port['stopped'] else ''}")
        lines.append(f"Modal awal {fmt_bal(start)} · total {fmt_bal(total)} ({total / start - 1:+.1%}) · "
                     f"menang {w} / kalah {len(pf) - w}"
                     f"{f' · winrate {w / len(pf):.0%}' if pf else ''}")
        if pf and len(pf) < 30:
            lines.append(f"<i>Paper baru {len(pf)} trade, belum bisa disimpulkan.</i>")
        return "\n".join(lines)


# ---------------------------------------------------------------- dekode event pump.fun
# Data diambil langsung dari log transaksi program pump.fun lewat RPC Solana (logsSubscribe),
# jadi semua trade sejak koin dibuat ikut terlihat. Layout dari IDL resmi pump.fun.

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DISC_CREATE = bytes([27, 114, 169, 77, 222, 235, 99, 118])
DISC_TRADE = bytes([189, 219, 127, 211, 78, 230, 97, 238])


def b58(b):
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


class _Buf:
    def __init__(self, b):
        self.b, self.i = b, 8

    def take(self, n):
        v = self.b[self.i:self.i + n]
        if len(v) < n:
            raise ValueError("data terpotong")
        self.i += n
        return v

    def u64(self):
        return int.from_bytes(self.take(8), "little")

    def i64(self):
        return int.from_bytes(self.take(8), "little", signed=True)

    def key(self):
        return b58(self.take(32))

    def str(self):
        return self.take(self.u32()).decode("utf-8", "replace")

    def u32(self):
        return int.from_bytes(self.take(4), "little")

    def flag(self):
        return self.take(1) != b"\0"


def decode_event(raw):
    """bytes 'Program data' -> dict event, atau None kalau bukan create/trade."""
    d = raw[:8]
    try:
        if d == DISC_TRADE:
            r = _Buf(raw)
            ev = {"kind": "trade", "mint": r.key(), "sol": r.u64() / 1e9, "tok": r.u64() / 1e6,
                  "buy": r.flag(), "user": r.key()}
            r.i64()
            ev["v_sol"], ev["v_tok"] = r.u64() / 1e9, r.u64() / 1e6
            return ev
        if d == DISC_CREATE:
            r = _Buf(raw)
            ev = {"kind": "create", "name": r.str(), "symbol": r.str()}
            r.str()                                   # uri
            ev["mint"] = r.key()
            r.key()                                   # bonding curve
            ev["user"], ev["creator"] = r.key(), r.key()
            r.i64()
            ev["v_tok"], ev["v_sol"] = r.u64() / 1e6, r.u64() / 1e9
            try:                                      # field baru: koin dengan quote selain SOL
                r.u64(), r.u64(), r.key(), r.flag(), r.flag()
                q = r.key()
                ev["quote"] = q if q != "11111111111111111111111111111111" else SOL_MINT
            except ValueError:
                ev["quote"] = SOL_MINT
            return ev
    except (ValueError, UnicodeDecodeError):
        return None
    return None


def tx_events(logs):
    """Event pump.fun dari satu transaksi (urut sesuai log)."""
    out = []
    for line in logs or []:
        if line.startswith("Program data: "):
            try:
                raw = base64.b64decode(line[14:])
            except ValueError:
                continue
            ev = decode_event(raw)
            if ev:
                out.append(ev)
    return out


def feed_tx(engine, logs, now):
    """Ubah event satu transaksi ke format engine (create + beli awal dev digabung)."""
    evs = tx_events(logs)
    engine.stats["tx"] = engine.stats.get("tx", 0) + 1
    created = {}
    for ev in evs:
        if ev["kind"] == "create":
            if ev.get("quote", SOL_MINT) != SOL_MINT:
                continue                              # koin non-SOL tidak didukung
            created[ev["mint"]] = {"txType": "create", "mint": ev["mint"], "traderPublicKey": ev["creator"],
                                   "symbol": ev["symbol"], "name": ev["name"], "initialBuy": 0.0,
                                   "solAmount": 0.0, "vSolInBondingCurve": ev["v_sol"],
                                   "vTokensInBondingCurve": ev["v_tok"], "pool": "pump"}
    pending = []
    for ev in evs:
        if ev["kind"] != "trade":
            continue
        c = created.get(ev["mint"])
        if c is not None and ev["buy"] and ev["user"] == c["traderPublicKey"] and not c["initialBuy"]:
            c.update(initialBuy=ev["tok"], solAmount=ev["sol"], vSolInBondingCurve=ev["v_sol"],
                     vTokensInBondingCurve=ev["v_tok"])
            continue
        pending.append(ev)
    for ev in evs:
        if ev["kind"] not in engine.sample:          # contoh untuk cek dekode di log
            engine.sample.add(ev["kind"])
            print(f"[info] contoh {ev['kind']}: {json.dumps(ev)[:400]}", file=sys.stderr)
    for c in created.values():
        c["marketCapSol"] = c["vSolInBondingCurve"] / c["vTokensInBondingCurve"] * SUPPLY
        engine.on_create(c, now)
    for m in created:
        for ev in engine.orphans.pop(m, []):          # trade yang datang sebelum create-nya
            pending.insert(0, ev)
    while engine.orphan_q and engine.orphan_q[0][0] < now - 5:
        _, m = engine.orphan_q.popleft()
        lst = engine.orphans.get(m)
        if lst:
            lst.pop(0)
            if not lst:
                del engine.orphans[m]
    for ev in pending:
        tok = engine.tokens.get(ev["mint"])
        if not tok:
            if ev["mint"] not in engine.seen and len(engine.orphan_q) < 5000:
                engine.orphans.setdefault(ev["mint"], []).append(ev)
                engine.orphan_q.append((now, ev["mint"]))
            continue
        prev = tok.bal.get(ev["user"], 0.0)
        engine.on_trade({"txType": "buy" if ev["buy"] else "sell", "mint": ev["mint"],
                         "traderPublicKey": ev["user"], "solAmount": ev["sol"],
                         "newTokenBalance": max(0.0, prev + (ev["tok"] if ev["buy"] else -ev["tok"])),
                         "vSolInBondingCurve": ev["v_sol"], "vTokensInBondingCurve": ev["v_tok"],
                         "marketCapSol": ev["v_sol"] / ev["v_tok"] * SUPPLY if ev["v_tok"] else None,
                         "pool": "pump"}, now)


# ---------------------------------------------------------------- koneksi

async def run(engine, duration=0):
    import websockets  # pip install websockets

    url = engine.cfg["RPC_WS_URL"] or PUBLIC_RPC_WS
    shown = url.split("?")[0]                          # jangan cetak api-key
    stop_at = time.time() + duration if duration else None
    sender = asyncio.ensure_future(telegram_sender(engine))
    backoff = 1
    try:
        while not stop_at or time.time() < stop_at:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=30,
                                              max_size=2 ** 24) as ws:
                    await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "logsSubscribe",
                                              "params": [{"mentions": [PUMP_PROGRAM]},
                                                         {"commitment": "processed"}]}))
                    print(f"[{time.strftime('%H:%M:%S')}] tersambung ke {shown}", file=sys.stderr)
                    backoff = 1
                    tasks = [asyncio.ensure_future(reader(ws, engine)),
                             asyncio.ensure_future(ticker(ws, engine, stop_at))]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)
                    for t in done:
                        t.result()   # lempar error koneksi ke except di bawah
            except asyncio.CancelledError:
                raise
            except Exception as e:  # putus koneksi: sambung ulang
                if stop_at and time.time() >= stop_at:
                    break
                print(f"[warn] websocket: {str(e).replace(url, shown)[:200]}, sambung ulang {backoff}s", file=sys.stderr)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        engine.flush(time.time())
        engine.save()
        # kirim sisa pesan sebelum berhenti
        await asyncio.sleep(0)
        sender.cancel()
        while engine.outbox:
            await engine.tg.asend(engine.outbox.pop(0))


async def reader(ws, engine):
    last_msg = time.time()
    async for raw in ws:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(msg, dict):
            continue
        if "error" in msg:
            raise ConnectionError(f"RPC menolak: {str(msg['error'])[:200]}")
        val = ((msg.get("params") or {}).get("result") or {}).get("value")
        if not isinstance(val, dict) or val.get("err") is not None:
            continue
        feed_tx(engine, val.get("logs"), time.time())
        last_msg = time.time()
    raise ConnectionError(f"RPC menutup koneksi ({time.time() - last_msg:.0f}s sejak data terakhir)")


async def ticker(ws, engine, stop_at):
    last_save = time.time()
    last_tx, last_tx_t = 0, time.time()
    while True:
        await asyncio.sleep(0.5)
        now = time.time()
        engine.tick(now)
        if now - last_save > 60:
            engine.save()
            last_save = now
            print(f"[{time.strftime('%H:%M:%S')}] dilacak {len(engine.tokens)} · posisi {len(engine.positions)} · "
                  f"kandidat {engine.n_cand} · " + " · ".join(f"{k} {v}" for k, v in engine.stats.items()),
                  file=sys.stderr)
        tx = engine.stats.get("tx", 0)
        if tx != last_tx:
            last_tx, last_tx_t = tx, now
        elif now - last_tx_t > 60:
            raise ConnectionError("tidak ada data 60 detik")   # koneksi macet: sambung ulang
        if stop_at and now >= stop_at:
            await ws.close()
            return


async def telegram_sender(engine):
    """Kirim pesan di task terpisah supaya Telegram lambat tidak menunda simulasi.
    Sekalian perbarui harga SOL/USD tiap 10 menit."""
    loop = asyncio.get_running_loop()
    next_px = 0.0
    while True:
        if time.time() >= next_px:
            v = await loop.run_in_executor(None, fetch_sol_usd)
            engine.sol_usd = v or engine.sol_usd
            next_px = time.time() + (600 if v else 30)
        while engine.outbox:
            await engine.tg.asend(engine.outbox.pop(0))
        await asyncio.sleep(0.5)


# ---------------------------------------------------------------- kalibrasi

def simulate(trades, allin, half, start=200.0, min_frac=0.2):
    """Simulasi modal (default $200) di trade berurutan waktu: satu posisi sekaligus,
    ukuran sesuai skor, auto-stop di bawah 20% modal awal. trades: (t, skor, outcome)."""
    bal, busy_until, n, wins = start, -1.0, 0, 0
    for t, s, o in trades:
        if bal < start * min_frac:
            break
        if t < busy_until:
            continue
        if allin is not None and s >= allin:
            frac = 1.0
        elif half is not None and s >= half:
            frac = 0.5
        else:
            continue
        bal = bal * (1 - frac) + bal * frac * o["multiple"]
        busy_until = t + o.get("held_s", 0)
        n += 1
        wins += o["multiple"] > 1
    return bal, n, wins


def calibrate(data_dir):
    """Latih regresi logistik di 70% kandidat paling lama, uji di 30% terbaru
    (hold-out, tidak dipakai melatih). Ambang mengikuti spesifikasi: >=60% all-in,
    50-60% setengah saldo. Ambang hanya diaktifkan kalau rentang skornya terbukti
    di hold-out: >=30 trade dan batas bawah CI 95% rata-rata hasil > 1,00x."""
    cands, outs = {}, {}
    with open(os.path.join(data_dir, "candidates.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            if "features" in r:
                cands[r["id"]] = r
            elif r.get("kind") == "shadow" and "outcome" in r:
                outs[r["id"]] = r["outcome"]
    rows = sorted(((cands[i]["t"], cands[i]["features"], outs[i]) for i in outs if i in cands),
                  key=lambda r: r[0])
    n = len(rows)
    print(f"{n} kandidat berlabel.")
    if n < 100:
        print("Kurang dari 100 kandidat berlabel. Kumpulkan data dulu, ambang tetap kosong.")
        return None
    cut = int(n * 0.7)
    tr, va = rows[:cut], rows[cut:]

    def vec(fs):
        return [float(fs.get(k, 0.0)) for k in FEATURES]

    xt = [vec(r[1]) for r in tr]
    yt = [1.0 if r[2]["won"] else 0.0 for r in tr]
    mu = [sum(c) / len(c) for c in zip(*xt)]
    sd = [math.sqrt(sum((v - m) ** 2 for v in c) / len(c)) or 1.0 for c, m in zip(zip(*xt), mu)]
    xs = [[(v - m) / s for v, m, s in zip(row, mu, sd)] for row in xt]
    w, b, lr, l2 = [0.0] * len(FEATURES), 0.0, 0.1, 0.01
    for _ in range(3000):
        gw, gb = [0.0] * len(w), 0.0
        for row, y in zip(xs, yt):
            p = 1 / (1 + math.exp(-max(-30, min(30, b + sum(a * c for a, c in zip(w, row))))))
            for j, v in enumerate(row):
                gw[j] += (p - y) * v
            gb += p - y
        w = [wj - lr * (g / len(xs) + l2 * wj) for wj, g in zip(w, gw)]
        b -= lr * gb / len(xs)
    model = {"features": FEATURES, "weights": w, "bias": b, "mean": mu, "std": sd}

    scored = [(r[0], score(model, r[1]), r[2]) for r in va]
    pos = [s for _, s, o in scored if o["won"]]
    neg = [s for _, s, o in scored if not o["won"]]
    auc = (sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))
           if pos and neg else float("nan"))
    day = lambda t: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))
    rep = [f"# Kalibrasi memescan ({time.strftime('%Y-%m-%d %H:%M')})", "",
           f"Latih: {len(tr)} kandidat ({day(tr[0][0])} – {day(tr[-1][0])} UTC).",
           f"Hold-out: {len(va)} kandidat ({day(va[0][0])} – {day(va[-1][0])} UTC), tidak dipakai melatih.",
           f"AUC hold-out: {auc:.3f} (0,5 = tebak koin)", "",
           "| Skor | n | Winrate (TP 2x) | CI 95% | Rata-rata x | CI 95% x |", "|---|---|---|---|---|---|"]
    for lo_b in range(0, 100, 10):
        sub = [o for _, s, o in scored if lo_b / 100 <= s < (lo_b + 10) / 100]
        if not sub:
            continue
        k = sum(o["won"] for o in sub)
        wl, wh = wilson(k, len(sub))
        m, ml, mh = mean_ci([o["multiple"] for o in sub])
        rep.append(f"| {lo_b}–{lo_b + 10}% | {len(sub)} | {k / len(sub):.0%} | {wl:.0%}–{wh:.0%} | "
                   f"{m:.2f}x | {ml:.2f}–{mh:.2f} |")

    def band(lo, hi):
        sub = [o["multiple"] for _, s, o in scored if lo <= s < hi]
        m, ml, _ = mean_ci(sub) if sub else (0.0, float("nan"), 0.0)
        return len(sub), m, ml, len(sub) >= 30 and ml > 1.0

    n_a, m_a, l_a, ok_a = band(0.60, 1.01)
    n_h, m_h, l_h, ok_h = band(0.50, 0.60)
    allin, half = (0.60 if ok_a else None), (0.50 if ok_h else None)
    rep += ["", "| Rentang | n hold-out | Rata-rata x | Batas bawah CI | Terbukti? |", "|---|---|---|---|---|",
            f"| ≥60% (all-in) | {n_a} | {m_a:.2f}x | {l_a:.2f}x | {'YA' if ok_a else 'tidak'} |",
            f"| 50–60% (setengah) | {n_h} | {m_h:.2f}x | {l_h:.2f}x | {'YA' if ok_h else 'tidak'} |",
            "", "Syarat terbukti: ≥30 trade hold-out di rentang itu, dan batas bawah CI 95% "
            "rata-rata hasil > 1,00x. Yang tidak terbukti dibiarkan kosong (cuma dicatat)."]

    trades = [(t, s, o) for t, s, o in scored]
    bal, nt, wn = simulate(trades, 0.60, 0.50)
    bal0, nt0, wn0 = simulate([(t, 1.0, o) for t, s, o in scored], 0.0, None)
    rep += ["", f"## Simulasi modal $200 di hold-out ({day(va[0][0])} – {day(va[-1][0])} UTC)", "",
            "Satu posisi sekaligus, auto-stop di bawah $40. Hasil per trade dari shadow trade 0,5 SOL "
            "(jeda 3 detik, slippage, fee, priority fee). Data sebelum memescan jalan tidak ada, "
            "jadi periode Jan 2026 – sekarang tidak bisa disimulasikan.", "",
            "| Aturan | Trade | Menang | Winrate | Modal akhir | PnL |", "|---|---|---|---|---|---|",
            f"| Skor ≥60% all-in, 50–60% setengah | {nt} | {wn} | "
            f"{(wn / nt if nt else 0):.0%} | ${bal:.2f} | {bal - 200:+.2f} |",
            f"| Beli semua kandidat all-in (tanpa skor) | {nt0} | {wn0} | "
            f"{(wn0 / nt0 if nt0 else 0):.0%} | ${bal0:.2f} | {bal0 - 200:+.2f} |"]
    rep.append("\nCatatan: all-in itu berbunga. Kalau modal sudah besar, slippage di kurva pump.fun jauh "
               "lebih parah dari shadow 0,5 SOL, jadi modal akhir yang sangat besar tidak realistis.")
    if nt < 30:
        rep.append(f"\n_Simulasi skor cuma {nt} trade (<30): tidak bisa disimpulkan._")
    model.update({"SCORE_ALLIN_MIN": allin, "SCORE_HALF_MIN": half, "auc": auc,
                  "n_train": len(tr), "n_val": len(va), "trained_at": time.time()})
    with open(os.path.join(data_dir, "model.json"), "w") as f:
        json.dump(model, f)
    with open(os.path.join(data_dir, "calibration_report.md"), "w") as f:
        f.write("\n".join(rep) + "\n")
    print("\n".join(rep))
    return model


# ---------------------------------------------------------------- setup

def _tg_api(token, method):
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=20) as r:
        return json.load(r)


def setup(data_dir):
    """Tanya token bot (tidak tampil di layar), cari chat id dari /start, tanya RPC websocket
    (opsional), simpan ke .env (chmod 600)."""
    import getpass
    path = os.path.join(data_dir, ".env")
    lines = open(path).read().splitlines() if os.path.exists(path) else []
    cfg = load_config(data_dir)
    token = cfg["TELEGRAM_BOT_TOKEN"]
    while True:
        if not token:
            token = getpass.getpass("Tempel token bot Telegram (dari @BotFather, tidak tampil) lalu Enter: ").strip()
        try:
            me = _tg_api(token, "getMe")["result"]["username"]
            break
        except (urllib.error.URLError, OSError, KeyError, ValueError):
            print("Token ditolak Telegram. Coba lagi.")
            token = ""
    print(f"Bot: @{me}")
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip() or cfg["TELEGRAM_CHAT_ID"]
    while not chat:
        try:
            ups = _tg_api(token, "getUpdates").get("result") or []
        except (urllib.error.URLError, OSError, ValueError):
            ups = []
        ids = [str(c["id"]) for u in ups for c in [(u.get("message") or {}).get("chat") or {}]
               if c.get("type") == "private"]
        if ids:
            chat = ids[0]
            break
        print(f"Buka Telegram, kirim /start ke @{me}, lalu tekan Enter di sini.")
        try:
            with open("/dev/tty") as tty:   # stdin bisa berupa pipe (curl | bash)
                tty.readline()
        except OSError:
            sys.stdin.readline()
    rpc = os.environ.get("RPC_WS_URL", "").strip() or cfg["RPC_WS_URL"]
    if not rpc:
        print("Opsional: URL websocket RPC Solana, misal Helius "
              "wss://mainnet.helius-rpc.com/?api-key=... (lebih stabil dari RPC publik).")
        rpc = getpass.getpass("Tempel URL lalu Enter, atau Enter saja untuk pakai RPC publik (tidak tampil): ").strip()
    keep = [l for l in lines if l.split("=", 1)[0].strip().replace("export ", "")
            not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "RPC_WS_URL")]
    if rpc:
        keep.append(f"RPC_WS_URL={rpc}")
    old = os.umask(0o077)
    try:
        with open(path, "w") as f:
            f.write("\n".join(keep + [f"TELEGRAM_BOT_TOKEN={token}", f"TELEGRAM_CHAT_ID={chat}"]) + "\n")
    finally:
        os.umask(old)
    os.chmod(path, 0o600)
    Telegram({"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat}).send(
        "✅ memescan tersambung ke chat ini.")
    print(f"Tersimpan di {path} (chat {chat}). Cek Telegram, harusnya ada pesan tes.")


# ---------------------------------------------------------------- main

def find_chat(data_dir, token):
    """Chat Telegram kalau TELEGRAM_CHAT_ID kosong (misal di GitHub Actions): yang sudah
    terkunci di state.json, lalu seen.json versi lama, lalu /start pertama ke bot."""
    for name in ("state.json", "seen.json"):
        try:
            with open(os.path.join(data_dir, name)) as f:
                c = str(json.load(f).get("tg_chat") or "")
            if c:
                return c
        except (OSError, ValueError, AttributeError):
            pass
    try:
        ups = _tg_api(token, "getUpdates").get("result") or []
    except (urllib.error.URLError, OSError, ValueError):
        return ""
    for u in ups:
        c = (u.get("message") or {}).get("chat") or {}
        if c.get("type") == "private":
            return str(c["id"])
    print("[warn] telegram: chat belum ketemu, kirim /start ke bot kamu", file=sys.stderr)
    return ""


# ---------------------------------------------------------------- riset aturan beli

RES_AGES = (10, 20, 30, 45, 60, 90, 120, 180, 300)
RES_EXITS = [(tp, sl, T) for tp in (1.3, 1.5, 2.0, 3.0) for sl in (0.2, 0.35, 0.5) for T in (120, 300, 900)]


def v_sol_at(m):
    """Cadangan SOL kurva di market cap m (SOL), dari x*y=k kurva pump.fun."""
    return math.sqrt(VIRTUAL_SOL * 1.073e9 / SUPPLY * max(m, 1e-9))


def res_load(data_dir):
    recs = []
    d = os.path.join(data_dir, "rec")
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, fn)) as f:
            for line in f:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    recs.sort(key=lambda r: r["t0"])
    return recs


def res_trade(cs, end, entry_age, m_snap, tp, sl, T, cfg, size):
    """Simulasi satu trade di candle rekaman. cs: [(mulai, selesai, high, low, close)].
    Masuk EXEC_DELAY detik setelah keputusan di close candle saat itu. Keluar di TP/SL/batas
    waktu; kalau TP dan SL kena di candle yang sama dianggap SL dulu, isi SL/TP paling bagus
    di close candle itu (harga sudah bergerak selama jeda). Return (hasil x, umur keluar)."""
    fee, slip, prio = cfg["FEE_PCT"], cfg["SLIPPAGE"], cfg["PRIORITY_FEE"]
    te = entry_age + cfg["EXEC_DELAY"]
    p, k = m_snap, 0
    while k < len(cs) and cs[k][0] <= te:   # candle yang memuat saat order terisi ikut dihitung
        p = cs[k][4]
        k += 1
    if te >= end:
        return None
    entry = p * (1 + size / v_sol_at(p)) / ((1 - fee) * (1 - slip))
    tp_px, sl_px = entry * tp, entry * (1 - sl)
    out, t_out, last = None, min(end, te + T), p
    for a, b, h, lo, c in cs[k:]:
        if a >= te + T:
            break
        if lo <= sl_px:
            out, t_out = min(sl_px, c), b
            break
        if h >= tp_px:
            out, t_out = min(tp_px, c) if c < tp_px else tp_px, b
            break
        last = c
    if out is None:
        out = last
    sell = out * (1 - fee) * (1 - slip) / (1 + size / v_sol_at(out))
    return sell / entry - 2 * prio / size, t_out


def research(data_dir, cfg, size=0.1, train_frac=0.7, min_train=100, top=15):
    """Cari aturan beli di rekaman semua koin: umur masuk x satu filter fitur x aturan jual.
    Dipilih di data lama (70%), dinilai di data terbaru (30%) yang tidak dipakai memilih.
    Terbukti = hold-out >=30 trade dan batas bawah CI 95% rata-rata > 1,00x."""
    try:
        import numpy as np
    except ImportError:
        print("Butuh numpy: pip install numpy")
        return
    recs = res_load(data_dir)
    n_rec = len(recs)
    if n_rec < 500:
        print(f"Baru {n_rec} koin terekam. Tunggu sampai ada beberapa ribu koin.")
        return
    t_cut = recs[int(n_rec * train_frac)]["t0"]
    span = lambda a, b: (time.strftime("%d/%m %H:%M", time.gmtime(a)) + " - "
                         + time.strftime("%d/%m %H:%M", time.gmtime(b)) + " UTC")
    print(f"== RISET ATURAN BELI: {n_rec} koin terekam, {span(recs[0]['t0'], recs[-1]['t0'])}")
    print(f"   Data lama (pilih aturan): sampai {span(recs[0]['t0'], t_cut)}; data baru (uji): sesudahnya.")
    print(f"   Ukuran per trade {size} SOL, jeda {cfg['EXEC_DELAY']:g} dtk, fee {cfg['FEE_PCT']:.2%}, "
          f"slippage {cfg['SLIPPAGE']:.0%}, priority fee {cfg['PRIORITY_FEE']} SOL, dampak harga kurva.")
    paths = []
    for r in recs:
        cs = [(rec_bucket_start(c[0]), rec_bucket_end(c[0]), c[1], c[2], c[3]) for c in r["c"]]
        paths.append((cs, r["end"]))
    names = FEATURES + ["mcap"]
    results = []          # (skor latih, A, exit, filter label, statistik latih, statistik uji)
    tested = 0
    per_age = {}
    for A in RES_AGES:
        rows = []
        for i, r in enumerate(recs):
            snap = next((s for s in r["snaps"] if s[0] == A), None)
            if snap:
                rows.append((i, snap))
        if len(rows) < 200:
            continue
        X = np.array([s[2:] + [s[1]] for _, s in rows], dtype=float)
        t0 = np.array([recs[i]["t0"] for i, _ in rows])
        tr = t0 < t_cut
        M, TX = [], []
        for tp, sl, T in RES_EXITS:
            ms, ts = [], []
            for i, s in rows:
                cs, end = paths[i]
                res = res_trade(cs, end, A, s[1], tp, sl, T, cfg, size)
                ms.append(res[0] if res else np.nan)
                ts.append(res[1] if res else np.nan)
            M.append(ms)
            TX.append(ts)
        M, TX = np.array(M), np.array(TX)
        ok = ~np.isnan(M[0])
        filters = [("semua koin", np.ones(len(rows), bool))]
        for j, nm in enumerate(names):
            col = X[:, j]
            qs = sorted(set(np.quantile(col[tr & ok], [0.2, 0.4, 0.6, 0.8]).round(6)))
            for q in qs:
                filters.append((f"{nm} >= {q:.4g}", col >= q))
                filters.append((f"{nm} <= {q:.4g}", col <= q))
        per_age[A] = (rows, X, t0, M, TX, filters)

        def stat(v):
            v = v[~np.isnan(v)]
            n = len(v)
            if n < 2:
                return n, float("nan"), float("nan"), float("nan")
            m, sd = float(v.mean()), float(v.std(ddof=1))
            return n, m, m - 1.96 * sd / math.sqrt(n), float((v > 1).mean())
        for e, ex in enumerate(RES_EXITS):
            for lab, mask in filters:
                tested += 1
                st = stat(M[e][mask & tr])
                if st[0] < min_train:
                    continue
                results.append((st[2], A, e, lab, st, stat(M[e][mask & ~tr])))
    if not results:
        print("Belum cukup data per umur masuk.")
        return
    print(f"   {tested} kombinasi diuji (umur masuk x filter x aturan jual). Semakin banyak yang diuji, "
          "semakin besar peluang ada yang kelihatan bagus di data lama cuma karena kebetulan; "
          "karena itu yang dipercaya cuma hasil di data baru.")

    def fmt(st):
        n, m, lo, w = st
        return f"n={n:<5} untung {w:>4.0%} rata {m:.3f}x (CI bawah {lo:.3f})" if n >= 2 else f"n={n}"

    def ex_lab(e):
        tp, sl, T = RES_EXITS[e]
        return f"TP {tp:g}x SL -{sl:.0%} maks {T / 60:g}m"

    print("\n== PEMBANDING: beli semua koin di umur itu (aturan jual terbaik di data lama)")
    for A in sorted(per_age):
        best = max((r for r in results if r[1] == A and r[3] == "semua koin"), key=lambda r: r[0], default=None)
        if best:
            print(f"  umur {A:>3} dtk, {ex_lab(best[2]):<26} lama {fmt(best[4])} | baru {fmt(best[5])}")

    results.sort(key=lambda r: -r[0])
    print(f"\n== {top} ATURAN TERBAIK DI DATA LAMA, lalu hasilnya di data baru")
    proven = []
    for sc, A, e, lab, st_tr, st_va in results[:top]:
        ok = st_va[0] >= 30 and st_va[2] > 1.0
        if ok:
            proven.append((A, e, lab))
        print(f"  [{'TERBUKTI' if ok else 'gagal   '}] umur {A} dtk · {lab} · {ex_lab(e)}")
        print(f"      lama {fmt(st_tr)}\n      baru {fmt(st_va)}")

    A, e, lab = proven[0] if proven else (results[0][1], results[0][2], results[0][3])
    rows, X, t0, M, TX, filters = per_age[A]
    mask = dict(filters)[lab] & (t0 >= t_cut)
    trades = sorted((t0[i] + A + cfg["EXEC_DELAY"], M[e][i], TX[e][i] - A) for i in np.where(mask)[0]
                    if not np.isnan(M[e][i]))
    bal, busy, n, w = 200.0, -1.0, 0, 0
    for t, m, held in trades:
        if t < busy or bal < 40:
            continue
        stake = min(20.0, bal)
        bal += stake * (m - 1)
        busy, n, w = t + held, n + 1, w + (m > 1)
    print(f"\n== SIMULASI $200 di data baru, aturan {'terbukti' if proven else 'terbaik (TIDAK terbukti)'}: "
          f"umur {A} dtk · {lab} · {ex_lab(e)}")
    print(f"  $20 per trade, satu posisi sekaligus, berhenti di bawah $40: {n} trade, menang {w}"
          f"{f' ({w / n:.0%})' if n else ''}, modal akhir ${bal:.2f} ({bal - 200:+.2f})")
    if n < 30:
        print("  Kurang dari 30 trade, belum bisa disimpulkan.")
    print("  Data sebelum rekaman dimulai tidak ada, jadi periode Jan 2026 - sekarang tidak bisa disimulasikan.")
    if not proven:
        print("\nKESIMPULAN: belum ada aturan yang terbukti di data baru.")


def analyze(data_dir, cfg):
    """Bedah hasil trade: alasan keluar, biaya, puncak harga, fitur. Pola fitur dicek di
    70% data lama dan 30% data terbaru terpisah; pola yang cuma muncul di satu bagian
    kemungkinan kebetulan."""
    cands, outs, port = {}, {}, []
    with open(os.path.join(data_dir, "candidates.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            if "features" in r:
                cands[r["id"]] = r
            elif "outcome" in r and r.get("kind") == "shadow":
                outs[r["id"]] = r["outcome"]
            elif "outcome" in r and r.get("kind") == "portfolio":
                port.append(r)
    rows = sorted(((cands[i], outs[i]) for i in outs if i in cands), key=lambda r: r[0]["t"])
    n = len(rows)
    if n < 30:
        print(f"Baru {n} trade shadow, belum cukup untuk dianalisa.")
        return
    xs = [o["multiple"] for _, o in rows]
    t0, t1 = rows[0][0]["t"], rows[-1][0]["t"]

    def line(label, sub):
        if not sub:
            return f"  {label:<26} n=0"
        k = sum(o["won"] for o in sub)
        m, lo, hi = mean_ci([o["multiple"] for o in sub])
        prof = sum(o["multiple"] > 1 for o in sub)
        return (f"  {label:<26} n={len(sub):<5} untung {prof / len(sub):>4.0%}  TP2x {k / len(sub):>4.0%}  "
                f"rata {m:.2f}x (CI {lo:.2f}-{hi:.2f})")

    print(f"== SHADOW {n} trade, {time.strftime('%d/%m %H:%M', time.gmtime(t0))} - "
          f"{time.strftime('%d/%m %H:%M', time.gmtime(t1))} UTC, ukuran {cfg['SHADOW_SOL']} SOL")
    k = sum(o["won"] for _, o in rows)
    lo, hi = wilson(k, n)
    srt = sorted(xs)
    print(f"  kena TP 2x {k}/{n} = {k / n:.1%} (CI {lo:.1%}-{hi:.1%}); untung (>1x) "
          f"{sum(x > 1 for x in xs) / n:.1%}; median {srt[n // 2]:.2f}x; rata {sum(xs) / n:.3f}x")
    gross = ((1 - cfg["FEE_PCT"]) * (1 - cfg["SLIPPAGE"])) ** 2
    print(f"  biaya pasti per trade (fee {cfg['FEE_PCT']:.2%} + slippage {cfg['SLIPPAGE']:.0%}, beli+jual): "
          f"{1 - gross:.1%} + priority fee {2 * cfg['PRIORITY_FEE'] / cfg['SHADOW_SOL']:.1%} + dampak harga")
    print(f"  rata sebelum fee & slippage kira-kira {sum(xs) / n / gross:.3f}x")

    print("\n== ALASAN KELUAR (sumbangan = bagian dari total rugi)")
    loss = sum(1 - x for x in xs if x < 1) or 1
    by = collections.defaultdict(list)
    for _, o in rows:
        by[o["reason"]].append(o)
    for why, sub in sorted(by.items(), key=lambda kv: -len(kv[1])):
        lost = sum(1 - o["multiple"] for o in sub if o["multiple"] < 1)
        print(line(why, sub) + f"  sumbangan rugi {lost / loss:.0%}")

    print("\n== PUNCAK HARGA SETELAH MASUK (dari harga beli termasuk biaya)")
    for a, b in ((0, 1.0), (1.0, 1.1), (1.1, 1.3), (1.3, 1.5), (1.5, 2.0), (2.0, 1e9)):
        sub = [o for _, o in rows if a <= o["peak_x"] < b]
        print(line(f"puncak {a:g}-{b:g}x" if b < 1e9 else f"puncak >={a:g}x", sub))
    gave = [o for _, o in rows if o["peak_x"] >= 1.5 and o["multiple"] < 1]
    print(f"  sempat >=1.5x tapi tutup rugi: {len(gave)} ({len(gave) / n:.1%})")

    sl = sorted(o["held_s"] for _, o in rows if o["reason"] == "sl")
    if sl:
        print(f"\n== SL: {len(sl)} trade. Kena SL dalam 15 dtk {sum(s <= 15 for s in sl) / len(sl):.0%}, "
              f"30 dtk {sum(s <= 30 for s in sl) / len(sl):.0%}, 60 dtk {sum(s <= 60 for s in sl) / len(sl):.0%}; "
              f"median {sl[len(sl) // 2]:.0f} dtk")
        slx = sorted(o["multiple"] for _, o in rows if o["reason"] == "sl")
        print(f"  hasil SL median {slx[len(slx) // 2]:.2f}x (aturan SL -{cfg['SL']:.0%}; selisihnya = harga "
              f"sudah jatuh lebih dalam selama jeda {cfg['EXEC_DELAY']:g} dtk)")

    print("\n== PERKIRAAN KASAR: jual semua begitu harga X kali harga beli (batas atas, optimistis)")
    for X in (1.2, 1.3, 1.5, 2.0):
        sim = [X * (1 - cfg["FEE_PCT"]) * (1 - cfg["SLIPPAGE"]) if o["peak_x"] >= X else o["multiple"]
               for _, o in rows]
        print(f"  jual di {X:g}x: rata {sum(sim) / n:.3f}x, untung {sum(s > 1 for s in sim) / n:.0%}")

    print("\n== PER GATE")
    for g in ("cepat", "lambat"):
        print(line(g, [o for c, o in rows if c["gate"] == g]))

    cut = int(n * 0.7)
    tr, va = rows[:cut], rows[cut:]
    print(f"\n== FITUR SAAT MASUK, dibagi 5 kelompok (batas dari 70% data lama). "
          f"Kiri: {len(tr)} trade lama. Kanan: {len(va)} trade terbaru")
    for fk in FEATURES:
        vals = sorted(c["features"].get(fk, 0.0) for c, _ in tr)
        qs = sorted(set(vals[int(len(vals) * q / 5)] for q in range(1, 5)))
        edges = [-1e18] + qs + [1e18]
        print(f" {fk}")
        for a, b in zip(edges, edges[1:]):
            def pick(rs):
                return [o for c, o in rs if a <= c["features"].get(fk, 0.0) < b]
            st, sv = pick(tr), pick(va)
            if not st and not sv:
                continue
            lab = (f"< {b:.3g}" if a == -1e18 else f">= {a:.3g}" if b == 1e18 else f"{a:.3g}-{b:.3g}")
            mt = sum(o["multiple"] for o in st) / len(st) if st else 0
            mv = sum(o["multiple"] for o in sv) / len(sv) if sv else 0
            wt = sum(o["won"] for o in st) / len(st) if st else 0
            wv = sum(o["won"] for o in sv) / len(sv) if sv else 0
            print(f"   {lab:<16} lama n={len(st):<4} TP {wt:>4.0%} {mt:.2f}x | baru n={len(sv):<4} TP {wv:>4.0%} {mv:.2f}x")

    print("\n== JAM (UTC) MASUK")
    for h0 in range(0, 24, 4):
        print(line(f"{h0:02d}-{h0 + 4:02d}", [o for c, o in rows if h0 <= time.gmtime(c["t"]).tm_hour < h0 + 4]))

    if port:
        po = [r["outcome"] for r in port if "usd_cost" in r["outcome"]]
        print(f"\n== PAPER ($) {len(po)} trade")
        if po:
            pnl = sum(o["usd_out"] - o["usd_cost"] for o in po)
            w = sum(o["usd_out"] > o["usd_cost"] for o in po)
            print(f"  menang {w} kalah {len(po) - w}, total {pnl:+.2f} USD, rata "
                  f"{sum(o['usd_out'] / o['usd_cost'] for o in po) / len(po):.3f}x")
            pr = collections.Counter(o["reason"] for o in po)
            print("  alasan keluar: " + ", ".join(f"{k} {v}" for k, v in pr.most_common()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "status", "calibrate", "analyze", "research", "setup"])
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
                    help="folder .env + data (default: data/ di sebelah script)")
    ap.add_argument("--duration", type=float, default=0, help="detik; 0 = jalan terus")
    ap.add_argument("--resume", action="store_true", help="lepas auto-stop saldo minimum")
    a = ap.parse_args()
    os.makedirs(a.data, exist_ok=True)
    if a.cmd == "setup":
        setup(a.data)
        return
    if a.cmd == "analyze":
        analyze(a.data, load_config(a.data))
        return
    if a.cmd == "research":
        research(a.data, load_config(a.data))
        return
    cfg = load_config(a.data)
    tg = Telegram(cfg)
    if tg.token and not tg.chat:
        tg.chat = find_chat(a.data, tg.token)
    if not (tg.token and tg.chat):
        print("[warn] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kosong, pesan cuma dicetak di log. "
              "Jalankan: memescan.py setup", file=sys.stderr)

    if a.cmd == "calibrate":
        m = calibrate(a.data)
        if m:
            tg.send(f"🧪 Kalibrasi selesai. AUC {m['auc']:.2f}. Ambang all-in: {m['SCORE_ALLIN_MIN']}, "
                    f"setengah: {m['SCORE_HALF_MIN']}. Detail di calibration_report.md")
        return

    model = None
    mp = os.path.join(a.data, "model.json")
    if os.path.exists(mp):
        with open(mp) as f:
            model = json.load(f)
        for k in ("SCORE_ALLIN_MIN", "SCORE_HALF_MIN"):
            if cfg[k] is None:          # .env menang; kalau kosong pakai hasil kalibrasi
                cfg[k] = model.get(k)
    eng = Engine(cfg, a.data, tg, model)
    if tg.chat and not eng.tg_chat:
        eng.tg_chat = tg.chat
        eng.save()

    if a.cmd == "status":
        print(eng.summary())
        return
    if a.resume:
        eng.port["stopped"] = False
        eng.save()

    if time.time() - eng.last_welcome > 12 * 3600:   # jangan spam kalau sering restart
        eng.last_welcome = time.time()
        tg.send("👋 <b>memescan</b> (sniper pump.fun, mode paper) aktif.\n" + eng.summary())
    try:
        asyncio.run(run(eng, a.duration))
    except KeyboardInterrupt:
        pass
    finally:
        eng.save()
        print(eng.summary())


if __name__ == "__main__":
    main()

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
    python3 memescan.py setup-telegram  # simpan token bot + chat id ke .env

Butuh: Python 3.9+ dan `pip install websockets`.
"""
import argparse
import asyncio
import html
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

WS_URL = "wss://pumpportal.fun/api/data"
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
    "START_SOL": 0.5, "MIN_BALANCE": 0.1, "SHADOW_SOL": 0.5,
    "SCORE_ALLIN_MIN": None, "SCORE_HALF_MIN": None,
    # lain-lain
    "BUNDLE_WINDOW": 1.0, "PRUNE_AGE": 120.0, "PRUNE_INFLOW": 0.5, "IDLE_DROP": 300.0,
    "MAX_TRACKED": 800, "SUMMARY_EVERY_H": 6.0, "NOTIFY_CANDIDATES": 1, "NOTIFY_MAX_PER_H": 30,
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
    env.update({k: v for k, v in os.environ.items() if k in DEFAULTS or k.startswith("TELEGRAM")})
    cfg = {}
    for k, d in DEFAULTS.items():
        v = env.get(k)
        if v is None or v == "" or v.lower() in ("null", "none"):
            cfg[k] = d
        else:
            cfg[k] = int(float(v)) if isinstance(d, int) else float(v)
    cfg["TELEGRAM_BOT_TOKEN"] = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    cfg["TELEGRAM_CHAT_ID"] = env.get("TELEGRAM_CHAT_ID", "").strip()
    return cfg


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
        self.inflow = float(ev.get("solAmount") or 0)   # bersih, termasuk dev
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
            self.inflow += sol
            self.n_buys += 1
            if trader != self.creator:
                self.buyers.add(trader)
                if now - self.t0 <= self.bundle_window:
                    self.bundle += 1
        elif side == "sell":
            self.inflow -= sol
            self.n_sells += 1
        if ev.get("newTokenBalance") is not None and trader:
            self.bal[trader] = float(ev["newTokenBalance"])
            if trader == self.creator:
                self.dev_max = max(self.dev_max, self.bal[trader])
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
        self.sub_del = []
        self.stats = {"create": 0, "trade": 0, "cepat": 0, "lambat": 0, "recheck_gagal": 0}
        st = self._load("state.json", {})
        self.seen = dict.fromkeys(st.get("seen", []))  # mint yang pernah jadi kandidat (urut waktu)
        self.creators = self._load("creators.json", {})
        self.port = st.get("portfolio") or {"balance": cfg["START_SOL"], "stopped": False}
        self.n_cand = st.get("n_cand", 0)
        self.last_summary = st.get("last_summary", time.time())
        self.last_welcome = st.get("last_welcome", 0)
        self.notified = set()
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

    def save(self):
        self._save("state.json", {"seen": list(self.seen)[-50000:], "portfolio": self.port,
                                  "n_cand": self.n_cand, "last_summary": self.last_summary,
                                  "last_welcome": self.last_welcome})
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
        if not was_sold and tok.dev_max > 0 and tok.bal.get(tok.creator, 0) <= tok.dev_max * 0.1:
            tok.dev_sold_flag = True
            self.creators.setdefault(tok.creator, {"tokens": 1, "rugs": 0})["rugs"] += 1

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
            if tok.decided:
                continue
            age = tok.age(now)
            if tok.recheck_at is not None:
                if now >= tok.recheck_at:
                    ok, why = self.holder_ok(tok)
                    gate = tok.recheck_gate
                    tok.recheck_at = tok.recheck_gate = None
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
            if tok and pos.step(tok, now):
                self.positions.remove(pos)
                self.close(pos, now)

        self.prune(now)
        if now - self.last_summary >= c["SUMMARY_EVERY_H"] * 3600:
            self.last_summary = now
            self.outbox.append(self.summary())

    def prune(self, now):
        c = self.cfg
        held = {p.mint for p in self.positions}
        drop = []
        for m, tok in self.tokens.items():
            if m in held:
                continue
            age = tok.age(now)
            if (tok.decided or age > c["SLOW_MAX_AGE"] or now - tok.last_trade > c["IDLE_DROP"]
                    or (age > c["PRUNE_AGE"] and tok.inflow < c["PRUNE_INFLOW"])):
                drop.append(m)
        if len(self.tokens) - len(drop) > c["MAX_TRACKED"]:
            rest = sorted((t for m, t in self.tokens.items() if m not in drop and m not in held),
                          key=lambda t: t.inflow)
            drop += [t.mint for t in rest[:len(self.tokens) - len(drop) - int(c["MAX_TRACKED"])]]
        for m in drop:
            self.tokens.pop(m, None)
            self.sub_del.append(m)

    # --- kandidat & posisi
    def candidate(self, tok, now, gate):
        tok.decided = True
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
            self.positions.append(Position(self.n_cand, tok, size, "portfolio", now, self.cfg))
        if now - self.hour_start >= 3600:
            self.hour_start, self.n_hour = now, 0
        if self.cfg["NOTIFY_CANDIDATES"] and self.n_hour >= self.cfg["NOTIFY_MAX_PER_H"]:
            self.suppressed += 1     # batas pesan per jam, tetap dicatat & disimulasikan
        elif self.cfg["NOTIFY_CANDIDATES"]:
            self.n_hour += 1
            self.notified.add(self.n_cand)
            e = html.escape
            sc = f"{s:.0%}" if s is not None else "belum dikalibrasi"
            self.outbox.append(
                f"🎯 <b>Kandidat #{self.n_cand} {e(tok.sym)}</b> · gate {gate} · skor {sc}\n"
                f"Umur {tok.age(now):.0f}s · MC {tok.mcap:.0f} SOL · inflow {tok.inflow:.2f} SOL · "
                f"{len(tok.buyers)} pembeli · top10 {tok.top_pct(10):.0%} · dev {tok.dev_pct():.0%}"
                f"{' · bundle ' + str(tok.bundle) if tok.bundle else ''}\n"
                f"Paper: {e(why)}\n"
                f"<code>{e(tok.mint)}</code>\nhttps://pump.fun/coin/{e(tok.mint)}")

    def sizing(self, s):
        c, p = self.cfg, self.port
        if p["stopped"]:
            return 0, "auto-stop aktif (saldo di bawah minimum)"
        if c["SCORE_ALLIN_MIN"] is None and c["SCORE_HALF_MIN"] is None:
            return 0, "cuma dicatat, ambang skor belum terbukti"
        if s is None:
            return 0, "skip, model skor belum ada"
        if any(x.kind == "portfolio" for x in self.positions):
            return 0, "skip, masih ada posisi terbuka (rotasi 1 posisi)"
        if c["SCORE_ALLIN_MIN"] is not None and s >= c["SCORE_ALLIN_MIN"]:
            size, why = p["balance"], "ALL-IN"
        elif c["SCORE_HALF_MIN"] is not None and s >= c["SCORE_HALF_MIN"]:
            size, why = p["balance"] / 2, "setengah saldo"
        else:
            return 0, "skip, skor di bawah ambang"
        p["balance"] -= size
        return size, f"beli {why} ({size:.3f} SOL)"

    def close(self, pos, now):
        e = html.escape
        if pos.kind == "portfolio":
            self.port["balance"] += pos.out
            if self.port["balance"] < self.cfg["MIN_BALANCE"] and not self.port["stopped"]:
                self.port["stopped"] = True
                self.outbox.append(f"⛔ Saldo paper {self.port['balance']:.3f} SOL di bawah minimum. "
                                   "Pembelian berhenti. Lanjutkan dengan <code>memescan.py --resume</code>.")
        self.log({"id": pos.id, "t": now, "mint": pos.mint, "kind": pos.kind, "outcome": {
            "won": pos.won, "multiple": round(pos.multiple, 4), "reason": pos.reason,
            "peak_x": round(pos.peak_x, 3), "held_s": round(now - pos.opened, 1),
            "cost": pos.cost, "out": pos.out}})
        # posisi paper selalu dilaporkan; shadow hanya kalau kandidatnya dikirim ke Telegram
        if pos.kind == "portfolio" or pos.id in self.notified:
            if pos.kind == "shadow":
                self.notified.discard(pos.id)
            tag = "Paper" if pos.kind == "portfolio" else "Shadow"
            self.outbox.append(
                f"{'✅' if pos.multiple > 1 else '❌'} {tag} #{pos.id} {e(pos.sym)}: {pos.multiple:.2f}x "
                f"({pos.reason}, puncak {pos.peak_x:.1f}x, {(now - pos.opened) / 60:.0f} menit)"
                f"{' · TP 2x tercapai' if pos.won else ''}"
                f"{' · saldo %.3f SOL' % self.port['balance'] if pos.kind == 'portfolio' else ''}")

    def results(self, kind="shadow"):
        outs = []
        try:
            with open(os.path.join(self.dir, "candidates.jsonl")) as f:
                for line in f:
                    r = json.loads(line)
                    if r.get("kind") == kind and "outcome" in r:
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
        lines = [f"📊 <b>memescan</b> · {self.n_cand} kandidat · {n} shadow trade selesai"]
        if n:
            lines.append(f"Winrate (kena TP 2x): {k}/{n} = {k / n:.0%} (CI 95% {lo:.0%}–{hi:.0%})")
            lines.append(f"Rata-rata hasil: {m:.2f}x per trade")
        if n < 30:
            lines.append("<i>Belum 30 trade, belum bisa disimpulkan apa-apa.</i>")
        if self.suppressed:
            lines.append(f"({self.suppressed} kandidat tidak dikirim karena batas "
                         f"{self.cfg['NOTIFY_MAX_PER_H']} pesan/jam, tetap dicatat)")
            self.suppressed = 0
        lines.append(f"💼 Saldo paper: {self.port['balance']:.3f} SOL (awal {self.cfg['START_SOL']} SOL)"
                     f"{' · AUTO-STOP' if self.port['stopped'] else ''}")
        return "\n".join(lines)


# ---------------------------------------------------------------- koneksi

async def run(engine, duration=0):
    import websockets  # pip install websockets

    stop_at = time.time() + duration if duration else None
    sender = asyncio.ensure_future(telegram_sender(engine))
    backoff = 1
    try:
        while not stop_at or time.time() < stop_at:
            try:
                async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20,
                                              max_size=2 ** 22) as ws:
                    await ws.send(json.dumps({"method": "subscribeNewToken"}))
                    keys = list(engine.tokens)
                    for i in range(0, len(keys), 200):
                        await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": keys[i:i + 200]}))
                    print(f"[{time.strftime('%H:%M:%S')}] tersambung ke PumpPortal", file=sys.stderr)
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
                print(f"[warn] websocket: {e!r}, sambung ulang {backoff}s", file=sys.stderr)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
    finally:
        engine.save()
        # kirim sisa pesan sebelum berhenti
        await asyncio.sleep(0)
        sender.cancel()
        while engine.outbox:
            await engine.tg.asend(engine.outbox.pop(0))


async def reader(ws, engine):
    async for raw in ws:
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        now = time.time()
        t = ev.get("txType")
        if t and t not in engine.sample:
            engine.sample.add(t)
            print(f"[info] contoh event {t}: " + json.dumps({k: (v if k != "uri" else "...") for k, v in ev.items()})[:600],
                  file=sys.stderr)
        if t == "create":
            if engine.on_create(ev, now):
                # langsung subscribe supaya trade awal (dan bundle) tidak terlewat
                await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [ev["mint"]]}))
        elif t in ("buy", "sell"):
            engine.on_trade(ev, now)
    raise ConnectionError("PumpPortal menutup koneksi")


async def ticker(ws, engine, stop_at):
    last_save = time.time()
    while True:
        await asyncio.sleep(0.5)
        now = time.time()
        engine.tick(now)
        if engine.sub_del:
            keys, engine.sub_del = engine.sub_del, []
            for i in range(0, len(keys), 200):
                await ws.send(json.dumps({"method": "unsubscribeTokenTrade", "keys": keys[i:i + 200]}))
        if now - last_save > 60:
            engine.save()
            last_save = now
            print(f"[{time.strftime('%H:%M:%S')}] dilacak {len(engine.tokens)} · posisi {len(engine.positions)} · "
                  f"kandidat {engine.n_cand} · " + " · ".join(f"{k} {v}" for k, v in engine.stats.items()),
                  file=sys.stderr)
        if stop_at and now >= stop_at:
            await ws.close()
            return


async def telegram_sender(engine):
    """Kirim pesan di task terpisah supaya Telegram lambat tidak menunda simulasi."""
    while True:
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


# ---------------------------------------------------------------- setup telegram

def _tg_api(token, method):
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", timeout=20) as r:
        return json.load(r)


def setup_telegram(data_dir):
    """Tanya token bot (tidak tampil di layar), cari chat id dari /start, simpan ke .env (chmod 600)."""
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
    keep = [l for l in lines if l.split("=", 1)[0].strip().replace("export ", "")
            not in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")]
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

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "status", "calibrate", "setup-telegram"])
    ap.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
                    help="folder .env + data (default: data/ di sebelah script)")
    ap.add_argument("--duration", type=float, default=0, help="detik; 0 = jalan terus")
    ap.add_argument("--resume", action="store_true", help="lepas auto-stop saldo minimum")
    a = ap.parse_args()
    os.makedirs(a.data, exist_ok=True)
    if a.cmd == "setup-telegram":
        setup_telegram(a.data)
        return
    cfg = load_config(a.data)
    tg = Telegram(cfg)
    if not (tg.token and tg.chat):
        print("[warn] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kosong, pesan cuma dicetak di log. "
              "Jalankan: memescan.py setup-telegram", file=sys.stderr)

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

    if a.cmd == "status":
        print(eng.summary())
        return
    if a.resume:
        eng.port["stopped"] = False
        eng.save()

    if time.time() - eng.last_welcome > 1800:   # jangan spam kalau systemd restart berulang
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

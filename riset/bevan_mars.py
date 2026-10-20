#!/usr/bin/env python3
"""Riset sekali jalan: cari wallet pembeli awal koin MARS (BNB Chain) yang masih pegang ~5% suplai.

Klaim di video podcast: "gua beli MARS di average market cap $10.000, sekarang 170.000.000, gua punya 5% suplai".
Cara: cari blok peluncuran (event mint), ambil semua Transfer di jam-jam pertama, jumlahkan pembelian per wallet,
hitung BNB yang dibayar, lalu cek saldo wallet itu sekarang. Hanya stdlib, RPC publik BSC tanpa key."""
import json, sys, time, urllib.request, collections, datetime

RPCS = ["https://bsc-rpc.publicnode.com", "https://bsc.drpc.org", "https://bsc-dataseed.bnbchain.org",
        "https://1rpc.io/bnb", "https://bsc.meowrpc.com", "https://bsc-dataseed1.defibit.io",
        "https://bsc-dataseed1.ninicoin.io", "https://rpc-bsc.48.club", "https://bsc.blockpi.network/v1/rpc/public",
        "https://bsc-mainnet.public.blastapi.io", "https://endpoints.omniatech.io/v1/bsc/mainnet/public",
        "https://bsc.api.onfinality.io/public", "https://api.zan.top/bsc-mainnet", "https://bsc-pokt.nodies.app",
        "https://bnb.rpc.subquery.network/public", "https://binance.llamarpc.com", "https://bsc.rpc.blxrbdn.com",
        "https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3", "https://bsc.publicnode.com"]
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_T = "0x" + "0" * 64
TOKENS = {"MARSCOIN (Flap, 0xfe18..7777)": "0xfe189e97832da1573e4e4ff034f4ffc3a15c7777",
          }  # Marscoin four.meme 0x1fd4..5b68 dibuang: diluncurkan 2024, MC $50rb, bukan koin di video
UA = {"User-Agent": "Mozilla/5.0", "content-type": "application/json"}
good = ["https://bsc-mainnet.nodereal.io/v1/64a9df0874fb4a93b9d0a3849de012d3",
        "https://bsc-mainnet.public.blastapi.io", "https://api.zan.top/bsc-mainnet"]


def utc(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def post(url, body, timeout=40):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def rpc(method, params, tries=None):
    err = None
    for url in (list(good) * 3)[: tries or 3 * len(good)]:
        try:
            j = post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if "error" in j:
                err = f"{url}: {j['error']}"
                continue
            return j["result"]
        except Exception as e:
            err = f"{url}: {e}"
            time.sleep(1)
    raise RuntimeError(err)


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def bn():
    return int(rpc("eth_blockNumber", []), 16)


def bts(n):
    return int(rpc("eth_getBlockByNumber", [hex(n), False])["timestamp"], 16)


def logs(addr, a, b, topics, step):
    """Semua log di [a, b], range dipecah otomatis kalau RPC menolak."""
    out, lo = [], a
    while lo <= b:
        hi = min(b, lo + step - 1)
        try:
            out += rpc("eth_getLogs", [{"address": addr, "fromBlock": hex(lo), "toBlock": hex(hi), "topics": topics}])
            lo = hi + 1
        except RuntimeError as e:
            if step <= 50:
                raise
            step = max(50, step // 4)
    return out


def call(to, data, block="latest"):
    return rpc("eth_call", [{"to": to, "data": data}, block])


def debug():
    """Uji tiap RPC: getLogs lama (50 blok, Juli 2026) dan state lama (archive)."""
    tok = TOKENS[next(iter(TOKENS))]
    for url in RPCS:
        res = []
        for name, method, params in [
            ("head", "eth_blockNumber", []),
            ("logs50", "eth_getLogs", [{"address": tok, "fromBlock": hex(112_430_000), "toBlock": hex(112_430_049), "topics": [TRANSFER]}]),
            ("logs5k", "eth_getLogs", [{"address": tok, "fromBlock": hex(112_430_000), "toBlock": hex(112_434_999), "topics": [TRANSFER]}]),
            ("code_old", "eth_getCode", [tok, hex(112_000_000)]),
        ]:
            try:
                j = post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
                r = j.get("result")
                res.append(f"{name}=" + ("ERR " + str(j["error"])[:70] if "error" in j else
                                         (str(int(r, 16)) if name == "head" else str(len(r)) + ("log" if isinstance(r, list) else "ch"))))
            except Exception as e:
                res.append(f"{name}=X {str(e)[:40]}")
        print(url, "|", " ".join(res), flush=True)


def bnb_usd(ts):
    d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%d-%m-%Y")
    try:
        return get_json(f"https://api.coingecko.com/api/v3/coins/binancecoin/history?date={d}&localization=false")["market_data"]["current_price"]["usd"]
    except Exception as e:
        print(f"  (harga BNB {d} gagal: {str(e)[:80]})")
        return None


def first_block(pred, lo, hi):
    """Blok terkecil di (lo, hi] dengan pred benar (pred monoton)."""
    while hi - lo > 1:
        m = (lo + hi) // 2
        if pred(m):
            hi = m
        else:
            lo = m
    return hi


def block_at(ts, head):
    return first_block(lambda n: bts(n) >= ts, 0, head)


def bal(tok, w, block="latest"):
    try:
        return int(call(tok, "0x70a08231" + "0" * 24 + w[2:], block if block == "latest" else hex(block)), 16)
    except Exception:
        return -1


def analyze(name, tok, hours):
    print(f"\n==================== {name} ====================\n{tok}")
    sup = int(call(tok, "0x18160ddd"), 16)
    print(f"total suplai {sup / 1e18:,.0f}")
    head = bn()
    try:
        for p in (get_json(f"https://api.dexscreener.com/latest/dex/tokens/{tok}").get("pairs") or [])[:3]:
            print(f"  dexscreener: {p.get('dexId')} MC ${p.get('marketCap') or p.get('fdv')} liq ${(p.get('liquidity') or {}).get('usd')}"
                  f" pair dibuat {utc(p['pairCreatedAt'] / 1000) if p.get('pairCreatedAt') else '-'}")
    except Exception as e:
        print(f"  dexscreener gagal: {str(e)[:80]}")
    launch = first_block(lambda n: len(rpc("eth_getCode", [tok, hex(n)])) > 2, 0, head)
    t0 = bts(launch)
    ms = logs(tok, launch, launch + 200, [TRANSFER, ZERO_T], 201)
    curve = "0x" + ms[0]["topics"][2][-40:] if ms else None
    print(f"kontrak dibuat blok {launch} ({utc(t0)} UTC); suplai awal ke {curve}")
    end = launch + int(hours * 3600 / 0.45) + 1
    tr = logs(tok, launch, end, [TRANSFER], 2000)
    print(f"{len(tr)} transfer dalam ~{hours} jam pertama (sampai {utc(bts(min(end, head)))} UTC)")
    # sumber beli = curve + kontrak pool (alamat yang paling sering mengirim token dan punya kode)
    cnt = collections.Counter("0x" + l["topics"][1][-40:] for l in tr)
    src = {curve}
    for a, c in cnt.most_common(12):
        if c >= 50 and a != "0x" + "0" * 40 and len(rpc("eth_getCode", [a, "latest"])) > 2:
            src.add(a)
    print("sumber (curve/pool):", ", ".join(f"{a}({cnt[a]})" for a in src))
    buy = collections.defaultdict(lambda: {"tok": 0, "net": 0, "txs": [], "first": None})
    for l in tr:
        fr, to, amt = "0x" + l["topics"][1][-40:], "0x" + l["topics"][2][-40:], int(l["data"], 16)
        b = int(l["blockNumber"], 16)
        if fr in src and to not in src:
            w = buy[to]
            w["net"] += amt
            if b <= launch + int(600 / 0.45):           # pembelian di 10 menit pertama
                w["tok"] += amt
                w["txs"].append((l["transactionHash"], amt, b))
                w["first"] = w["first"] or b
        elif to in src and fr not in src and fr in buy:
            buy[fr]["net"] -= amt
    buy = {k: v for k, v in buy.items() if v["tok"] > 0}
    print(f"{len(buy)} wallet beli di 10 menit pertama")
    ath_blk = block_at(int(datetime.datetime(2026, 9, 5, tzinfo=datetime.timezone.utc).timestamp()), head)
    px = bnb_usd(t0)
    print(f"harga BNB hari peluncuran: {px}; blok 5 Sep 2026: {ath_blk}")
    print(f"\n{'wallet':44} {'menit':>6} {'beli%':>6} {'net3j%':>6} {'BNB':>8} {'avgMC$':>9} {'5Sep%':>6} {'kini%':>6}  signer / bayar")
    print(f"cek balanceOf: pool utama {100 * bal(tok, '0x94f3ed36706c746ad59fadcaf271b7431ab1d8f1') / sup:.2f}% kini, "
          f"{100 * bal(tok, '0x94f3ed36706c746ad59fadcaf271b7431ab1d8f1', ath_blk) / sup:.2f}% 5 Sep")
    top = sorted(buy.items(), key=lambda kv: -kv[1]["tok"])[:40]
    cands = []
    for w, d in top:
        bnb, part, signer, other = 0.0, 0, set(), collections.Counter()
        for h, amt, b in d["txs"][:10]:
            try:
                tx = rpc("eth_getTransactionByHash", [h])
                v = int(tx["value"], 16) / 1e18
                signer.add(tx["from"])
                if v > 0:
                    bnb += v
                    part += amt
                else:
                    for l in rpc("eth_getTransactionReceipt", [h])["logs"]:
                        if l["topics"] and l["topics"][0] == TRANSFER and len(l["topics"]) == 3 and l["address"].lower() != tok \
                                and "0x" + l["topics"][2][-40:] == curve:
                            other[l["address"][:10]] += int(l["data"], 16) / 1e18
            except Exception as e:
                print(f"   ({h[:10]} gagal: {str(e)[:60]})")
        mc = bnb / (part / 1e18) * (sup / 1e18) * px if part and px else None
        mins = (bts(d["first"]) - t0) / 60
        b5, bn_ = bal(tok, w, ath_blk), bal(tok, w)
        sg = ",".join(x[:12] for x in signer if x != w) or "sama"
        oth = " ".join(f"{k}:{v:.2f}" for k, v in other.items())
        print(f"{w:44} {mins:6.1f} {100 * d['tok'] / sup:5.2f}% {100 * d['net'] / sup:5.2f}% {bnb:8.3f} {('%9.0f' % mc) if mc else '        -'} "
              f"{100 * b5 / sup:5.2f}% {100 * bn_ / sup:5.2f}%  {sg} {oth}", flush=True)
        if d["net"] >= 0.005 * sup or (mc and mc <= 20000 and d["tok"] >= 0.01 * sup):
            cands.append(w)
    trace(tok, sup, src, launch, head, ath_blk, cands)


def drop_block(tok, w, lo, hi, thr):
    """Blok pertama di (lo, hi] saat saldo w turun di bawah thr (pakai archive balanceOf)."""
    return first_block(lambda n: 0 <= bal(tok, w, n) < thr, lo, hi)


def trace(tok, sup, src, launch, head, ath_blk, cands, depth=0, seen=None):
    """Ikuti token kandidat: cari kapan saldonya habis, lalu lihat ke mana transfernya (jual ke pool atau pindah wallet)."""
    seen = seen if seen is not None else set()
    if depth == 0:
        print(f"\n---- jejak {len(cands)} wallet kandidat ----")
    pad = "    " * depth
    for w in cands:
        if w in seen:
            continue
        seen.add(w)
        start = launch + int(3 * 3600 / 0.45)
        b0 = bal(tok, w, start) if depth == 0 else max(bal(tok, w, start), 1)
        if b0 <= 0 and depth == 0:
            print(f"{pad}{w}: sudah habis dalam 3 jam pertama")
            continue
        peak = max(b0, bal(tok, w, ath_blk), bal(tok, w))
        if bal(tok, w) >= 0.5 * peak:
            print(f"{pad}{w}: MASIH PEGANG {100 * bal(tok, w) / sup:.2f}% kini (5 Sep {100 * bal(tok, w, ath_blk) / sup:.2f}%)")
            continue
        blk = drop_block(tok, w, start, head, 0.1 * peak)
        out = logs(tok, max(launch, blk - 3000), blk, [TRANSFER, "0x" + "0" * 24 + w[2:]], 3001)
        moved = collections.Counter()
        sold = 0
        for l in out:
            to, amt = "0x" + l["topics"][2][-40:], int(l["data"], 16)
            if to in src:
                sold += amt
            else:
                moved[to] += amt
        print(f"{pad}{w}: saldo habis {utc(bts(blk))} UTC; di blok itu jual ke pool {100 * sold / sup:.2f}%, pindah {100 * sum(moved.values()) / sup:.2f}%")
        nxt = []
        for d, amt in moved.most_common(3):
            if amt >= 0.002 * sup:
                code = len(rpc("eth_getCode", [d, "latest"])) > 2
                print(f"{pad}    -> {d}{' (kontrak)' if code else ''} {100 * amt / sup:.2f}%; saldo 5 Sep {100 * bal(tok, d, ath_blk) / sup:.2f}%, kini {100 * bal(tok, d) / sup:.2f}%", flush=True)
                if not code:
                    nxt.append(d)
        if nxt and depth < 2:
            trace(tok, sup, src, launch, head, ath_blk, nxt, depth + 1, seen)


if __name__ == "__main__":
    if sys.argv[1:2] == ["debug"]:
        debug()
    else:
        if sys.argv[1:2] == ["skip"]:
            sys.exit(0)
        hours = float(sys.argv[1]) if len(sys.argv) > 1 else 3
        for n, t in TOKENS.items():
            try:
                analyze(n, t, hours)
            except Exception as e:
                print(f"{n}: gagal {str(e)[:300]}")

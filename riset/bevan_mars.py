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
          "Marscoin (four.meme, 0x1fd4..5b68)": "0x1fd448d0361c3212961a70930f3129a45f425b68"}
UA = {"User-Agent": "Mozilla/5.0", "content-type": "application/json"}
good = list(RPCS)


def utc(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def post(url, body, timeout=40):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def rpc(method, params, tries=None):
    err = None
    for url in list(good)[: tries or len(good)]:
        try:
            j = post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if "error" in j:
                err = f"{url}: {j['error']}"
                continue
            return j["result"]
        except Exception as e:
            err = f"{url}: {e}"
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
    d = utc(ts).strftime("%d-%m-%Y")
    try:
        return get_json(f"https://api.coingecko.com/api/v3/coins/binancecoin/history?date={d}&localization=false")["market_data"]["current_price"]["usd"]
    except Exception as e:
        print(f"  (harga BNB {d} gagal: {str(e)[:80]})")
        return None


def analyze(name, tok, hours):
    print(f"\n==================== {name} ====================\n{tok}")
    sup = int(call(tok, "0x18160ddd"), 16)
    try:
        dec = int(call(tok, "0x313ce567"), 16)
    except Exception:
        dec = 18
    print(f"total suplai {sup / 10**dec:,.0f} (desimal {dec})")
    head = bn()
    t_head = bts(head)
    bt = (t_head - bts(head - 100_000)) / 100_000
    print(f"blok terakhir {head}, waktu blok {bt:.3f} s")
    hint = head
    try:
        ds = get_json(f"https://api.dexscreener.com/latest/dex/tokens/{tok}").get("pairs") or []
        pc = [p["pairCreatedAt"] for p in ds if p.get("pairCreatedAt")]
        for p in ds[:3]:
            print(f"  dexscreener: {p.get('dexId')} MC ${p.get('marketCap') or p.get('fdv')} liq ${(p.get('liquidity') or {}).get('usd')}")
        if pc:
            hint = min(head, head - int((t_head - min(pc) / 1000) / bt) + 2000)
            print(f"  pair dibuat {utc(min(pc) / 1000)} UTC -> mulai cari dari blok {hint}")
    except Exception as e:
        print(f"  dexscreener gagal: {str(e)[:80]}")
    # cari mint (Transfer dari alamat nol) mundur dari hint
    launch, curve, hi = None, None, hint
    while hi > hint - 12_000_000 and launch is None:
        lo = hi - 200_000
        ms = logs(tok, lo, hi, [TRANSFER, ZERO_T], 200_000)
        if ms:
            m = min(ms, key=lambda x: int(x["blockNumber"], 16))
            launch, curve = int(m["blockNumber"], 16), "0x" + m["topics"][2][-40:]
            # pastikan tidak ada mint lebih awal di chunk sebelumnya
            prev = logs(tok, lo - 200_000, lo - 1, [TRANSFER, ZERO_T], 200_000)
            if prev:
                hi = lo - 1
                launch = None
                continue
        hi = lo - 1
    if launch is None:
        print("blok peluncuran tidak ketemu")
        return
    t0 = bts(launch)
    print(f"diluncurkan blok {launch} ({utc(t0)} UTC); suplai awal dikirim ke {curve}")
    end = launch + int(hours * 3600 / bt)
    tr = logs(tok, launch, end, [TRANSFER], 3000)
    print(f"{len(tr)} transfer di {hours} jam pertama")
    buy = collections.defaultdict(lambda: {"tok": 0, "txs": [], "first": None})
    sold_from_curve = 0
    for l in tr:
        fr, to, amt = "0x" + l["topics"][1][-40:], "0x" + l["topics"][2][-40:], int(l["data"], 16)
        b = int(l["blockNumber"], 16)
        if fr == curve and to != curve:
            sold_from_curve += amt
            w = buy[to]
            w["tok"] += amt
            w["txs"].append((l["transactionHash"], amt, b, sold_from_curve))
            w["first"] = w["first"] or b
    top = sorted(buy.items(), key=lambda kv: -kv[1]["tok"])[:40]
    px = bnb_usd(t0)
    print(f"harga BNB hari itu: {px}")
    print(f"\n{'wallet':44} {'menit':>6} {'beli %':>7} {'BNB':>9} {'avg MC $':>10} {'saldo kini %':>12}")
    for w, d in top:
        bnb, signer = 0, set()
        for h, amt, b, cum in d["txs"][:25]:
            try:
                tx = rpc("eth_getTransactionByHash", [h])
                bnb += int(tx["value"], 16) / 1e18
                signer.add(tx["from"])
            except Exception:
                pass
        part = sum(a for _, a, _, _ in d["txs"][:25])
        mc = (bnb / (part / 10**dec)) * (sup / 10**dec) * px if part and bnb and px else None
        try:
            now = int(call(tok, "0x70a08231" + "0" * 24 + w[2:]), 16)
        except Exception:
            now = -1
        mins = (bts(d["first"]) - t0) / 60
        print(f"{w:44} {mins:6.1f} {100 * d['tok'] / sup:6.2f}% {bnb:9.3f} {('%10.0f' % mc) if mc else '         -'} "
              f"{(100 * now / sup) if now >= 0 else -1:11.2f}%  signer {','.join(s[:10] for s in signer) if signer and signer != {w} else '-'}")
        time.sleep(0.2)


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

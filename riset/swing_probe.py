"""Cek daftar koin lulus pump.fun dari RPC Solana publik (7 Nov 2026)."""
import json
import time
import urllib.request

RPC = "https://api.mainnet-beta.solana.com"


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=body, headers={"Content-Type": "application/json", "User-Agent": "memescan"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


for addr in ("39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg",):
    r = rpc("getSignaturesForAddress", [addr, {"limit": 20}])
    sigs = r.get("result", [])
    print(addr, "sig:", len(sigs), r.get("error"))
    for s in sigs[:20]:
        print("  ", time.strftime("%Y-%m-%d %H:%M", time.gmtime(s["blockTime"] or 0)), s["err"] is None)
    # lompat ke belakang: berapa per hari
    if sigs:
        last = sigs[-1]["signature"]
        n, t_first = 0, sigs[0]["blockTime"]
        for _ in range(3):
            rr = rpc("getSignaturesForAddress", [addr, {"limit": 1000, "before": last}]).get("result", [])
            if not rr:
                break
            n += len(rr)
            last = rr[-1]["signature"]
            time.sleep(1)
        print("  3000 sig mundur sampai", time.strftime("%Y-%m-%d %H:%M", time.gmtime(rr[-1]["blockTime"])) if rr else "?", "dari",
              time.strftime("%Y-%m-%d %H:%M", time.gmtime(t_first)))
    for s in sigs[:3]:
        tx = rpc("getTransaction", [s["signature"], {"maxSupportedTransactionVersion": 0, "encoding": "json"}]).get("result")
        if not tx:
            print("   tx kosong")
            continue
        logs = [l for l in tx["meta"]["logMessages"] if "Instruction" in l][:8]
        mints = sorted({b["mint"] for b in tx["meta"]["postTokenBalances"]})
        print("   logs:", logs)
        print("   mints:", mints)
        time.sleep(1)

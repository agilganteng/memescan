#!/usr/bin/env bash
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
for u in \
 "https://kolscan.io/leaderboard" \
 "https://kolscan.io/api/leaderboard?timeframe=1" \
 "https://kolscan.io/api/leaderboard" \
 "https://frontend-api-v3.pump.fun/leaderboard/traders?timeframe=24h&limit=20" \
 "https://frontend-api-v3.pump.fun/leaderboards/traders?limit=20" \
 "https://frontend-api-v3.pump.fun/traders/leaderboard?limit=20" \
 "https://advanced-api-v2.pump.fun/leaderboard/traders?limit=20" \
 "https://pump.fun/leaderboard" \
 "https://gmgn.ai/defi/quotation/v1/rank/sol/wallets/7d?orderby=pnl_7d&direction=desc" \
 ; do
  echo "=== $u"; curl -sS -m 20 -A "$UA" -w '\nHTTP %{http_code} size %{size_download}\n' "$u" | head -c 1500; echo
done
echo "=== kolscan wallets in html"
curl -sS -m 20 -A "$UA" https://kolscan.io/leaderboard | grep -oE '[1-9A-HJ-NP-Za-km-z]{32,44}' | sort | uniq -c | sort -rn | head -30
echo "=== pump.fun js leaderboard endpoints"
curl -sS -m 20 -A "$UA" https://pump.fun/leaderboard | grep -oE 'https://[a-z0-9.-]*pump\.fun[^"'"'"' ]*' | sort -u | head -40
echo "=== RPC"
curl -sS -m 20 -X POST -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"getSlot"}' https://api.mainnet-beta.solana.com

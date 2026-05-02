     1|     1|#!/bin/bash
     2|     2|# monitor_clob_activation.sh
     3|     3|# Sleduje, kedy Polymarket zapne CLOB orderbook (enable_order_book=true)
     4|     4|# Usage: nohup ./monitor_clob_activation.sh &
     5|     5|
     6|     6|# PROXY disabled — using direct DE IP
# PROXY=""
     7|     7|LOG_FILE="$HOME/.trading_bot/logs/clob_monitor.log"
     8|     8|CHECK_INTERVAL=900  # 15 min
     9|     9|TELEGRAM_BOT_TOKEN="***"
    10|    10|TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID}"
    11|    11|
    12|    12|log() {
    13|    13|    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
    14|    14|}
    15|    15|
    16|    16|send_telegram() {
    17|    17|    local msg="$1"
    18|    18|    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
    19|    19|        curl -s -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage" \
    20|    20|            -d "chat_id=$TELEGRAM_CHAT_ID" -d "text=$msg" -d "parse_mode=Markdown" >/dev/null 2>&1
    21|    21|    fi
    22|    22|}
    23|    23|
    24|    24|log "CLOB monitor spustený. Kontrolujem každých $((CHECK_INTERVAL/60)) min."
    25|    25|log "Proxy: $PROXY"
    26|    26|
    27|    27|while true; do
    28|    28|    # Fetch markets via proxy
    response=$(curl -s \
        "https://clob.polymarket.com/markets?active=true&limit=50")
    31|    31|    
    32|    32|    if [ $? -ne 0 ]; then
    33|    33|        log "ERROR: curl failed (possible proxy issue)"
    34|    34|        sleep $CHECK_INTERVAL
    35|    35|        continue
    36|    36|    fi
    37|    37|    
    38|    38|    # Count markets with enable_order_book=true
    39|    39|    ob_count=$(echo "$response" | python3 -c "
    40|    40|import sys, json
    41|    41|try:
    42|    42|    d = json.load(sys.stdin)
    43|    43|    markets = d.get('data', []) if isinstance(d, dict) else d
    44|    44|    ob = [m for m in markets if m.get('enable_order_book')]
    45|    45|    print(len(ob))
    46|    46|except Exception as e:
    47|    47|    print(0)
    48|    48|")
    49|    49|    
    50|    50|    if [ "$ob_count" -gt 0 ]; then
    51|    51|        log "✅ VYSLEDOK: Našiel som $ob_count trhov s enable_order_book=true!"
    52|    52|        
    53|    53|        # Get first tradable market details
    54|    54|        details=$(echo "$response" | python3 -c "
    55|    55|import sys, json
    56|    56|d = json.load(sys.stdin)
    57|    57|markets = d.get('data', []) if isinstance(d, dict) else d
    58|    58|for m in markets:
    59|    59|    if m.get('enable_order_book'):
    60|    60|        print('Question:', m.get('question','N/A'))
    61|    61|        print('Ticker:', m.get('ticker','N/A'))
    62|    62|        tokens = m.get('tokens', [])
    63|    63|        for t in tokens:
    64|    64|            if t.get('outcome','').lower() in ('yes','true'):
    65|    65|                print('Token ID (YES):', t.get('token_id','N/A')[:60])
    66|    66|        break
    67|    67|")
    68|    68|        
    69|    69|        log "DETAILS: $details"
    70|    70|        
    71|    71|        # Send Telegram alert
    72|    72|        alert="✅ Polymarket CLOB ORDERBOOK REAKTIVOVANÝ!\n\nNašiel som $ob_count trhov s enable_order_book=true.\n\n$details\n\nSpusti bota: python -m polymarket_bot"
    73|    73|        send_telegram "$alert"
    74|    74|        
    75|    75|        log "NOTIFICATION odoslaná. Monitor pokračuje (nové trhy sa môžu objaviť)."
    76|    76|    else
    77|    77|        log "Žiadne trhy s orderbook — stále disable."
    78|    78|    fi
    79|    79|    
    80|    80|    sleep $CHECK_INTERVAL
    81|    81|done
    82|    82|
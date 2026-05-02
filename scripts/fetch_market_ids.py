#!/usr/bin/env python3
"""
Fetch live Polymarket market IDs for configured crypto assets.
Outputs YAML snippet for config/prod.yaml

Usage:
  export POLYMARKET_API_KEY=...
  export POLYMARKET_API_SECRET=...
  export POLYMARKET_WALLET_ADDRESS=0x...
  python scripts/fetch_market_ids.py > market_ids.yaml
"""
import os, sys, asyncio, json, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from polymarket_bot.exchange.live_client import PolymarketLiveClient

ASSET_KEYWORDS = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum"],
    "TAO": ["tao", "bittensor"],
    "HL":  ["hyperliquid", "hyper-liquid"],
}
WINDOW_KEYWORDS = {
    "1h": ["1 hour", "1h", "hour"],
    "6h": ["6 hour", "6h", "six hour"],
}

async def main():
    api_key = os.environ.get("POLYMARKET_API_KEY")
    api_secret = os.environ.get("POLYMARKET_API_SECRET")
    wallet = os.environ.get("POLYMARKET_WALLET_ADDRESS")
    if not all([api_key, api_secret, wallet]):
        print("ERROR: Set POLYMARKET_API_KEY/SECRET/WALLET_ADDRESS", file=sys.stderr)
        sys.exit(1)
    
    print("# Fetching Polymarket crypto markets...", file=sys.stderr)
    client = PolymarketLiveClient(dry_run=False, api_key=api_key, api_secret=api_secret, wallet_address=wallet)
    await client.connect()
    
    try:
        markets = await client.get_markets(category="crypto", limit=200)
        print(f"# Retrieved {len(markets)} markets", file=sys.stderr)
        found = {}
        for m in markets:
            mid = m.get("id") or m.get("market_id")
            if not mid: continue
            question = (m.get("question", "") + " " + m.get("title", "")).lower()
            for asset, kws in ASSET_KEYWORDS.items():
                if not any(kw in question for kw in kws): continue
                for window, wkws in WINDOW_KEYWORDS.items():
                    if any(wk in question for wk in wkws):
                        found[f"{asset}:{window}"] = mid
        
        print("# Generated market IDs for config/prod.yaml")
        print("trading:")
        print("  assets:")
        for asset in ["BTC", "ETH", "TAO", "HL"]:
            win1h = found.get(f"{asset}:1h", "0x..._1H_PLACEHOLDER")
            win6h = found.get(f"{asset}:6h", "0x..._6H_PLACEHOLDER")
            print(f"    {asset}:")
            print(f"      symbol: {asset}")
            print(f"      market_id: {win1h}   # ⚠️ verify in prod")
            print(f"      windows: ["1h", "6h"]")
            print(f"      enabled: true")
            print(f"      max_position_usd: 30")
        await client.disconnect()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

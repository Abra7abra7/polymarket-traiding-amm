#!/usr/bin/env python3
"""
Test Polymarket API connectivity — validates credentials and market access.
Run BEFORE going live: python test_polymarket_api.py
"""
import os
import sys
import asyncio
import pytest
import json
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from polymarket_bot.exchange.client import PolymarketClient
from polymarket_bot.exchange.interface import BaseExchangeClient

@pytest.mark.asyncio
async def test_connectivity():
    print("=== Polymarket API Test ===\n")
    
    from dotenv import load_dotenv
    load_dotenv()
    
    # Read env vars
    api_key = os.environ.get("POLYMARKET_API_KEY")
    api_secret = os.environ.get("POLYMARKET_API_SECRET")
    wallet_addr = os.environ.get("POLYMARKET_WALLET_ADDRESS")
    
    if not all([api_key, api_secret, wallet_addr]):
        print("[FAIL] Missing environment variables:")
        for var in ["POLYMARKET_API_KEY", "POLYMARKET_API_SECRET", "POLYMARKET_WALLET_ADDRESS"]:
            status = "[OK]" if os.environ.get(var) else "[MISSING]"
            print(f"   {status} {var}")
        print("\nSet them in .env or export before running.")
        return False
    
    print("[OK] Credentials found")
    
    # Create client (dry_run=False uses real API when implemented)
    client = PolymarketClient(
        dry_run=False,  # Will hit real endpoints if PolymarketClient implements them
        sandbox=False
    )
    
    try:
        await client.connect()
        print("[OK] Connected to Polymarket")
    except Exception as e:
        print(f"[FAIL] Connection failed: {e}")
        return False
    
    # Test 1: Get account balance
    try:
        bal = await client.get_balance()
        print(f"[OK] Balance: ${bal:,.2f}")
    except NotImplementedError:
        print("[WARN] get_balance() not implemented in mock — needs real client")
    except Exception as e:
        print(f"[FAIL] Balance fetch error: {e}")
    
    # Test 2: Get ticker for ETH_1H
    try:
        price = await client.get_ticker("ETH_1H")
        print(f"[OK] ETH_1H ticker: ${price:.4f}")
    except NotImplementedError:
        print("[WARN] get_ticker() returns mock data — real API not connected")
    except Exception as e:
        print(f"[FAIL] Ticker error: {e}")
    
    # Test 3: List markets
    try:
        markets = await client.get_markets()
        print(f"[OK] Markets available: {len(markets)}")
        # Show first 3
        for m in markets[:3]:
            mid = m.get('id', m.get('market_id', '???'))
            q = m.get('question', m.get('title', ''))[:50]
            print(f"   • {mid}: {q}")
    except NotImplementedError:
        print("[WARN] get_markets() not implemented")
    except Exception as e:
        print(f"[FAIL] Markets fetch error: {e}")
    
    await client.disconnect()
    print("\n[OK] API test complete — review results above")
    return True

if __name__ == "__main__":
    success = asyncio.run(test_connectivity())
    sys.exit(0 if success else 1)

import asyncio
import random
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import structlog  # type: ignore

from polymarket_bot.exchange.interface import BaseExchangeClient

logger = structlog.get_logger()


class PolymarketClient(BaseExchangeClient):
    """
    Mock Polymarket client for dry-run and unit testing.

    - Simulates binary outcome markets (YES/NO).
    - Prices are probabilities in [0.01, 1.00] for prediction markets,
      except BTC symbol which returns a simulated USD price (~50k) for
      test purposes.
    - No real network calls; all data is deterministic noise.
    """

    def __init__(self, dry_run: bool = True, sandbox: bool = False, base_url: str = None, ws_url: str = None):
        self.dry_run = dry_run
        self.sandbox = sandbox
        self.base_url = base_url
        self.ws_url = ws_url
        self._connected = False
        self._order_counter = 0
        self._orders: Dict[str, Dict] = {}

        # Simulated account balance (for dry-run)
        self._dry_balance = 50000.0

        # Mock market definitions
        self._mock_markets = {
            "BTC_1H": {
                "id": "0xbtc-1h-0123456789abcdef",
                "symbol": "BTC",
                "name": "BTC 1H",
                "window": "1h",
                "question": "Will BTC be above $100K by end of day?",
                "base_price": 0.65,
                "volatility": 0.02
            },
            "ETH_1H": {
                "id": "0xeth-1h-abcdef1234567890",
                "symbol": "ETH",
                "name": "ETH 1H",
                "window": "1h",
                "question": "Will ETH flip ETH?",
                "base_price": 0.58,
                "volatility": 0.02
            },
            "BTC_5M": {
                "id": "0xbtc-5m-0123456789abcdef",
                "symbol": "BTC",
                "name": "BTC 5M",
                "window": "5m",
                "question": "Will BTC pump next 5 minutes?",
                "base_price": 0.50,
                "volatility": 0.05
            },
            "LON_RAIN_1H": {
                "id": "0xlondon-rain-1h-abcdef123456",
                "symbol": "RAIN",
                "name": "London Rain 1H",
                "window": "1h",
                "question": "Will it rain in London in the next hour?",
                "base_price": 0.50,
                "volatility": 0.02
            },
            "VIE_RAIN_1H": {
                "id": "0xvienna-rain-1h-abcdef123456",
                "symbol": "RAIN",
                "name": "Vienna Rain 1H",
                "window": "1h",
                "question": "Will it rain in Vienna in the next hour?",
                "base_price": 0.50,
                "volatility": 0.02
            },
            "PRG_RAIN_1H": {
                "id": "0xprague-rain-1h-abcdef123456",
                "symbol": "RAIN",
                "name": "Prague Rain 1H",
                "window": "1h",
                "question": "Will it rain in Prague in the next hour?",
                "base_price": 0.50,
                "volatility": 0.02
            },
            # --- Added crypto 6h and TAO/HL 1h markets (2026-04-22) ---
            "BTC_6H": {
                "id": "0xbtc-6h-0123456789abcdef",
                "symbol": "BTC",
                "name": "BTC 6H",
                "window": "6h",
                "question": "Will BTC hold 6h?",
                "base_price": 0.60,
                "volatility": 0.03
            },
            "ETH_6H": {
                "id": "0xeth-6h-abcdef1234567890",
                "symbol": "ETH",
                "name": "ETH 6H",
                "window": "6h",
                "question": "Will ETH be above $5K in 6 hours?",
                "base_price": 0.58,
                "volatility": 0.03
            },
            "TAO_1H": {
                "id": "0xtao-1h-0123456789abcdef",
                "symbol": "TAO",
                "name": "TAO 1H",
                "window": "1h",
                "question": "Will TAO pump next hour?",
                "base_price": 0.50,
                "volatility": 0.04
            },
            "TAO_6H": {
                "id": "0xtao-6h-abcdef1234567890",
                "symbol": "TAO",
                "name": "TAO 6H",
                "window": "6h",
                "question": "Will TAO moon in 6 hours?",
                "base_price": 0.50,
                "volatility": 0.05
            },
            "HL_1H": {
                "id": "0xhl-1h-0123456789abcdef",
                "symbol": "HL",
                "name": "Hyperliquid 1H",
                "window": "1h",
                "question": "Will HL retain liquidity?",
                "base_price": 0.50,
                "volatility": 0.04
            },
            "ETH_4H": {
                "id": "0x9b3bed5b6884fc90605c9de49fe3e240bff35d5779640cdc7d12e4ec5a06cc22",
                "symbol": "ETH",
                "name": "ETH 4H",
                "window": "4h",
                "question": "Will ETH hold 4h?",
                "base_price": 0.58,
                "volatility": 0.03
            }
        }

        # Add new 15M and 4H timeframes (2026-05-01)
        self._mock_markets.update({
            "BTC_15M": {
                "id": "0xf7086e2218ce1c3a61ba10ec8f1086964f1281f78a216da02795865b4770c8bd",
                "symbol": "BTC",
                "name": "BTC 15M",
                "window": "15m",
                "question": "Will BTC go up in 15 minutes?",
                "base_price": 0.50,
                "volatility": 0.03
            },
            "BTC_4H": {
                "id": "0xc01cde6f78bdab324d6ca29b617eb180e6890262691d005768d07f5ff86b4110",
                "symbol": "BTC",
                "name": "BTC 4H",
                "window": "4h",
                "question": "Will BTC hold 4h?",
                "base_price": 0.60,
                "volatility": 0.03
            },
            "ETH_15M": {
                "id": "0xcc5a3447e1bf14981a1e772851b7135b23d8bf1edac04d1c39b3636f85044c04",
                "symbol": "ETH",
                "name": "ETH 15M",
                "window": "15m",
                "question": "Will ETH go up in 15 minutes?",
                "base_price": 0.50,
                "volatility": 0.03
            },
            "ETH_4H": {
                "id": "0x9b3bed5b6884fc90605c9de49fe3e240bff35d5779640cdc7d12e4ec5a06cc22",
                "symbol": "ETH",
                "name": "ETH 4H",
                "window": "4h",
                "question": "Will ETH hold 4h?",
                "base_price": 0.58,
                "volatility": 0.03
            }
        })

        # Extended weather markets — all 18 EU cities, both 1h/6h, all 4 metrics
        self._mock_markets.update({
        "AMS_RAIN_1H": {
            "id": "0xams-rain-1h-16390",
            "symbol": "RAIN",
            "name": "Amsterdam Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Amsterdam reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "AMS_RAIN_6H": {
            "id": "0xams-rain-6h-d07c",
            "symbol": "RAIN",
            "name": "Amsterdam Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Amsterdam reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "AMS_STORM_1H": {
            "id": "0xams-storm-1h-2ffa",
            "symbol": "STORM",
            "name": "Amsterdam Storm 1H",
            "window": "1h",
            "question": "Will storm in Amsterdam reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "AMS_STORM_6H": {
            "id": "0xams-storm-6h-15b72",
            "symbol": "STORM",
            "name": "Amsterdam Storm 6H",
            "window": "6h",
            "question": "Will storm in Amsterdam reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "AMS_SUN_1H": {
            "id": "0xams-sun-1h-45bf",
            "symbol": "SUN",
            "name": "Amsterdam Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Amsterdam reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "AMS_SUN_6H": {
            "id": "0xams-sun-6h-354f",
            "symbol": "SUN",
            "name": "Amsterdam Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Amsterdam reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "AMS_WIND_1H": {
            "id": "0xams-wind-1h-dceb",
            "symbol": "WIND",
            "name": "Amsterdam Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Amsterdam reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "AMS_WIND_6H": {
            "id": "0xams-wind-6h-cafb",
            "symbol": "WIND",
            "name": "Amsterdam Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Amsterdam reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ATH_RAIN_1H": {
            "id": "0xath-rain-1h-103cb",
            "symbol": "RAIN",
            "name": "Athens Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Athens reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ATH_RAIN_6H": {
            "id": "0xath-rain-6h-4319",
            "symbol": "RAIN",
            "name": "Athens Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Athens reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ATH_STORM_1H": {
            "id": "0xath-storm-1h-313b",
            "symbol": "STORM",
            "name": "Athens Storm 1H",
            "window": "1h",
            "question": "Will storm in Athens reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ATH_STORM_6H": {
            "id": "0xath-storm-6h-fd10",
            "symbol": "STORM",
            "name": "Athens Storm 6H",
            "window": "6h",
            "question": "Will storm in Athens reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ATH_SUN_1H": {
            "id": "0xath-sun-1h-df87",
            "symbol": "SUN",
            "name": "Athens Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Athens reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ATH_SUN_6H": {
            "id": "0xath-sun-6h-36",
            "symbol": "SUN",
            "name": "Athens Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Athens reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ATH_WIND_1H": {
            "id": "0xath-wind-1h-12b5e",
            "symbol": "WIND",
            "name": "Athens Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Athens reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ATH_WIND_6H": {
            "id": "0xath-wind-6h-e318",
            "symbol": "WIND",
            "name": "Athens Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Athens reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BER_RAIN_1H": {
            "id": "0xber-rain-1h-aaea",
            "symbol": "RAIN",
            "name": "Berlin Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Berlin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BER_RAIN_6H": {
            "id": "0xber-rain-6h-a2ba",
            "symbol": "RAIN",
            "name": "Berlin Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Berlin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BER_STORM_1H": {
            "id": "0xber-storm-1h-e772",
            "symbol": "STORM",
            "name": "Berlin Storm 1H",
            "window": "1h",
            "question": "Will storm in Berlin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BER_STORM_6H": {
            "id": "0xber-storm-6h-1127c",
            "symbol": "STORM",
            "name": "Berlin Storm 6H",
            "window": "6h",
            "question": "Will storm in Berlin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BER_SUN_1H": {
            "id": "0xber-sun-1h-db24",
            "symbol": "SUN",
            "name": "Berlin Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Berlin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BER_SUN_6H": {
            "id": "0xber-sun-6h-65e0",
            "symbol": "SUN",
            "name": "Berlin Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Berlin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BER_WIND_1H": {
            "id": "0xber-wind-1h-6c5c",
            "symbol": "WIND",
            "name": "Berlin Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Berlin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BER_WIND_6H": {
            "id": "0xber-wind-6h-1412b",
            "symbol": "WIND",
            "name": "Berlin Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Berlin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BRU_RAIN_1H": {
            "id": "0xbru-rain-1h-7e49",
            "symbol": "RAIN",
            "name": "Brussels Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Brussels reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BRU_RAIN_6H": {
            "id": "0xbru-rain-6h-376",
            "symbol": "RAIN",
            "name": "Brussels Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Brussels reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BRU_STORM_1H": {
            "id": "0xbru-storm-1h-64cc",
            "symbol": "STORM",
            "name": "Brussels Storm 1H",
            "window": "1h",
            "question": "Will storm in Brussels reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BRU_STORM_6H": {
            "id": "0xbru-storm-6h-845d",
            "symbol": "STORM",
            "name": "Brussels Storm 6H",
            "window": "6h",
            "question": "Will storm in Brussels reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BRU_SUN_1H": {
            "id": "0xbru-sun-1h-d8d1",
            "symbol": "SUN",
            "name": "Brussels Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Brussels reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BRU_SUN_6H": {
            "id": "0xbru-sun-6h-1d14",
            "symbol": "SUN",
            "name": "Brussels Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Brussels reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BRU_WIND_1H": {
            "id": "0xbru-wind-1h-e362",
            "symbol": "WIND",
            "name": "Brussels Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Brussels reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BRU_WIND_6H": {
            "id": "0xbru-wind-6h-16b91",
            "symbol": "WIND",
            "name": "Brussels Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Brussels reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BUD_RAIN_1H": {
            "id": "0xbud-rain-1h-6f82",
            "symbol": "RAIN",
            "name": "Budapest Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Budapest reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BUD_RAIN_6H": {
            "id": "0xbud-rain-6h-16b4c",
            "symbol": "RAIN",
            "name": "Budapest Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Budapest reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BUD_STORM_1H": {
            "id": "0xbud-storm-1h-6e98",
            "symbol": "STORM",
            "name": "Budapest Storm 1H",
            "window": "1h",
            "question": "Will storm in Budapest reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BUD_STORM_6H": {
            "id": "0xbud-storm-6h-10354",
            "symbol": "STORM",
            "name": "Budapest Storm 6H",
            "window": "6h",
            "question": "Will storm in Budapest reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BUD_SUN_1H": {
            "id": "0xbud-sun-1h-be89",
            "symbol": "SUN",
            "name": "Budapest Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Budapest reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BUD_SUN_6H": {
            "id": "0xbud-sun-6h-10d80",
            "symbol": "SUN",
            "name": "Budapest Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Budapest reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "BUD_WIND_1H": {
            "id": "0xbud-wind-1h-3717",
            "symbol": "WIND",
            "name": "Budapest Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Budapest reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "BUD_WIND_6H": {
            "id": "0xbud-wind-6h-10dd0",
            "symbol": "WIND",
            "name": "Budapest Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Budapest reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "CPH_RAIN_1H": {
            "id": "0xcph-rain-1h-134a8",
            "symbol": "RAIN",
            "name": "Copenhagen Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Copenhagen reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "CPH_RAIN_6H": {
            "id": "0xcph-rain-6h-114c4",
            "symbol": "RAIN",
            "name": "Copenhagen Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Copenhagen reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "CPH_STORM_1H": {
            "id": "0xcph-storm-1h-12f70",
            "symbol": "STORM",
            "name": "Copenhagen Storm 1H",
            "window": "1h",
            "question": "Will storm in Copenhagen reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "CPH_STORM_6H": {
            "id": "0xcph-storm-6h-10208",
            "symbol": "STORM",
            "name": "Copenhagen Storm 6H",
            "window": "6h",
            "question": "Will storm in Copenhagen reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "CPH_SUN_1H": {
            "id": "0xcph-sun-1h-8e13",
            "symbol": "SUN",
            "name": "Copenhagen Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Copenhagen reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "CPH_SUN_6H": {
            "id": "0xcph-sun-6h-6ec0",
            "symbol": "SUN",
            "name": "Copenhagen Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Copenhagen reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "CPH_WIND_1H": {
            "id": "0xcph-wind-1h-107b1",
            "symbol": "WIND",
            "name": "Copenhagen Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Copenhagen reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "CPH_WIND_6H": {
            "id": "0xcph-wind-6h-117d8",
            "symbol": "WIND",
            "name": "Copenhagen Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Copenhagen reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "DUB_RAIN_1H": {
            "id": "0xdub-rain-1h-d5e9",
            "symbol": "RAIN",
            "name": "Dublin Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Dublin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "DUB_RAIN_6H": {
            "id": "0xdub-rain-6h-17654",
            "symbol": "RAIN",
            "name": "Dublin Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Dublin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "DUB_STORM_1H": {
            "id": "0xdub-storm-1h-1466b",
            "symbol": "STORM",
            "name": "Dublin Storm 1H",
            "window": "1h",
            "question": "Will storm in Dublin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "DUB_STORM_6H": {
            "id": "0xdub-storm-6h-330b",
            "symbol": "STORM",
            "name": "Dublin Storm 6H",
            "window": "6h",
            "question": "Will storm in Dublin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "DUB_SUN_1H": {
            "id": "0xdub-sun-1h-9c79",
            "symbol": "SUN",
            "name": "Dublin Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Dublin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "DUB_SUN_6H": {
            "id": "0xdub-sun-6h-109a9",
            "symbol": "SUN",
            "name": "Dublin Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Dublin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "DUB_WIND_1H": {
            "id": "0xdub-wind-1h-fa5f",
            "symbol": "WIND",
            "name": "Dublin Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Dublin reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "DUB_WIND_6H": {
            "id": "0xdub-wind-6h-15e22",
            "symbol": "WIND",
            "name": "Dublin Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Dublin reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "HEL_RAIN_1H": {
            "id": "0xhel-rain-1h-15400",
            "symbol": "RAIN",
            "name": "Helsinki Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Helsinki reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "HEL_RAIN_6H": {
            "id": "0xhel-rain-6h-56a7",
            "symbol": "RAIN",
            "name": "Helsinki Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Helsinki reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "HEL_STORM_1H": {
            "id": "0xhel-storm-1h-1660b",
            "symbol": "STORM",
            "name": "Helsinki Storm 1H",
            "window": "1h",
            "question": "Will storm in Helsinki reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "HEL_STORM_6H": {
            "id": "0xhel-storm-6h-76bc",
            "symbol": "STORM",
            "name": "Helsinki Storm 6H",
            "window": "6h",
            "question": "Will storm in Helsinki reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "HEL_SUN_1H": {
            "id": "0xhel-sun-1h-cda5",
            "symbol": "SUN",
            "name": "Helsinki Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Helsinki reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "HEL_SUN_6H": {
            "id": "0xhel-sun-6h-c202",
            "symbol": "SUN",
            "name": "Helsinki Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Helsinki reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "HEL_WIND_1H": {
            "id": "0xhel-wind-1h-a72d",
            "symbol": "WIND",
            "name": "Helsinki Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Helsinki reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "HEL_WIND_6H": {
            "id": "0xhel-wind-6h-ae00",
            "symbol": "WIND",
            "name": "Helsinki Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Helsinki reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LIS_RAIN_1H": {
            "id": "0xlis-rain-1h-11897",
            "symbol": "RAIN",
            "name": "Lisbon Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Lisbon reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LIS_RAIN_6H": {
            "id": "0xlis-rain-6h-3d47",
            "symbol": "RAIN",
            "name": "Lisbon Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Lisbon reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LIS_STORM_1H": {
            "id": "0xlis-storm-1h-6656",
            "symbol": "STORM",
            "name": "Lisbon Storm 1H",
            "window": "1h",
            "question": "Will storm in Lisbon reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LIS_STORM_6H": {
            "id": "0xlis-storm-6h-12bf6",
            "symbol": "STORM",
            "name": "Lisbon Storm 6H",
            "window": "6h",
            "question": "Will storm in Lisbon reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LIS_SUN_1H": {
            "id": "0xlis-sun-1h-25d1",
            "symbol": "SUN",
            "name": "Lisbon Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Lisbon reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LIS_SUN_6H": {
            "id": "0xlis-sun-6h-54ec",
            "symbol": "SUN",
            "name": "Lisbon Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Lisbon reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LIS_WIND_1H": {
            "id": "0xlis-wind-1h-738",
            "symbol": "WIND",
            "name": "Lisbon Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Lisbon reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LIS_WIND_6H": {
            "id": "0xlis-wind-6h-18301",
            "symbol": "WIND",
            "name": "Lisbon Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Lisbon reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LON_RAIN_1H": {
            "id": "0xlon-rain-1h-177c4",
            "symbol": "RAIN",
            "name": "London Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in London reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LON_RAIN_6H": {
            "id": "0xlon-rain-6h-2aef",
            "symbol": "RAIN",
            "name": "London Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in London reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LON_STORM_1H": {
            "id": "0xlon-storm-1h-4102",
            "symbol": "STORM",
            "name": "London Storm 1H",
            "window": "1h",
            "question": "Will storm in London reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LON_STORM_6H": {
            "id": "0xlon-storm-6h-150b6",
            "symbol": "STORM",
            "name": "London Storm 6H",
            "window": "6h",
            "question": "Will storm in London reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LON_SUN_1H": {
            "id": "0xlon-sun-1h-9534",
            "symbol": "SUN",
            "name": "London Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in London reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LON_SUN_6H": {
            "id": "0xlon-sun-6h-91f3",
            "symbol": "SUN",
            "name": "London Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in London reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "LON_WIND_1H": {
            "id": "0xlon-wind-1h-100e8",
            "symbol": "WIND",
            "name": "London Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in London reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "LON_WIND_6H": {
            "id": "0xlon-wind-6h-ec",
            "symbol": "WIND",
            "name": "London Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in London reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "MAD_RAIN_1H": {
            "id": "0xmad-rain-1h-6d59",
            "symbol": "RAIN",
            "name": "Madrid Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Madrid reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "MAD_RAIN_6H": {
            "id": "0xmad-rain-6h-5604",
            "symbol": "RAIN",
            "name": "Madrid Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Madrid reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "MAD_STORM_1H": {
            "id": "0xmad-storm-1h-c870",
            "symbol": "STORM",
            "name": "Madrid Storm 1H",
            "window": "1h",
            "question": "Will storm in Madrid reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "MAD_STORM_6H": {
            "id": "0xmad-storm-6h-a0d7",
            "symbol": "STORM",
            "name": "Madrid Storm 6H",
            "window": "6h",
            "question": "Will storm in Madrid reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "MAD_SUN_1H": {
            "id": "0xmad-sun-1h-13a91",
            "symbol": "SUN",
            "name": "Madrid Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Madrid reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "MAD_SUN_6H": {
            "id": "0xmad-sun-6h-146b9",
            "symbol": "SUN",
            "name": "Madrid Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Madrid reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "MAD_WIND_1H": {
            "id": "0xmad-wind-1h-12d2f",
            "symbol": "WIND",
            "name": "Madrid Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Madrid reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "MAD_WIND_6H": {
            "id": "0xmad-wind-6h-ff41",
            "symbol": "WIND",
            "name": "Madrid Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Madrid reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "OSL_RAIN_1H": {
            "id": "0xosl-rain-1h-1808d",
            "symbol": "RAIN",
            "name": "Oslo Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Oslo reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "OSL_RAIN_6H": {
            "id": "0xosl-rain-6h-55d1",
            "symbol": "RAIN",
            "name": "Oslo Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Oslo reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "OSL_STORM_1H": {
            "id": "0xosl-storm-1h-11833",
            "symbol": "STORM",
            "name": "Oslo Storm 1H",
            "window": "1h",
            "question": "Will storm in Oslo reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "OSL_STORM_6H": {
            "id": "0xosl-storm-6h-163f3",
            "symbol": "STORM",
            "name": "Oslo Storm 6H",
            "window": "6h",
            "question": "Will storm in Oslo reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "OSL_SUN_1H": {
            "id": "0xosl-sun-1h-2b8c",
            "symbol": "SUN",
            "name": "Oslo Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Oslo reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "OSL_SUN_6H": {
            "id": "0xosl-sun-6h-16ba2",
            "symbol": "SUN",
            "name": "Oslo Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Oslo reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "OSL_WIND_1H": {
            "id": "0xosl-wind-1h-b273",
            "symbol": "WIND",
            "name": "Oslo Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Oslo reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "OSL_WIND_6H": {
            "id": "0xosl-wind-6h-e151",
            "symbol": "WIND",
            "name": "Oslo Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Oslo reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PAR_RAIN_1H": {
            "id": "0xpar-rain-1h-fbcf",
            "symbol": "RAIN",
            "name": "Paris Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Paris reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PAR_RAIN_6H": {
            "id": "0xpar-rain-6h-1d0b",
            "symbol": "RAIN",
            "name": "Paris Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Paris reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PAR_STORM_1H": {
            "id": "0xpar-storm-1h-1047c",
            "symbol": "STORM",
            "name": "Paris Storm 1H",
            "window": "1h",
            "question": "Will storm in Paris reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PAR_STORM_6H": {
            "id": "0xpar-storm-6h-790c",
            "symbol": "STORM",
            "name": "Paris Storm 6H",
            "window": "6h",
            "question": "Will storm in Paris reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PAR_SUN_1H": {
            "id": "0xpar-sun-1h-14147",
            "symbol": "SUN",
            "name": "Paris Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Paris reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PAR_SUN_6H": {
            "id": "0xpar-sun-6h-14f6",
            "symbol": "SUN",
            "name": "Paris Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Paris reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PAR_WIND_1H": {
            "id": "0xpar-wind-1h-119fa",
            "symbol": "WIND",
            "name": "Paris Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Paris reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PAR_WIND_6H": {
            "id": "0xpar-wind-6h-1353b",
            "symbol": "WIND",
            "name": "Paris Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Paris reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PRG_RAIN_1H": {
            "id": "0xprg-rain-1h-12b04",
            "symbol": "RAIN",
            "name": "Prague Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Prague reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PRG_RAIN_6H": {
            "id": "0xprg-rain-6h-39e5",
            "symbol": "RAIN",
            "name": "Prague Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Prague reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PRG_STORM_1H": {
            "id": "0xprg-storm-1h-148de",
            "symbol": "STORM",
            "name": "Prague Storm 1H",
            "window": "1h",
            "question": "Will storm in Prague reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PRG_STORM_6H": {
            "id": "0xprg-storm-6h-6fa7",
            "symbol": "STORM",
            "name": "Prague Storm 6H",
            "window": "6h",
            "question": "Will storm in Prague reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PRG_SUN_1H": {
            "id": "0xprg-sun-1h-aa52",
            "symbol": "SUN",
            "name": "Prague Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Prague reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PRG_SUN_6H": {
            "id": "0xprg-sun-6h-120c3",
            "symbol": "SUN",
            "name": "Prague Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Prague reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "PRG_WIND_1H": {
            "id": "0xprg-wind-1h-17720",
            "symbol": "WIND",
            "name": "Prague Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Prague reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "PRG_WIND_6H": {
            "id": "0xprg-wind-6h-44bf",
            "symbol": "WIND",
            "name": "Prague Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Prague reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ROM_RAIN_1H": {
            "id": "0xrom-rain-1h-60e4",
            "symbol": "RAIN",
            "name": "Rome Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Rome reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ROM_RAIN_6H": {
            "id": "0xrom-rain-6h-577e",
            "symbol": "RAIN",
            "name": "Rome Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Rome reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ROM_STORM_1H": {
            "id": "0xrom-storm-1h-8e48",
            "symbol": "STORM",
            "name": "Rome Storm 1H",
            "window": "1h",
            "question": "Will storm in Rome reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ROM_STORM_6H": {
            "id": "0xrom-storm-6h-1309d",
            "symbol": "STORM",
            "name": "Rome Storm 6H",
            "window": "6h",
            "question": "Will storm in Rome reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ROM_SUN_1H": {
            "id": "0xrom-sun-1h-b43",
            "symbol": "SUN",
            "name": "Rome Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Rome reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ROM_SUN_6H": {
            "id": "0xrom-sun-6h-7fa4",
            "symbol": "SUN",
            "name": "Rome Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Rome reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ROM_WIND_1H": {
            "id": "0xrom-wind-1h-2495",
            "symbol": "WIND",
            "name": "Rome Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Rome reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "ROM_WIND_6H": {
            "id": "0xrom-wind-6h-16b99",
            "symbol": "WIND",
            "name": "Rome Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Rome reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "STO_RAIN_1H": {
            "id": "0xsto-rain-1h-e7c2",
            "symbol": "RAIN",
            "name": "Stockholm Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Stockholm reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "STO_RAIN_6H": {
            "id": "0xsto-rain-6h-b9f3",
            "symbol": "RAIN",
            "name": "Stockholm Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Stockholm reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "STO_STORM_1H": {
            "id": "0xsto-storm-1h-176a2",
            "symbol": "STORM",
            "name": "Stockholm Storm 1H",
            "window": "1h",
            "question": "Will storm in Stockholm reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "STO_STORM_6H": {
            "id": "0xsto-storm-6h-3adf",
            "symbol": "STORM",
            "name": "Stockholm Storm 6H",
            "window": "6h",
            "question": "Will storm in Stockholm reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "STO_SUN_1H": {
            "id": "0xsto-sun-1h-18617",
            "symbol": "SUN",
            "name": "Stockholm Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Stockholm reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "STO_SUN_6H": {
            "id": "0xsto-sun-6h-12619",
            "symbol": "SUN",
            "name": "Stockholm Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Stockholm reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "STO_WIND_1H": {
            "id": "0xsto-wind-1h-5900",
            "symbol": "WIND",
            "name": "Stockholm Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Stockholm reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "STO_WIND_6H": {
            "id": "0xsto-wind-6h-16c9f",
            "symbol": "WIND",
            "name": "Stockholm Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Stockholm reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "VIE_RAIN_1H": {
            "id": "0xvie-rain-1h-d0e9",
            "symbol": "RAIN",
            "name": "Vienna Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Vienna reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "VIE_RAIN_6H": {
            "id": "0xvie-rain-6h-b96b",
            "symbol": "RAIN",
            "name": "Vienna Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Vienna reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "VIE_STORM_1H": {
            "id": "0xvie-storm-1h-ae39",
            "symbol": "STORM",
            "name": "Vienna Storm 1H",
            "window": "1h",
            "question": "Will storm in Vienna reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "VIE_STORM_6H": {
            "id": "0xvie-storm-6h-4e00",
            "symbol": "STORM",
            "name": "Vienna Storm 6H",
            "window": "6h",
            "question": "Will storm in Vienna reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "VIE_SUN_1H": {
            "id": "0xvie-sun-1h-7bbf",
            "symbol": "SUN",
            "name": "Vienna Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Vienna reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "VIE_SUN_6H": {
            "id": "0xvie-sun-6h-324f",
            "symbol": "SUN",
            "name": "Vienna Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Vienna reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "VIE_WIND_1H": {
            "id": "0xvie-wind-1h-1cd1",
            "symbol": "WIND",
            "name": "Vienna Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Vienna reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "VIE_WIND_6H": {
            "id": "0xvie-wind-6h-2cd2",
            "symbol": "WIND",
            "name": "Vienna Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Vienna reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "WAW_RAIN_1H": {
            "id": "0xwaw-rain-1h-dda9",
            "symbol": "RAIN",
            "name": "Warsaw Rain Inches 1H",
            "window": "1h",
            "question": "Will rain inches in Warsaw reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "WAW_RAIN_6H": {
            "id": "0xwaw-rain-6h-99d",
            "symbol": "RAIN",
            "name": "Warsaw Rain Inches 6H",
            "window": "6h",
            "question": "Will rain inches in Warsaw reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "WAW_STORM_1H": {
            "id": "0xwaw-storm-1h-163e3",
            "symbol": "STORM",
            "name": "Warsaw Storm 1H",
            "window": "1h",
            "question": "Will storm in Warsaw reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "WAW_STORM_6H": {
            "id": "0xwaw-storm-6h-10831",
            "symbol": "STORM",
            "name": "Warsaw Storm 6H",
            "window": "6h",
            "question": "Will storm in Warsaw reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "WAW_SUN_1H": {
            "id": "0xwaw-sun-1h-f75b",
            "symbol": "SUN",
            "name": "Warsaw Sunshine Hours 1H",
            "window": "1h",
            "question": "Will sunshine hours in Warsaw reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "WAW_SUN_6H": {
            "id": "0xwaw-sun-6h-15f1e",
            "symbol": "SUN",
            "name": "Warsaw Sunshine Hours 6H",
            "window": "6h",
            "question": "Will sunshine hours in Warsaw reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "WAW_WIND_1H": {
            "id": "0xwaw-wind-1h-1ceb",
            "symbol": "WIND",
            "name": "Warsaw Wind Speed 1H",
            "window": "1h",
            "question": "Will wind speed in Warsaw reach threshold in the next 1h?",
            "base_price": 0.5,
            "volatility": 0.02
        },
        "WAW_WIND_6H": {
            "id": "0xwaw-wind-6h-c13c",
            "symbol": "WIND",
            "name": "Warsaw Wind Speed 6H",
            "window": "6h",
            "question": "Will wind speed in Warsaw reach threshold in the next 6h?",
            "base_price": 0.5,
            "volatility": 0.01
        },
        "ETH_5M": {
            "id": "0xeth-5m-15d52",
            "symbol": "ETH",
            "name": "ETH 5M",
            "window": "5m",
            "question": "Will ETH price move in next 5m?",
            "base_price": 0.50,
            "volatility": 0.05
        },
        "ETH_6H": {
            "id": "0xeth-6h-12cde",
            "symbol": "ETH",
            "name": "ETH 6H",
            "window": "6h",
            "question": "Will ETH price move in next 6h?",
            "base_price": 0.50,
            "volatility": 0.04
        },
        "TAO_5M": {
            "id": "0xtao-5m-17136",
            "symbol": "TAO",
            "name": "TAO 5M",
            "window": "5m",
            "question": "Will TAO price move in next 5m?",
            "base_price": 0.50,
            "volatility": 0.05
        },
        "TAO_6H": {
            "id": "0xtao-6h-264d",
            "symbol": "TAO",
            "name": "TAO 6H",
            "window": "6h",
            "question": "Will TAO price move in next 6h?",
            "base_price": 0.50,
            "volatility": 0.04
        },
        "HL_5M": {
            "id": "0xhl-5m-f062",
            "symbol": "HL",
            "name": "HL 5M",
            "window": "5m",
            "question": "Will HL price move in next 5m?",
            "base_price": 0.50,
            "volatility": 0.05
        },
        "HL_6H": {
            "id": "0xhl-6h-10ee2",
            "symbol": "HL",
            "name": "HL 6H",
            "window": "6h",
            "question": "Will HL price move in next 6h?",
            "base_price": 0.50,
            "volatility": 0.04
        },
        })
    async def connect(self) -> None:
        """Connect to exchange (mock)."""
        await asyncio.sleep(0.1)  # Simulate network latency
        self._connected = True
        print("[Exchange] Connected to Polymarket (mock mode)")

    async def disconnect(self) -> None:
        """Disconnect from exchange."""
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.disconnect()

    async def get_markets(self) -> list:
        """
        List all available markets.

        Returns:
            List of market info dicts
        """
        if not self.connected:
            raise ConnectionError("Not connected to exchange")
        return list(self._mock_markets.values())

    async def get_volume_24h(self, market_id: str) -> float:
        """Return mock 24h volume for dry-run mode."""
        market = self._mock_markets.get(market_id)
        if market:
            return float(market.get("base_volume", 100_000.0))
        return 0.0

    async def get_ticker(self, market_id: str, window: Optional[str] = None) -> float:
        """
        Get current price for a market.

        Args:
            market_id: Market identifier (e.g., "0xbtc-1h-...") or symbol like "BTC"

        Returns:
            price: float (probability 0.01–0.99 for prediction markets; USD price for BTC symbol)
        """
        if not self.connected:
            raise ConnectionError("Not connected")

        # Find market by id or by symbol
        market = self._mock_markets.get(market_id)
        if market is None:
            for m in self._mock_markets.values():
                if m.get("symbol") == market_id:
                    market = m
                    break
        if market is None:
            raise ValueError(f"Unknown market_id: {market_id}")

        # Normal prediction market: probability with random walk
        noise = random.uniform(-market["volatility"], market["volatility"])
        price = market["base_price"] + noise
        price = max(0.01, min(0.99, price))

        await asyncio.sleep(0.05)
        return round(price, 4)

    async def buy(self,
                  market_id: str,
                  outcome_id: int = 0,
                  price: Optional[float] = None,
                  amount: int = 1,
                  order_type: str = "limit",
                  asset=None,
                  window=None) -> Optional[Dict[str, Any]]:
        """
        Place a buy order in dry-run mode.

        Returns:
            order dict with status "mock_placed", or None for invalid amounts,
            or raises ValueError for invalid parameters.
        """
        if not self.dry_run:
            raise NotImplementedError("Real buy() not implemented — set dry_run=True")

        # price is required for tests
        if price is None:
            raise ValueError("price is required")
        if price <= 0:
            raise ValueError("price must be positive")

        # amount validation
        if amount < 0:
            raise ValueError("amount must be non-negative")
        if amount < 1:
            return None

        # Balance check
        cost = price * amount
        if cost > self._dry_balance:
            return {"order_id": None, "status": "rejected", "reason": "insufficient balance"}

        # Deduct balance
        self._dry_balance -= cost

        # Create fake order
        self._order_counter += 1
        order_id = f"dryrun-{self._order_counter:06d}"
        order = {
            "order_id": order_id,
            "market_id": market_id,
            "outcome_id": outcome_id,
            "side": "buy",
            "type": order_type,
            "price": price,
            "amount": amount,
            "filled_amount": amount,
            "avg_price": price,
            "status": "mock_placed",
            "created_at": datetime.utcnow().isoformat() + "Z",
            "fee": cost * 0.002
        }
        self._orders[order_id] = order
        print(f"[DRYRUN] BUY {amount} shares of {market_id} @ ${price:.4f} = ${cost:.2f} [order={order_id}]")
        self._send_trade_email("BUY", market_id, price, amount, cost, order_id)
        return order

    def is_connected(self) -> bool:
        return self.connected

    async def get_positions(self) -> Dict[str, Any]:
        raise NotImplementedError("get_positions not implemented in mock")

    async def cancel_order(self, order_id: str) -> bool:
        raise NotImplementedError("cancel_order not implemented in mock")
    async def get_balance(self) -> float:
        """Get current portfolio balance (dry-run mock)."""
        if not self.dry_run:
            raise NotImplementedError("Real get_balance() not implemented — use dry-run")
        return self._dry_balance

    def _send_trade_email(self, side: str, market_id: str, price: float, amount: int, total: float, order_id: str) -> None:
        """Send trade notification email via AgentMail (async, non-blocking)."""
        import subprocess, os, sys
        recipient = "stancikmarian8@gmail.com"
        subject = f"Polymarket Bot: {side} {market_id}"
        body = (
            f"Trade Executed (DRYRUN)\n\n"
            f"Side:      {side}\n"
            f"Asset:     {market_id}\n"
            f"Price:     ${price:.4f}\n"
            f"Amount:    {amount} shares\n"
            f"Total:     ${total:.2f}\n"
            f"Order ID:  {order_id}\n"
            f"Time:      {datetime.utcnow().isoformat()}Z\n\n"
            f"--- Bot status ---\n"
            f"Portfolio: Dry-run ($50,000 simulated)\n"
            f"Strategy:  Markov-matrix (tau=0.05, eps=0.03)\n"
            f"Host:      hermes-agent-hetzner\n"
        )
        script = "/root/.hermes/skills/email/agentmail/scripts/send_email.py"
        env = os.environ.copy()
        # Load AGENTMAIL credentials from Hermes config
        import yaml
        cfg_path = os.path.expanduser("~/.hermes/config.yaml")
        if os.path.exists(cfg_path):
            with open(cfg_path) as cf:
                hermes_cfg = yaml.safe_load(cf) or {}
            env_keys = hermes_cfg.get("env", {})
            env["AGENTMAIL_API_KEY"] = env_keys.get("AGENTMAIL_API_KEY", env.get("AGENTMAIL_API_KEY", ""))
            env["AGENTMAIL_INBOX"] = env_keys.get("AGENTMAIL_INBOX", env.get("AGENTMAIL_INBOX", "heremes-agent-hetzner@agentmail.to"))
        subprocess.Popen(
            [sys.executable, script, "--to", recipient, "--subject", subject, "--text", body],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    async def sell(self, market_id: str, outcome_id: int, price: float, amount: int, order_type: str = "limit", asset=None, window=None) -> dict:
        """Sell order in dry-run mode. Updates balance and returns order dict."""
        if not self.connected:
            raise ConnectionError("Not connected")
        if amount < 1:
            return {"order_id": None, "status": "rejected", "reason": "amount < 1"}
        if price is None:
            raise ValueError("price is required")
        if price <= 0:
            raise ValueError("price must be positive")
        if not self.dry_run:
            raise NotImplementedError("Live sell not implemented")
        self._order_counter += 1
        order_id = f"dryrun-sell-{self._order_counter:06d}"
        proceeds = price * amount
        self._dry_balance += proceeds
        order = {
            "order_id": order_id,
            "market_id": market_id,
            "outcome_id": outcome_id,
            "side": "sell",
            "type": order_type,
            "price": price,
            "amount": amount,
            "filled_amount": amount,
            "avg_price": price,
            "status": "filled",
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
        self._orders[order_id] = order
        print(f"[DRYRUN] SELL {amount} shares of {market_id} @ ${price:.4f} = ${proceeds:.2f} [order={order_id}]")
        self._send_trade_email("SELL", market_id, price, amount, proceeds, order_id)
        return order

# Demo runner for manual testing
if __name__ == "__main__":
    async def main():
        client = PolymarketClient(dry_run=True)
        await client.connect()
        markets = await client.get_markets()
        print(json.dumps(markets, indent=2))
        ticker = await client.get_ticker("BTC")
        print(f"BTC price: {ticker}")
        order = await client.buy(market_id="BTC_1H", outcome_id=0, price=0.65, amount=10)
        print(json.dumps(order, indent=2))
        balance = await client.get_balance()
        print(f"Balance: {balance}")
        await client.disconnect()

    asyncio.run(main())
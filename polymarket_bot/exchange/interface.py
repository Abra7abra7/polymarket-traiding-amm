"""Exchange client interface – abstract base class.

All exchange clients (mock or real) must implement this contract.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseExchangeClient(ABC):
    """Abstract base class defining the exchange client API."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange."""
        pass

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Check if client is connected."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection and clean up resources."""
        pass

    @abstractmethod
    async def __aenter__(self):
        """Async context manager entry."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc, tb):
        """Async context manager exit."""
        pass

    @abstractmethod
    async def get_markets(self) -> List[Dict[str, Any]]:
        """List all available markets."""
        pass

    @abstractmethod
    async def get_ticker(self, market_id: str) -> float:
        """Get current price for a market."""
        pass

    @abstractmethod
    async def get_volume_24h(self, market_id: str) -> float:
        """Get 24-hour trading volume for a market (USD or native token)."""
        pass

    @abstractmethod
    async def buy(
        self,
        market_id: str,
        outcome_id: int = 0,
        price: Optional[float] = None,
        amount: int = 1,
        order_type: str = "limit"
    ) -> Optional[Dict[str, Any]]:
        """Place a buy order."""
        pass

    @abstractmethod
    async def sell(
        self,
        market_id: str,
        outcome_id: int = 0,
        price: Optional[float] = None,
        amount: int = 1
    ) -> Optional[Dict[str, Any]]:
        """Place a sell order."""
        pass

    @abstractmethod
    async def get_balance(self) -> float:
        """Get available cash balance."""
        pass

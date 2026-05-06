"""
Look-ahead Guard — Prevents future data leakage in models and backtests.
"""

from datetime import datetime, timezone
from typing import Optional

class LookAheadGuard:
    """
    Enforces temporal isolation.
    
    Ensures that any data point added to a model or used for a decision
    has a timestamp strictly less than the 'Current Market Time'.
    """

    def __init__(self, start_time: Optional[datetime] = None):
        self.current_time = start_time or datetime.now(timezone.utc)

    def set_time(self, new_time: datetime):
        """Update the internal clock (used during backtesting)."""
        self.current_time = new_time

    def validate(self, data_time: datetime, label: str = "Data"):
        """
        Check if data_time is valid relative to current_time.
        
        Raises:
            ValueError: If data_time is in the 'future'.
        """
        if data_time > self.current_time:
            raise ValueError(
                f"[LOOK-AHEAD VIOLATION] {label} timestamp {data_time} is in the future "
                f"relative to system clock {self.current_time}!"
            )
        return True

    def is_safe(self, data_time: datetime) -> bool:
        """Silent check if data is safe to use."""
        return data_time <= self.current_time

import pytest
from datetime import datetime, timedelta, timezone
from polymarket_bot.utils.validator import LookAheadGuard

def test_look_ahead_guard():
    now = datetime.now(timezone.utc)
    guard = LookAheadGuard(start_time=now)
    
    past = now - timedelta(minutes=5)
    future = now + timedelta(minutes=5)
    
    # Past data is safe
    assert guard.is_safe(past) is True
    assert guard.validate(past) is True
    
    # Future data is not safe
    assert guard.is_safe(future) is False
    with pytest.raises(ValueError, match="LOOK-AHEAD VIOLATION"):
        guard.validate(future)

def test_guard_time_update():
    t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    
    guard = LookAheadGuard(start_time=t1)
    assert guard.is_safe(t2) is False
    
    guard.set_time(t2)
    assert guard.is_safe(t2) is True

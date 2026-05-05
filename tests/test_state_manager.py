import os
import json
import pytest
from unittest.mock import MagicMock
from polymarket_bot.core.state_manager import StateManager

@pytest.fixture
def mock_config(tmp_path):
    config = MagicMock()
    # Create a temp path for the checkpoint
    checkpoint_file = tmp_path / "checkpoint.json"
    config.storage.checkpoint.path = str(checkpoint_file)
    config.storage.checkpoint.enabled = True
    config.storage.checkpoint.interval_minutes = 1
    return config

def test_state_manager_save_load(mock_config):
    manager = StateManager(mock_config)
    test_data = {"test": "data", "value": 123}
    
    # Save
    success = manager.save(test_data)
    assert success is True
    assert os.path.exists(mock_config.storage.checkpoint.path)
    
    # Load
    loaded = manager.load()
    assert loaded["test"] == "data"
    assert loaded["value"] == 123
    assert "timestamp" in loaded

def test_state_manager_disabled(mock_config):
    mock_config.storage.checkpoint.enabled = False
    manager = StateManager(mock_config)
    
    assert manager.save({"data": 1}) is False
    assert manager.should_save() is False

def test_state_manager_should_save_interval(mock_config):
    manager = StateManager(mock_config)
    # Should save first time or if interval passed
    assert manager.should_save() is True
    
    manager.save({"data": 1})
    # Should not save immediately after
    assert manager.should_save() is False

def test_state_manager_load_missing(mock_config):
    manager = StateManager(mock_config)
    # File doesn't exist yet
    assert manager.load() is None

import os
import json
import time
from datetime import datetime, timezone, date
from typing import Dict, Any, Optional
import structlog

class StateManager:
    """Handles persistence of bot state (matrices, positions, stats)."""
    
    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger or structlog.get_logger(__name__)
        self.path = os.path.expanduser(config.storage.checkpoint.path)
        self._last_save_time = 0.0

    def should_save(self) -> bool:
        if not self.config.storage.checkpoint.enabled:
            return False
        now = time.time()
        interval = self.config.storage.checkpoint.interval_minutes * 60
        return (now - self._last_save_time) >= interval

    def load(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.path):
            self.logger.info("No checkpoint found, starting fresh")
            return None

        try:
            with open(self.path, 'r') as f:
                data = json.load(f)
            self.logger.info("Checkpoint loaded", path=self.path)
            return data
        except Exception as e:
            self.logger.error("Failed to load checkpoint", error=str(e))
            return None

    def save(self, bot_state: Dict[str, Any]) -> bool:
        if not self.config.storage.checkpoint.enabled:
            return False

        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            bot_state['timestamp'] = datetime.now(timezone.utc).isoformat()
            
            with open(self.path, 'w') as f:
                json.dump(bot_state, f, indent=2, default=str)
            
            self._last_save_time = time.time()
            self.logger.info("Checkpoint saved", path=self.path)
            return True
        except Exception as e:
            self.logger.error("Failed to save checkpoint", error=str(e))
            return False

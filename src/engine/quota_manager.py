"""
src/engine/quota_manager.py - Adaptive Rate Controller & UTC Quota Tracking.
Maintains a local ledger at ~/.chalk/quota_state.json recording requests and tokens used today.
Automatically resets at 00:00 UTC. Dynamically calculates target chunk durations:
Target Window = clamp(Est. Remaining Lecture Time / Safe Remaining RPD, 12 min, 45 min).
Modes:
- Real-Time (RPD > 15): 12-15 min window, slide threshold = 8
- Balanced (RPD 6-15): 18-25 min window, slide threshold = 10
- Conservation (RPD < 6): 35-45 min window, slide threshold = 14
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Tuple

logger = logging.getLogger("chalk.engine.quota")

LEDGER_DIR = os.path.expanduser("~/.chalk")
LEDGER_PATH = os.path.join(LEDGER_DIR, "quota_state.json")

# Default daily limits for Google AI Studio tier (Gemini 3.5 / 3.1 Flash-Lite has 500 RPD)
DEFAULT_DAILY_RPD_LIMIT = 500


class QuotaManager:
    """
    Tracks local API consumption against Google AI Studio daily quotas
    with UTC date rollover and dynamic elastic window calculation.
    """

    def __init__(self, daily_rpd_limit: int = DEFAULT_DAILY_RPD_LIMIT):
        self.daily_rpd_limit = daily_rpd_limit
        self._ensure_ledger_dir()
        self.state = self._load_or_reset_ledger()

    def set_daily_rpd_limit(self, limit: int):
        """Dynamically updates the daily RPD limit based on the active model preset."""
        self.daily_rpd_limit = max(1, limit)

    def _ensure_ledger_dir(self):
        os.makedirs(LEDGER_DIR, exist_ok=True)

    @staticmethod
    def _current_utc_date_str() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load_or_reset_ledger(self) -> Dict[str, Any]:
        """Loads state from disk or initializes a new entry if day rolled over."""
        current_date = self._current_utc_date_str()
        default_state = {
            "date_utc": current_date,
            "requests_today": 0,
            "input_tokens_today": 0,
            "output_tokens_today": 0,
            "total_tokens_today": 0,
            "last_updated_utc_ts": time.time(),
        }

        if not os.path.exists(LEDGER_PATH):
            self._save_ledger(default_state)
            return default_state

        try:
            with open(LEDGER_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("date_utc") != current_date:
                logger.info(
                    "00:00 UTC rollover detected. Resetting quota ledger (prev: %s -> new: %s)",
                    data.get("date_utc"),
                    current_date,
                )
                self._save_ledger(default_state)
                return default_state

            return data
        except Exception as e:
            logger.warning("Error reading quota state: %s. Re-initializing ledger.", e)
            self._save_ledger(default_state)
            return default_state

    def _save_ledger(self, state: Dict[str, Any]):
        try:
            with open(LEDGER_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error("Failed to save quota state: %s", e)

    def _check_utc_rollover(self):
        current_date = self._current_utc_date_str()
        if self.state.get("date_utc") != current_date:
            logger.info("Midnight UTC reached: resetting requests and tokens count.")
            self.state = {
                "date_utc": current_date,
                "requests_today": 0,
                "input_tokens_today": 0,
                "output_tokens_today": 0,
                "total_tokens_today": 0,
                "last_updated_utc_ts": time.time(),
            }
            self._save_ledger(self.state)

    @property
    def requests_today(self) -> int:
        self._check_utc_rollover()
        return self.state.get("requests_today", 0)

    @property
    def safe_remaining_rpd(self) -> int:
        """Remaining safe requests per day."""
        self._check_utc_rollover()
        used = self.state.get("requests_today", 0)
        return max(0, self.daily_rpd_limit - used)

    @property
    def total_tokens_today(self) -> int:
        self._check_utc_rollover()
        return self.state.get("total_tokens_today", 0)

    def record_usage(self, input_tokens: int = 0, output_tokens: int = 0):
        """Records an API request and associated token consumption in local ledger."""
        self._check_utc_rollover()
        self.state["requests_today"] = self.state.get("requests_today", 0) + 1
        self.state["input_tokens_today"] = self.state.get("input_tokens_today", 0) + input_tokens
        self.state["output_tokens_today"] = self.state.get("output_tokens_today", 0) + output_tokens
        self.state["total_tokens_today"] = (
            self.state["input_tokens_today"] + self.state["output_tokens_today"]
        )
        self.state["last_updated_utc_ts"] = time.time()
        self._save_ledger(self.state)
        logger.info(
            "Recorded API request. Today's usage: %d requests, %d tokens. Remaining RPD: %d",
            self.state["requests_today"],
            self.state["total_tokens_today"],
            self.safe_remaining_rpd,
        )

    def get_adaptive_profile(
        self,
        est_remaining_lecture_min: float = 120.0,
    ) -> Tuple[str, float, float, int]:
        """
        Calculates adaptive rate control profile based on remaining RPD:
        Target Window = clamp(Est. Remaining Lecture / Safe Remaining RPD, 12 min, 45 min)
        Returns:
            mode: "realtime" | "balanced" | "conservation"
            min_window_minutes: minimum elastic boundary trigger time
            max_window_minutes: hard cutoff ceiling
            slide_phash_threshold: perceptual hash distance threshold
        """
        rpd = self.safe_remaining_rpd

        if rpd > 15:
            mode = "realtime"
            slide_thresh = 8
            # Calculate dynamic window clamped between 12 and 15 mins
            raw_window = est_remaining_lecture_min / max(rpd, 1)
            target = max(12.0, min(15.0, raw_window))
            min_window = max(11.0, target - 2.0)
            max_window = min(16.0, target + 1.0)
        elif 6 <= rpd <= 15:
            mode = "balanced"
            slide_thresh = 10
            raw_window = est_remaining_lecture_min / max(rpd, 1)
            target = max(18.0, min(25.0, raw_window))
            min_window = max(16.0, target - 3.0)
            max_window = min(28.0, target + 3.0)
        else:
            mode = "conservation"
            slide_thresh = 14
            raw_window = est_remaining_lecture_min / max(rpd, 1)
            target = max(35.0, min(45.0, raw_window))
            min_window = max(30.0, target - 5.0)
            max_window = 45.0

        return mode, min_window, max_window, slide_thresh

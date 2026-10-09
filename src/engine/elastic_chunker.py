"""
src/engine/elastic_chunker.py - 12 to 45 Minute Dynamic Elastic Boundary Engine.
Evaluates natural conversational pauses (>3.5s silence) and slide advancement keyframes
within the quota-adaptive target window to determine optimal chunk flush boundaries.
Enforces hard cutoffs and coordinates 429 rate-limit backoff recovery.
"""

import time
import logging
from typing import Optional, Callable, Dict, Any, Tuple
from src.engine.quota_manager import QuotaManager
from src.vision.slide_filter import SlideKeyframe

logger = logging.getLogger("chalk.engine.chunker")


class ElasticChunker:
    """
    Coordinates dynamic chunk boundary detection based on:
    1. Quota-adaptive time window (12 - 45 min)
    2. Natural conversational pauses (>3.5s silence)
    3. Slide transition events
    4. Hard window ceiling cutoff
    5. Rate limit (429) backoff management
    """

    def __init__(
        self,
        quota_manager: Optional[QuotaManager] = None,
        on_flush_triggered: Optional[Callable[[str], None]] = None,
        on_rate_limit_backoff: Optional[Callable[[int], None]] = None,
    ):
        self.quota_manager = quota_manager or QuotaManager()
        self.on_flush_triggered = on_flush_triggered
        self.on_rate_limit_backoff = on_rate_limit_backoff

        # Chunk lifecycle tracking
        self.chunk_start_time: float = time.time()
        self.current_chunk_index: int = 1
        self.is_flushing: bool = False

        # 429 Backoff state
        self.in_backoff: bool = False
        self.backoff_until: float = 0.0

        # Slide advancement flag
        self._pending_slide_event: bool = False

    def reset_for_new_session(self):
        """Resets the chunker for a new lecture session."""
        self.chunk_start_time = time.time()
        self.current_chunk_index = 1
        self.is_flushing = False
        self.in_backoff = False
        self.backoff_until = 0.0
        self._pending_slide_event = False

    def notify_slide_advanced(self, keyframe: SlideKeyframe):
        """Notified by screen grabber when a new slide keyframe is detected."""
        self._pending_slide_event = True

    def check_boundary_conditions(
        self,
        current_audio_duration_sec: float,
        is_conversational_pause: bool,
        est_remaining_lecture_min: float = 120.0,
    ) -> Tuple[bool, str]:
        """
        Evaluates whether the active chunk should be flushed.
        Returns (should_flush, trigger_reason).
        """
        now = time.time()

        # Check if currently in 429 backoff
        if self.in_backoff:
            if now < self.backoff_until:
                remaining_sec = int(self.backoff_until - now)
                logger.debug("Currently in 429 backoff (%ds remaining)", remaining_sec)
                return False, f"Backoff active ({remaining_sec}s remaining)"
            else:
                logger.info("429 rate limit backoff period expired. Resuming normal boundary triggers.")
                self.in_backoff = False

        # Query adaptive profile from Quota Manager
        mode, min_window_min, max_window_min, _ = self.quota_manager.get_adaptive_profile(
            est_remaining_lecture_min=est_remaining_lecture_min
        )

        min_window_sec = min_window_min * 60.0
        max_window_sec = max_window_min * 60.0
        elapsed_sec = current_audio_duration_sec

        # 1. Hard Cutoff at ceiling
        if elapsed_sec >= max_window_sec:
            logger.info(
                "Trigger: Hard ceiling cutoff reached (%.1f min >= %.1f min limit)",
                elapsed_sec / 60.0,
                max_window_min,
            )
            self._pending_slide_event = False
            return True, f"Hard Ceiling Cutoff ({max_window_min:.0f} min)"

        # 2. Inside Elastic Target Window
        if elapsed_sec >= min_window_sec:
            # Natural conversational pause (>3.5s silence)
            if is_conversational_pause:
                logger.info(
                    "Trigger: Conversational pause (>3.5s silence) inside target window (%.1f min elapsed)",
                    elapsed_sec / 60.0,
                )
                self._pending_slide_event = False
                return True, "Conversational Pause (>3.5s silence)"

            # Slide advancement keyframe
            if self._pending_slide_event:
                logger.info(
                    "Trigger: Slide transition inside target window (%.1f min elapsed)",
                    elapsed_sec / 60.0,
                )
                self._pending_slide_event = False
                return True, "Slide Transition Keyframe"

        return False, "Window open (accumulating)"

    def handle_rate_limit_429(self, backoff_seconds: int = 300):
        """
        Enters a 5-minute backoff period upon HTTP 429 RESOURCE_EXHAUSTED.
        """
        self.in_backoff = True
        self.backoff_until = time.time() + backoff_seconds
        logger.warning(
            "HTTP 429 rate limit encountered. Initiating %d-second backoff.",
            backoff_seconds,
        )
        if self.on_rate_limit_backoff:
            self.on_rate_limit_backoff(backoff_seconds)

    def set_retry_backoff(self, backoff_seconds: int):
        """
        Enforces a retry backoff delay before allowing subsequent chunk boundaries to trigger.
        """
        self.in_backoff = True
        self.backoff_until = time.time() + max(1.0, float(backoff_seconds))
        logger.info("ElasticChunker entered retry backoff for %ds", backoff_seconds)

    def mark_chunk_flushed(self):
        """Called when a chunk has been successfully packaged and dispatched."""
        self.chunk_start_time = time.time()
        self.current_chunk_index += 1
        self._pending_slide_event = False
        self.is_flushing = False

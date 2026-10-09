"""
src/vision/screen_grabber.py - Privacy-Preserving Screen Capture & Visual Pipeline.
Uses zero global keyloggers (zero pynput, zero Input Monitoring permissions).
Samples primary monitor periodically (default: 4s) or via explicit manual triggers,
evaluating perceptual dHash to detect genuine slide transitions.
Integrates Accessibility Tree Text Extraction and sensitive-app exclusions.
"""

import time
import threading
import logging
from typing import Optional, List, Callable, Tuple
from PIL import Image
import mss

from src.vision.accessibility import AccessibilityTextExtractor
from src.vision.slide_filter import PerceptualSlideFilter, SlideKeyframe

logger = logging.getLogger("chalk.vision.grabber")

# Sensitive applications that should never have their screens scraped
SENSITIVE_APP_KEYWORDS = (
    "1password", "bitwarden", "keychain", "keepass", "vault",
    "banking", "finanzonline", "signal", "whatsapp", "telegram"
)


class EventGatedScreenGrabber:
    """
    Orchestrates screen capture triggered by periodic sampling (default: 4s)
    and perceptual hash slide deduplication.
    Zero Input Monitoring permissions required.
    """

    def __init__(
        self,
        slide_filter: Optional[PerceptualSlideFilter] = None,
        accessibility_extractor: Optional[AccessibilityTextExtractor] = None,
        fallback_interval_sec: float = 4.0,
        on_slide_advanced: Optional[Callable[[SlideKeyframe], None]] = None,
    ):
        self.slide_filter = slide_filter or PerceptualSlideFilter()
        self.ax_extractor = accessibility_extractor or AccessibilityTextExtractor()
        self.fallback_interval_sec = fallback_interval_sec
        self.on_slide_advanced = on_slide_advanced

        # State & Threading
        self._is_running = False
        self._is_paused = False
        self._lock = threading.Lock()
        self._session_start_time = 0.0

        # Accumulated keyframes for current chunk
        self._active_chunk_keyframes: List[SlideKeyframe] = []

        # Worker thread & manual trigger event
        self._worker_thread: Optional[threading.Thread] = None
        self._capture_trigger_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def trigger_manual_capture(self):
        """Manually triggers an immediate screen sampling pass."""
        self._capture_trigger_event.set()

    def start(self, session_start_time: Optional[float] = None):
        """Starts screen sampling worker loop."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._is_paused = False
            self._session_start_time = session_start_time or time.time()
            self._active_chunk_keyframes.clear()
            self.slide_filter.reset()

        # Start background capture loop
        self._worker_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="ChalkScreenGrabberWorker",
        )
        self._worker_thread.start()
        logger.info("Screen grabber started (perceptual diff mode, 0 input monitoring).")

    def pause(self):
        """Pauses visual sampling."""
        with self._lock:
            self._is_paused = True

    def resume(self):
        """Resumes visual sampling."""
        with self._lock:
            self._is_paused = False
            self._capture_trigger_event.set()

    def stop(self):
        """Stops visual sampling and terminates worker thread."""
        with self._lock:
            self._is_running = False
            self._is_paused = False
            self._capture_trigger_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        logger.info("Screen grabber stopped.")

    def _is_sensitive_window_active(self, ocr_text: Optional[str]) -> bool:
        """Checks if the active window or extracted text contains sensitive keywords."""
        if not ocr_text:
            return False
        lower = ocr_text[:500].lower()
        return any(kw in lower for kw in SENSITIVE_APP_KEYWORDS)

    def _capture_loop(self):
        """Main worker loop: samples screen periodically or on manual trigger."""
        with mss.mss() as sct:
            while self._is_running:
                # Wait up to fallback_interval_sec for manual trigger or timeout
                self._capture_trigger_event.wait(timeout=self.fallback_interval_sec)
                self._capture_trigger_event.clear()

                if not self._is_running or self._is_paused:
                    continue

                elapsed = time.time() - self._session_start_time

                # 1. Zero-Token OCR via Accessibility Tree Bypass
                ocr_text = None
                try:
                    ocr_text = self.ax_extractor.extract_active_window_text()
                except Exception as e:
                    logger.debug("Zero-token OCR error: %s", e)

                # Privacy check: skip capture if sensitive app is frontmost
                if self._is_sensitive_window_active(ocr_text):
                    logger.info("Active window appears sensitive. Skipping screen capture for privacy.")
                    continue

                # 2. Screen Grab via mss
                try:
                    # Capture primary presentation monitor
                    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    sct_img = sct.grab(monitor)
                    pil_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

                    # Resize to moderate resolution for efficient pHash and API transmission
                    max_dim = 1600
                    if max(pil_img.size) > max_dim:
                        pil_img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

                    # 3. pHash Slide Deduplication
                    keyframe = self.slide_filter.evaluate_frame(
                        pil_image=pil_img,
                        session_elapsed_sec=elapsed,
                        ocr_text=ocr_text,
                    )

                    if keyframe is not None:
                        with self._lock:
                            self._active_chunk_keyframes.append(keyframe)
                        logger.info(
                            "New unique slide keyframe detected at %s (OCR length: %d)",
                            keyframe.timestamp_str,
                            len(keyframe.ocr_text or ""),
                        )
                        if self.on_slide_advanced:
                            self.on_slide_advanced(keyframe)

                except Exception as e:
                    logger.warning("Screen grab iteration error: %s", e)
                    time.sleep(1.0)

    def get_and_flush_keyframes(self) -> List[SlideKeyframe]:
        """Flushes and returns accumulated unique slide keyframes for the active chunk."""
        with self._lock:
            keyframes = list(self._active_chunk_keyframes)
            self._active_chunk_keyframes.clear()
            return keyframes

    def has_pending_keyframes(self) -> bool:
        """Inspects whether pending keyframes exist without draining them."""
        with self._lock:
            return len(self._active_chunk_keyframes) > 0

    def get_pending_keyframes_count(self) -> int:
        """Returns the count of pending keyframes in the active chunk."""
        with self._lock:
            return len(self._active_chunk_keyframes)

    def reinsert_unprocessed_keyframes(self, keyframes: List[SlideKeyframe]):
        """Reinserts keyframes back into the active queue upon API retry."""
        if not keyframes:
            return
        with self._lock:
            self._active_chunk_keyframes = keyframes + self._active_chunk_keyframes

    @staticmethod
    def capture_screenshot(bbox: Optional[Tuple[int, int, int, int]] = None) -> Image.Image:
        """
        Instant screen capture helper for Snip Tool or active screen queries.
        bbox format: (left, top, right, bottom)
        Uses monitor 0 (virtual desktop spanning all monitors) to properly align coordinates.
        """
        with mss.mss() as sct:
            if bbox:
                left, top, right, bottom = bbox
                monitor = {
                    "left": int(left),
                    "top": int(top),
                    "width": int(right - left),
                    "height": int(bottom - top),
                }
            else:
                # monitor 0 covers all monitors combined in mss
                monitor = sct.monitors[0]

            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

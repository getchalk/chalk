"""
src/vision/screen_grabber.py - Event-Gated Screen Capture & Visual Pipeline.
Listens for presentation navigation events (Right Arrow, Page Down, Space, Mouse Scroll)
via pynput and falls back to a 5-second polling timer using mss.
Integrates Accessibility Tree Bypass (Zero-Token OCR) and pHash deduplication.
"""

import time
import threading
import logging
from typing import Optional, List, Callable
from PIL import Image
import mss
from pynput import keyboard, mouse

from src.vision.accessibility import AccessibilityTextExtractor
from src.vision.slide_filter import PerceptualSlideFilter, SlideKeyframe

logger = logging.getLogger("chalk.vision.grabber")


class EventGatedScreenGrabber:
    """
    Orchestrates screen capture triggered by keyboard/mouse navigation events
    and 5-second fallback polling.
    """

    def __init__(
        self,
        slide_filter: Optional[PerceptualSlideFilter] = None,
        accessibility_extractor: Optional[AccessibilityTextExtractor] = None,
        fallback_interval_sec: float = 5.0,
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

        # Worker threads & input listeners
        self._worker_thread: Optional[threading.Thread] = None
        self._keyboard_listener: Optional[keyboard.Listener] = None
        self._mouse_listener: Optional[mouse.Listener] = None
        self._capture_trigger_event = threading.Event()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, session_start_time: Optional[float] = None):
        """Starts screen sampling and event listeners."""
        with self._lock:
            if self._is_running:
                return
            self._is_running = True
            self._is_paused = False
            self._session_start_time = session_start_time or time.time()
            self._active_chunk_keyframes.clear()
            self.slide_filter.reset()

        # Start pynput keyboard listener
        try:
            self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
            self._keyboard_listener.daemon = True
            self._keyboard_listener.start()
        except Exception as e:
            logger.warning("Could not initialize keyboard listener: %s", e)

        # Start pynput mouse scroll listener
        try:
            self._mouse_listener = mouse.Listener(on_scroll=self._on_mouse_scroll)
            self._mouse_listener.daemon = True
            self._mouse_listener.start()
        except Exception as e:
            logger.warning("Could not initialize mouse scroll listener: %s", e)

        # Start background capture loop
        self._worker_thread = threading.Thread(
            target=self._capture_loop,
            daemon=True,
            name="ChalkScreenGrabberWorker",
        )
        self._worker_thread.start()
        logger.info("Event-gated screen grabber started.")

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
        """Stops visual sampling and cleans up listeners."""
        with self._lock:
            self._is_running = False
            self._is_paused = False
            self._capture_trigger_event.set()

        if self._keyboard_listener:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
            self._keyboard_listener = None

        if self._mouse_listener:
            try:
                self._mouse_listener.stop()
            except Exception:
                pass
            self._mouse_listener = None

        logger.info("Screen grabber stopped.")

    def _on_key_press(self, key):
        """Presentation navigation key detector."""
        if not self._is_running or self._is_paused:
            return

        is_nav_key = False
        try:
            # Check arrow keys and page down/space
            if key in (
                keyboard.Key.right,
                keyboard.Key.page_down,
                keyboard.Key.space,
                keyboard.Key.down,
                keyboard.Key.enter,
                keyboard.Key.left,
                keyboard.Key.page_up,
            ):
                is_nav_key = True
        except Exception:
            pass

        if is_nav_key:
            logger.debug("Presentation nav key pressed -> triggering screen sample")
            self._capture_trigger_event.set()

    def _on_mouse_scroll(self, x, y, dx, dy):
        """Trigger capture on significant mouse scroll."""
        if not self._is_running or self._is_paused:
            return
        # Debounce: only trigger on vertical scroll
        if abs(dy) >= 1:
            self._capture_trigger_event.set()

    def _capture_loop(self):
        """Main worker loop: waits for event trigger or 5s fallback timeout."""
        with mss.mss() as sct:
            while self._is_running:
                # Wait up to fallback_interval_sec for an input event
                triggered = self._capture_trigger_event.wait(timeout=self.fallback_interval_sec)
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

                # 2. Screen Grab via mss
                try:
                    # Capture primary monitor
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

    def reinsert_unprocessed_keyframes(self, keyframes: List[SlideKeyframe]):
        """Reinserts keyframes back into the active queue upon API retry."""
        if not keyframes:
            return
        with self._lock:
            self._active_chunk_keyframes = keyframes + self._active_chunk_keyframes

    @staticmethod
    def capture_screenshot(bbox: Optional[tuple] = None) -> Image.Image:
        """
        Instant screen capture helper for Snip Tool or active screen queries.
        bbox format: (left, top, right, bottom)
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
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]

            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

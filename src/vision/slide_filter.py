"""
src/vision/slide_filter.py - Perceptual Hash (pHash) Slide Deduplication.
Uses imagehash.phash to filter redundant presentation frames.
Discards frames with Hamming distance <= threshold (default: 8; throttled: 14)
compared to the preceding keyframe, saving 80-95% of visual tokens on static slides.
Tags keyframes with session timestamp metadata ([MM:SS]).
"""

import time
import io
import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from PIL import Image
import imagehash

logger = logging.getLogger("chalk.vision.filter")


@dataclass
class SlideKeyframe:
    """Represents a unique, deduplicated slide keyframe."""
    image: Image.Image
    phash: imagehash.ImageHash
    timestamp_str: str          # e.g. "[14:38]"
    elapsed_seconds: float
    ocr_text: Optional[str] = None
    hamming_distance_from_prev: int = 0

    def to_jpeg_bytes(self, quality: int = 85) -> bytes:
        """Compresses slide to JPEG bytes for efficient multimodal transmission."""
        bio = io.BytesIO()
        rgb_img = self.image.convert("RGB")
        rgb_img.save(bio, format="JPEG", quality=quality, optimize=True)
        return bio.getvalue()


class PerceptualSlideFilter:
    """
    Maintains perceptual hash state and filters redundant slide frames.
    """

    def __init__(self, default_threshold: int = 8, throttled_threshold: int = 14):
        self.default_threshold = default_threshold
        self.throttled_threshold = throttled_threshold
        self.current_threshold = default_threshold

        self.last_keyframe_phash: Optional[imagehash.ImageHash] = None
        self.last_keyframe_time: float = 0.0
        self.total_evaluated_frames = 0
        self.total_retained_keyframes = 0

    def set_threshold_mode(self, mode: str):
        """
        Adjusts perceptual hash gating threshold based on rate limit budget.
        'realtime': 8
        'balanced': 10
        'conservation': 14
        """
        if mode == "conservation":
            self.current_threshold = self.throttled_threshold
        elif mode == "balanced":
            self.current_threshold = 10
        else:
            self.current_threshold = self.default_threshold
        logger.info("Slide filter threshold updated to %d (mode: %s)", self.current_threshold, mode)

    def reset(self):
        """Reset deduplication state for a new session."""
        self.last_keyframe_phash = None
        self.last_keyframe_time = 0.0
        self.total_evaluated_frames = 0
        self.total_retained_keyframes = 0

    def evaluate_frame(
        self,
        pil_image: Image.Image,
        session_elapsed_sec: float,
        ocr_text: Optional[str] = None,
    ) -> Optional[SlideKeyframe]:
        """
        Calculates pHash for the captured frame. If Hamming distance > threshold
        compared to the last keyframe, registers and returns a new SlideKeyframe.
        Otherwise returns None (discarded duplicate).
        """
        self.total_evaluated_frames += 1

        try:
            curr_hash = imagehash.phash(pil_image)
        except Exception as e:
            logger.warning("Failed to compute pHash: %s", e)
            return None

        # Format timestamp tag [MM:SS]
        mins = int(session_elapsed_sec // 60)
        secs = int(session_elapsed_sec % 60)
        timestamp_str = f"[{mins:02d}:{secs:02d}]"

        # First frame is always a keyframe
        if self.last_keyframe_phash is None:
            self.last_keyframe_phash = curr_hash
            self.last_keyframe_time = session_elapsed_sec
            self.total_retained_keyframes += 1
            logger.info("Captured initial slide keyframe %s", timestamp_str)
            return SlideKeyframe(
                image=pil_image,
                phash=curr_hash,
                timestamp_str=timestamp_str,
                elapsed_seconds=session_elapsed_sec,
                ocr_text=ocr_text,
                hamming_distance_from_prev=0,
            )

        # Calculate Hamming distance
        distance = curr_hash - self.last_keyframe_phash

        if distance > self.current_threshold:
            # Significant visual change detected (slide advanced)
            self.last_keyframe_phash = curr_hash
            self.last_keyframe_time = session_elapsed_sec
            self.total_retained_keyframes += 1
            logger.info(
                "New slide keyframe %s: Hamming distance %d > threshold %d",
                timestamp_str,
                distance,
                self.current_threshold,
            )
            return SlideKeyframe(
                image=pil_image,
                phash=curr_hash,
                timestamp_str=timestamp_str,
                elapsed_seconds=session_elapsed_sec,
                ocr_text=ocr_text,
                hamming_distance_from_prev=distance,
            )
        else:
            # Redundant frame; discard
            logger.debug(
                "Filtered static slide frame (distance %d <= threshold %d)",
                distance,
                self.current_threshold,
            )
            return None

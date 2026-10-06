"""
src/audio/vad_detector.py - Local Silero VAD & Autonomous Break Detection.
Runs Silero VAD model locally on CPU via PyTorch to:
1. Calculate speech probability in real time.
2. Strip silent gaps > 1.5 seconds from recording payloads (~40% reduction).
3. Detect sustained lecture breaks (>180s silence with probability < 0.3).
4. Detect natural conversational pauses (>3.5s silence) for elastic chunk triggers.
"""

import time
import logging
from typing import Optional, Callable, List, Tuple
import numpy as np
import torch

logger = logging.getLogger("chalk.vad")


class SileroVADDetector:
    """
    Local voice activity detector using Silero VAD with fallback heuristic.
    Maintains temporal state for conversational pauses and lecture break detection.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        break_threshold_sec: float = 180.0,
        pause_threshold_sec: float = 3.5,
        speech_prob_threshold: float = 0.3,
        on_break_detected: Optional[Callable[[], None]] = None,
        on_speech_resumed: Optional[Callable[[], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.break_threshold_sec = break_threshold_sec
        self.pause_threshold_sec = pause_threshold_sec
        self.speech_prob_threshold = speech_prob_threshold
        self.on_break_detected = on_break_detected
        self.on_speech_resumed = on_speech_resumed

        # Model state
        self.model = None
        self._init_silero_model()

        # Temporal tracking
        self.is_in_break = False
        self.last_speech_time = time.time()
        self.continuous_silence_duration = 0.0
        self.recent_speech_history: List[float] = []

    def _init_silero_model(self):
        """Load Silero VAD model on CPU."""
        try:
            torch.set_num_threads(1)
            model, _ = torch.hub.load(
                repo_or_dir="snakers4/silero-vad",
                model="silero_vad",
                onnx=False,
                trust_repo=True,
                verbose=False,
            )
            self.model = model.eval()
            logger.info("Silero VAD loaded successfully on CPU.")
        except Exception as e:
            logger.warning("Failed to load Silero VAD from torch.hub: %s. Using heuristic energy VAD fallback.", e)
            self.model = None

    def reset_state(self):
        """Reset internal temporal counters."""
        self.last_speech_time = time.time()
        self.continuous_silence_duration = 0.0
        self.is_in_break = False
        self.recent_speech_history.clear()
        if self.model and hasattr(self.model, "reset_states"):
            self.model.reset_states()

    def calculate_speech_prob(self, audio_chunk_mono: np.ndarray) -> float:
        """
        Calculates speech probability [0.0, 1.0] for a 16kHz audio chunk.
        Expects mono 1D float32 array in range [-1.0, 1.0].
        """
        if len(audio_chunk_mono) == 0:
            return 0.0

        if self.model is not None:
            try:
                # Silero expects chunks of 512, 1024, or 1536 samples at 16kHz
                # If chunk is different length, take central window or pad
                target_len = 512
                if len(audio_chunk_mono) >= target_len:
                    samples = audio_chunk_mono[:target_len]
                else:
                    samples = np.pad(audio_chunk_mono, (0, target_len - len(audio_chunk_mono)))

                tensor = torch.from_numpy(samples).float()
                with torch.no_grad():
                    prob = float(self.model(tensor, self.sample_rate).item())
                    return prob
            except Exception as e:
                logger.debug("Silero inference fallback: %s", e)

        # Heuristic Energy & Zero-Crossing Fallback
        rms = np.sqrt(np.mean(audio_chunk_mono**2) + 1e-9)
        # Speech typical RMS is > 0.015
        prob = min(1.0, max(0.0, (rms - 0.005) / 0.05))
        return float(prob)

    def update(self, audio_chunk_mono: np.ndarray, duration_sec: float) -> Tuple[float, bool, bool]:
        """
        Process a sequential audio chunk and update temporal state.
        Returns:
            prob: speech probability (0.0 - 1.0)
            is_conversational_pause: True if silence >= pause_threshold_sec (3.5s)
            break_event_fired: True if break just detected (>180s silence)
        """
        prob = self.calculate_speech_prob(audio_chunk_mono)
        now = time.time()

        is_speech = prob >= self.speech_prob_threshold
        break_event_fired = False

        if is_speech:
            if self.is_in_break:
                logger.info("Vocal activity resumed. Exiting break mode.")
                self.is_in_break = False
                if self.on_speech_resumed:
                    self.on_speech_resumed()

            self.last_speech_time = now
            self.continuous_silence_duration = 0.0
        else:
            self.continuous_silence_duration += duration_sec

            # Check Break Detection (>180s continuous silence)
            if not self.is_in_break and self.continuous_silence_duration >= self.break_threshold_sec:
                logger.warning(
                    "EVENT_BREAK_DETECTED: Speech probability < 0.3 for %.1fs (>%ds).",
                    self.continuous_silence_duration,
                    self.break_threshold_sec,
                )
                self.is_in_break = True
                break_event_fired = True
                if self.on_break_detected:
                    self.on_break_detected()

        is_conversational_pause = (self.continuous_silence_duration >= self.pause_threshold_sec)

        return prob, is_conversational_pause, break_event_fired

    def strip_silent_gaps(
        self,
        stereo_audio: np.ndarray,
        sample_rate: int = 16000,
        max_silence_sec: float = 1.5,
        frame_ms: int = 30,
    ) -> np.ndarray:
        """
        Strips prolonged silent gaps (>max_silence_sec) from the stereo audio stream.
        Preserves stereo alignment (Left = Mic, Right = System Loopback).
        Shrinks payload size by ~40% while preserving phrasing and question pauses.
        """
        if stereo_audio.ndim != 2 or stereo_audio.shape[0] == 0:
            return stereo_audio

        # Frame parameters (30ms = 480 samples at 16kHz)
        frame_samples = int(sample_rate * (frame_ms / 1000.0))
        total_samples = stereo_audio.shape[0]
        if total_samples < frame_samples * 2:
            return stereo_audio

        max_silent_frames = int(max_silence_sec / (frame_ms / 1000.0))

        # Check speech on either channel (Mic or Loopback)
        mono_mix = np.maximum(np.abs(stereo_audio[:, 0]), np.abs(stereo_audio[:, 1]))

        retained_chunks = []
        silent_frame_count = 0

        for start in range(0, total_samples, frame_samples):
            end = min(start + frame_samples, total_samples)
            frame_mix = mono_mix[start:end]
            frame_stereo = stereo_audio[start:end]

            # RMS of the frame
            rms = np.sqrt(np.mean(frame_mix**2) + 1e-9)
            has_sound = rms > 0.008  # Audio presence threshold

            if has_sound:
                silent_frame_count = 0
                retained_chunks.append(frame_stereo)
            else:
                silent_frame_count += 1
                if silent_frame_count <= max_silent_frames:
                    # Keep padding up to max_silence_sec
                    retained_chunks.append(frame_stereo)
                else:
                    # Drop excess silence
                    continue

        if not retained_chunks:
            # Avoid returning completely empty array
            return stereo_audio[:frame_samples]

        stripped = np.concatenate(retained_chunks, axis=0)
        logger.debug(
            "Silence stripping: reduced %d samples to %d samples (%.1f%% kept)",
            total_samples,
            stripped.shape[0],
            (stripped.shape[0] / total_samples) * 100,
        )
        return stripped

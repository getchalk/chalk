"""
src/audio/vad_detector.py - Local Silero VAD, Autonomous Break Detection & Cut-List Offset-Map.
Runs Silero VAD model locally on CPU via PyTorch to:
1. Calculate speech probability in real time.
2. Strip silent gaps > 1.5 seconds from recording payloads (~40% reduction).
3. Provide Cut-List Offset-Map (AudioOffsetMap) for exact second-level audio scrubbing between
   original wall-clock time and compressed payload time.
4. Detect sustained lecture breaks (>180s silence with probability < 0.3).
5. Detect natural conversational pauses (>3.5s silence) for elastic chunk triggers.
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable, List, Tuple, Dict, Any, Union
import numpy as np
import torch

logger = logging.getLogger("chalk.vad")


@dataclass
class SegmentMapping:
    """Represents a continuous segment retained during silence stripping."""
    orig_start: float
    orig_end: float
    comp_start: float
    comp_end: float


class AudioOffsetMap:
    """
    Cut-List Offset Map for exact second-level audio scrubbing.
    Maintains bijective piece-wise mappings between the original uncompressed audio
    timeline and the compressed (silence-stripped) audio timeline.
    """

    def __init__(
        self,
        segments: Optional[List[SegmentMapping]] = None,
        original_duration_sec: float = 0.0,
        compressed_duration_sec: float = 0.0,
    ):
        self.segments: List[SegmentMapping] = segments or []
        self.original_duration_sec = float(original_duration_sec)
        self.compressed_duration_sec = float(compressed_duration_sec)

    @property
    def pruned_duration_sec(self) -> float:
        """Total duration of silent gaps removed in seconds."""
        return max(0.0, self.original_duration_sec - self.compressed_duration_sec)

    def map_compressed_to_original(self, compressed_time_sec: float) -> float:
        """
        Maps a timestamp from the compressed/stripped audio back to the exact second
        in the original uncompressed stream.
        """
        if not self.segments:
            return float(compressed_time_sec)

        c_time = float(compressed_time_sec)
        if c_time <= 0.0:
            return float(self.segments[0].orig_start)

        for seg in self.segments:
            if seg.comp_start <= c_time <= seg.comp_end:
                delta = c_time - seg.comp_start
                return float(seg.orig_start + delta)

        if c_time >= self.segments[-1].comp_end:
            return float(self.original_duration_sec)

        # Fallback clamped
        return min(float(self.original_duration_sec), max(0.0, c_time))

    def map_original_to_compressed(self, original_time_sec: float) -> float:
        """
        Maps a timestamp from the original uncompressed audio to the corresponding time
        in the compressed/stripped stream.
        If the original time lands inside a stripped silence gap, maps to the cut seam.
        """
        if not self.segments:
            return float(original_time_sec)

        o_time = float(original_time_sec)
        if o_time <= 0.0:
            return 0.0

        if o_time < self.segments[0].orig_start:
            return 0.0

        for i, seg in enumerate(self.segments):
            if seg.orig_start <= o_time <= seg.orig_end:
                delta = o_time - seg.orig_start
                return float(seg.comp_start + delta)
            if i + 1 < len(self.segments):
                next_seg = self.segments[i + 1]
                if seg.orig_end < o_time < next_seg.orig_start:
                    # Inside stripped gap; map to cut boundary
                    return float(seg.comp_end)

        if o_time >= self.segments[-1].orig_end:
            return float(self.compressed_duration_sec)

        return min(float(self.compressed_duration_sec), max(0.0, o_time))

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the offset map for JSON caching or session storage."""
        return {
            "original_duration_sec": self.original_duration_sec,
            "compressed_duration_sec": self.compressed_duration_sec,
            "segments": [
                {
                    "orig_start": s.orig_start,
                    "orig_end": s.orig_end,
                    "comp_start": s.comp_start,
                    "comp_end": s.comp_end,
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioOffsetMap":
        """Deserializes an offset map from a dictionary."""
        segs = [
            SegmentMapping(
                orig_start=s["orig_start"],
                orig_end=s["orig_end"],
                comp_start=s["comp_start"],
                comp_end=s["comp_end"],
            )
            for s in data.get("segments", [])
        ]
        return cls(
            segments=segs,
            original_duration_sec=data.get("original_duration_sec", 0.0),
            compressed_duration_sec=data.get("compressed_duration_sec", 0.0),
        )


class SileroVADDetector:
    """
    Local voice activity detector using Silero VAD with fallback heuristic.
    Maintains temporal state for conversational pauses, lecture break detection,
    and Cut-List Offset-Map silence stripping.
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
        self.last_offset_map: Optional[AudioOffsetMap] = None

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
        self.last_offset_map = None
        if self.model and hasattr(self.model, "reset_states"):
            self.model.reset_states()

    def calculate_speech_prob(self, audio_chunk_mono: np.ndarray) -> float:
        """
        Calculates speech probability [0.0, 1.0] for a 16kHz audio chunk.
        Expects mono 1D float32 array in range [-1.0, 1.0].
        """
        if len(audio_chunk_mono) == 0:
            return 0.0

        # Low energy silence gating
        rms = np.sqrt(np.mean(audio_chunk_mono**2) + 1e-9)
        if rms < 0.003:
            if self.model is not None and hasattr(self.model, "reset_states"):
                try:
                    self.model.reset_states()
                except Exception:
                    pass
            return 0.0

        if self.model is not None:
            try:
                target_len = 512
                if len(audio_chunk_mono) <= target_len:
                    samples = np.pad(audio_chunk_mono, (0, target_len - len(audio_chunk_mono)))
                    tensor = torch.from_numpy(samples).float()
                    with torch.no_grad():
                        return float(self.model(tensor, self.sample_rate).item())
                else:
                    # Multi-window evaluation: non-overlapping 512-sample frames to preserve model RNN state
                    step = 512
                    max_prob = 0.0
                    for s in range(0, len(audio_chunk_mono) - target_len + 1, step):
                        window = audio_chunk_mono[s : s + target_len]
                        tensor = torch.from_numpy(window).float()
                        with torch.no_grad():
                            p = float(self.model(tensor, self.sample_rate).item())
                        if p > max_prob:
                            max_prob = p
                    return max_prob
            except Exception as e:
                logger.debug("Silero inference fallback: %s", e)

        # Heuristic Energy & Zero-Crossing Fallback
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
        return_offset_map: bool = False,
    ) -> Union[np.ndarray, Tuple[np.ndarray, AudioOffsetMap]]:
        """
        Strips prolonged silent gaps (>max_silence_sec) from the stereo audio stream.
        Preserves stereo alignment (Left = Mic, Right = System Loopback).
        Shrinks payload size by ~40% while preserving phrasing and question pauses.

        When return_offset_map is False (default): returns stripped_audio for 100% backward compatibility.
        When return_offset_map is True: returns (stripped_audio, AudioOffsetMap).
        Also stores the offset map on self.last_offset_map for subsequent query.
        """
        if stereo_audio.ndim != 2 or stereo_audio.shape[0] == 0:
            empty_map = AudioOffsetMap(
                segments=[],
                original_duration_sec=0.0,
                compressed_duration_sec=0.0,
            )
            self.last_offset_map = empty_map
            return (stereo_audio, empty_map) if return_offset_map else stereo_audio

        total_samples = stereo_audio.shape[0]
        original_duration_sec = total_samples / sample_rate

        # Frame parameters (30ms = 480 samples at 16kHz)
        frame_samples = int(sample_rate * (frame_ms / 1000.0))
        if total_samples < frame_samples * 2:
            single_seg = [SegmentMapping(0.0, original_duration_sec, 0.0, original_duration_sec)]
            passthrough_map = AudioOffsetMap(
                segments=single_seg,
                original_duration_sec=original_duration_sec,
                compressed_duration_sec=original_duration_sec,
            )
            self.last_offset_map = passthrough_map
            return (stereo_audio, passthrough_map) if return_offset_map else stereo_audio

        # Pre/Post-roll padding of at least 300ms (10 frames at 30ms)
        min_padding_frames = max(10, int(0.300 / (frame_ms / 1000.0)))
        max_silent_frames = max(min_padding_frames, int(max_silence_sec / (frame_ms / 1000.0)))

        # Evaluate vocal activity using combined mono stream
        mono_mix = 0.5 * (stereo_audio[:, 0] + stereo_audio[:, 1])
        n_frames = (total_samples + frame_samples - 1) // frame_samples
        frame_active = [False] * n_frames
        is_active_state = False

        for f_idx in range(n_frames):
            start = f_idx * frame_samples
            end = min(start + frame_samples, total_samples)
            frame_mono = mono_mix[start:end]
            rms = float(np.sqrt(np.mean(frame_mono**2) + 1e-12))
            prob = self.calculate_speech_prob(frame_mono)

            # Hysteresis thresholding
            if not is_active_state:
                if prob > 0.35 or rms > 0.012:
                    is_active_state = True
            else:
                if prob < 0.15 and rms < 0.004:
                    is_active_state = False

            frame_active[f_idx] = is_active_state

        # Apply at least 300ms pre-roll and post-roll dilation to protect speech boundaries
        dilated_active = list(frame_active)
        for f_idx in range(n_frames):
            if frame_active[f_idx]:
                left_pad = max(0, f_idx - min_padding_frames)
                right_pad = min(n_frames, f_idx + min_padding_frames + 1)
                for p in range(left_pad, right_pad):
                    dilated_active[p] = True

        retained_chunks = []
        retained_intervals: List[List[int]] = []
        silent_frame_count = 0

        for f_idx in range(n_frames):
            start = f_idx * frame_samples
            end = min(start + frame_samples, total_samples)
            frame_stereo = stereo_audio[start:end]

            if dilated_active[f_idx]:
                silent_frame_count = 0
                retained_chunks.append(frame_stereo)
                if retained_intervals and retained_intervals[-1][1] == start:
                    retained_intervals[-1][1] = end
                else:
                    retained_intervals.append([start, end])
            else:
                silent_frame_count += 1
                if silent_frame_count <= max_silent_frames:
                    retained_chunks.append(frame_stereo)
                    if retained_intervals and retained_intervals[-1][1] == start:
                        retained_intervals[-1][1] = end
                    else:
                        retained_intervals.append([start, end])
                else:
                    # Drop excess silence
                    continue

        if not retained_chunks:
            frame_end = min(frame_samples, total_samples)
            retained_chunks = [stereo_audio[:frame_end]]
            retained_intervals = [[0, frame_end]]

        stripped = np.concatenate(retained_chunks, axis=0)

        # Build AudioOffsetMap
        segments: List[SegmentMapping] = []
        curr_comp_samples = 0
        for orig_s_samp, orig_e_samp in retained_intervals:
            seg_len = orig_e_samp - orig_s_samp
            comp_s_samp = curr_comp_samples
            comp_e_samp = curr_comp_samples + seg_len
            curr_comp_samples += seg_len
            segments.append(
                SegmentMapping(
                    orig_start=orig_s_samp / sample_rate,
                    orig_end=orig_e_samp / sample_rate,
                    comp_start=comp_s_samp / sample_rate,
                    comp_end=comp_e_samp / sample_rate,
                )
            )

        offset_map = AudioOffsetMap(
            segments=segments,
            original_duration_sec=original_duration_sec,
            compressed_duration_sec=stripped.shape[0] / sample_rate,
        )
        self.last_offset_map = offset_map

        logger.debug(
            "Silence stripping: reduced %d samples to %d samples (%.1f%% kept), %d segments mapped",
            total_samples,
            stripped.shape[0],
            (stripped.shape[0] / total_samples) * 100,
            len(segments),
        )

        if return_offset_map:
            return stripped, offset_map
        return stripped

    def strip_silent_gaps_with_map(
        self,
        stereo_audio: np.ndarray,
        sample_rate: int = 16000,
        max_silence_sec: float = 1.5,
        frame_ms: int = 30,
    ) -> Tuple[np.ndarray, AudioOffsetMap]:
        """Convenience method returning both stripped audio and the offset map."""
        return self.strip_silent_gaps(
            stereo_audio,
            sample_rate=sample_rate,
            max_silence_sec=max_silence_sec,
            frame_ms=frame_ms,
            return_offset_map=True,
        )

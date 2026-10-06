"""
src/audio/recorder.py - Dual-Channel Audio Capture & Hardware Diarization Mixer.
Captures two independent channels simultaneously at 16kHz:
  Left Channel:  Microphone (in-person lecturer & student questions)
  Right Channel: System Loopback (WASAPI loopback on Windows / ScreenCaptureKit on macOS)
Merges into a synchronized stereo stream for hardware diarization without heavy local ML models.
Maintains a rolling 90-second circular buffer for rewind tool queries and an active chunk buffer.
"""

import sys
import os
import time
import wave
import io
import queue
import threading
import logging
from collections import deque
from typing import Optional, Tuple, Callable
import numpy as np
import sounddevice as sd

from src.audio.vad_detector import SileroVADDetector

logger = logging.getLogger("chalk.audio")


class DualChannelAudioRecorder:
    """
    Simultaneous Dual-Channel Audio Recorder with Hardware Diarization:
    - Left Channel: Microphone via sounddevice
    - Right Channel: System Loopback via soundcard (Windows WASAPI loopback)
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_block_size: int = 1024,
        rewind_buffer_seconds: int = 120,
        vad_detector: Optional[SileroVADDetector] = None,
        on_break_detected: Optional[Callable[[], None]] = None,
        on_speech_resumed: Optional[Callable[[], None]] = None,
    ):
        self.sample_rate = sample_rate
        self.block_size = chunk_block_size
        self.rewind_buffer_seconds = rewind_buffer_seconds

        # VAD detector
        self.vad = vad_detector or SileroVADDetector(
            sample_rate=self.sample_rate,
            on_break_detected=on_break_detected,
            on_speech_resumed=on_speech_resumed,
        )

        # Threading & Control
        self._is_recording = False
        self._is_paused = False
        self._lock = threading.Lock()

        # Buffers
        # Rolling buffer for rewind queries (fixed max length: rewind_buffer_seconds * sample_rate)
        max_rewind_samples = self.sample_rate * self.rewind_buffer_seconds
        self._rolling_rewind_buffer = deque(maxlen=max_rewind_samples)

        # Active recording accumulator (stores stereo frames for current chunk)
        self._active_chunk_samples: list = []

        # Inter-thread audio queues
        self._mic_queue = queue.Queue(maxsize=200)
        self._loopback_queue = queue.Queue(maxsize=200)

        # Background worker threads
        self._mic_stream: Optional[sd.InputStream] = None
        self._loopback_thread: Optional[threading.Thread] = None
        self._mixer_thread: Optional[threading.Thread] = None

        # Stats
        self.total_frames_recorded = 0
        self.latest_speech_prob = 0.0
        self.is_conversational_pause = False

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def start(self):
        """Start dual-channel capture threads."""
        with self._lock:
            if self._is_recording:
                logger.warning("Recorder already running.")
                return

            self._is_recording = True
            self._is_paused = False
            self.vad.reset_state()
            self._active_chunk_samples.clear()

        # 1. Start Mic Stream via sounddevice
        try:
            self._mic_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self.block_size,
                callback=self._mic_callback,
            )
            self._mic_stream.start()
            logger.info("Microphone input stream started (16kHz mono).")
        except Exception as e:
            logger.error("Failed to start sounddevice microphone stream: %s", e)
            self._mic_stream = None

        # 2. Start Loopback capture thread
        self._loopback_thread = threading.Thread(
            target=self._loopback_capture_worker,
            daemon=True,
            name="ChalkLoopbackWorker",
        )
        self._loopback_thread.start()

        # 3. Start Stereo Mixer & VAD worker thread
        self._mixer_thread = threading.Thread(
            target=self._mixer_and_vad_worker,
            daemon=True,
            name="ChalkMixerVADWorker",
        )
        self._mixer_thread.start()

        logger.info("Chalk dual-channel audio pipeline active.")

    def pause(self):
        """Pause audio accumulation (standby mode)."""
        with self._lock:
            self._is_paused = True
            logger.info("Chalk audio recording paused (standby).")

    def resume(self):
        """Resume audio accumulation from pause."""
        with self._lock:
            self._is_paused = False
            self.vad.reset_state()
            logger.info("Chalk audio recording resumed.")

    def stop(self):
        """Stop all recording streams and threads."""
        with self._lock:
            self._is_recording = False
            self._is_paused = False

        if self._mic_stream:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception as e:
                logger.debug("Error closing mic stream: %s", e)
            self._mic_stream = None

        logger.info("Chalk audio recording stopped.")

    def _mic_callback(self, indata, frames, time_info, status):
        """Sounddevice input stream callback."""
        if status:
            logger.debug("Mic stream status: %s", status)
        if self._is_recording:
            try:
                # indata shape: (frames, 1)
                self._mic_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

    def _loopback_capture_worker(self):
        """
        Captures system audio loopback with macOS runtime resilience:
        On Windows: Uses soundcard.all_microphones(include_loopback=True) for native WASAPI loopback.
        On macOS: Detects virtual aggregate/loopback interfaces (e.g. BlackHole, Soundflower).
                  If none is present, gracefully falls back without throwing exceptions, routing Left
                  channel directly from the default microphone and padding Right channel with silence.
        """
        loopback_mic = None
        has_logged_macos_guidance = False

        try:
            import soundcard as sc

            # Attempt finding loopback mic
            mics = sc.all_microphones(include_loopback=True)
            for m in mics:
                m_name_lower = m.name.lower()
                if getattr(m, "isloopback", False) or any(
                    x in m_name_lower
                    for x in ("loopback", "blackhole", "soundflower", "screencapture", "stereo mix")
                ):
                    loopback_mic = m
                    logger.info("Selected loopback capture device: %s", m.name)
                    break
        except Exception as e:
            logger.debug("Loopback discovery notice: %s", e)

        if not loopback_mic and sys.platform == "darwin" and not has_logged_macos_guidance:
            has_logged_macos_guidance = True
            logger.info(
                "macOS Runtime Note: No virtual loopback driver detected (e.g., BlackHole 2ch). "
                "Chalk is routing Left Channel directly from the default microphone while Right Channel "
                "is padded with silence. (To capture remote Zoom/Teams computer audio, run 'brew install blackhole-2ch')."
            )

        while self._is_recording:
            if loopback_mic:
                try:
                    with loopback_mic.recorder(samplerate=self.sample_rate, channels=1, blocksize=self.block_size) as rec:
                        while self._is_recording:
                            data = rec.record(numframes=self.block_size)
                            if data.ndim == 2:
                                data = data[:, 0]
                            try:
                                self._loopback_queue.put_nowait(data.astype(np.float32))
                            except queue.Full:
                                pass
                except Exception as e:
                    logger.warning("Loopback stream encountered an issue: %s. Falling back to synthetic silence.", e)
                    loopback_mic = None
                    time.sleep(0.5)
            else:
                # Synthetic silent loopback for right channel
                synthetic = np.zeros(self.block_size, dtype=np.float32)
                try:
                    self._loopback_queue.put(synthetic, timeout=0.1)
                except queue.Full:
                    pass
                time.sleep(self.block_size / self.sample_rate)

    def _mixer_and_vad_worker(self):
        """
        Synchronizes Mic and Loopback into Stereo (Left=Mic, Right=Loopback),
        evaluates local Silero VAD, updates rolling rewind buffer and active chunk buffer.
        """
        while self._is_recording:
            # 1. Fetch Mic audio
            try:
                mic_chunk = self._mic_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            # 2. Fetch or synchronize Loopback audio
            try:
                loopback_chunk = self._loopback_queue.get_nowait()
            except queue.Empty:
                loopback_chunk = np.zeros_like(mic_chunk)

            # Ensure matching lengths
            min_len = min(len(mic_chunk), len(loopback_chunk))
            mic_chunk = mic_chunk[:min_len]
            loopback_chunk = loopback_chunk[:min_len]

            # 3. Hardware Diarization: Merge into Stereo
            # Left Channel: Mic (Lecturer / Student acoustics)
            # Right Channel: Loopback (Slides / Zoom / Teams computer audio)
            stereo_frame = np.stack([mic_chunk, loopback_chunk], axis=-1)  # Shape: (N, 2)

            # 4. Local Silero VAD evaluation (evaluate mix of both channels)
            combined_mono = 0.6 * mic_chunk + 0.4 * loopback_chunk
            duration_sec = min_len / self.sample_rate
            prob, is_pause, break_fired = self.vad.update(combined_mono, duration_sec)

            self.latest_speech_prob = prob
            self.is_conversational_pause = is_pause

            # 5. Buffer Management
            with self._lock:
                # Always append to rolling rewind buffer (even during pause, so recent context is preserved)
                for i in range(min_len):
                    self._rolling_rewind_buffer.append(stereo_frame[i])

                # Append to active chunk buffer only if not paused
                if not self._is_paused:
                    self._active_chunk_samples.append(stereo_frame)
                    self.total_frames_recorded += min_len

    def get_rewind_audio(self, seconds: int = 90) -> np.ndarray:
        """
        Extract the trailing audio buffer (default: trailing 90 seconds).
        Returns stereo numpy array shape (N, 2) at 16kHz float32.
        """
        with self._lock:
            num_samples = min(len(self._rolling_rewind_buffer), int(seconds * self.sample_rate))
            if num_samples == 0:
                return np.zeros((0, 2), dtype=np.float32)

            recent_frames = list(self._rolling_rewind_buffer)[-num_samples:]
            return np.array(recent_frames, dtype=np.float32)

    def get_and_flush_active_chunk(self, strip_silence: bool = True) -> np.ndarray:
        """
        Flushes and returns all accumulated stereo audio since last flush.
        Optionally strips prolonged silent gaps (>1.5s) to shrink payload by ~40%.
        """
        with self._lock:
            if not self._active_chunk_samples:
                return np.zeros((0, 2), dtype=np.float32)

            concatenated = np.concatenate(self._active_chunk_samples, axis=0)
            self._active_chunk_samples.clear()

        if strip_silence and len(concatenated) > 0:
            concatenated = self.vad.strip_silent_gaps(concatenated, sample_rate=self.sample_rate)

        return concatenated

    def get_active_buffer_duration_sec(self) -> float:
        """Returns the current duration in seconds accumulated in the active chunk."""
        with self._lock:
            if not self._active_chunk_samples:
                return 0.0
            total_samples = sum(len(c) for c in self._active_chunk_samples)
            return total_samples / self.sample_rate

    def reinsert_unprocessed_chunk(self, stereo_audio: np.ndarray):
        """
        Reinserts audio back into the active recording queue upon API failure or HTTP 429
        so no lecture audio is lost during temporary network or rate-limit dropouts.
        """
        if len(stereo_audio) == 0:
            return
        with self._lock:
            logger.info("Re-inserting %d audio samples into active recording queue.", len(stereo_audio))
            # Prepend back to active chunk
            self._active_chunk_samples.insert(0, stereo_audio)

    @staticmethod
    def audio_to_wav_bytes(stereo_audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        """
        Converts a stereo float32 numpy array to 16-bit PCM WAV bytes in memory.
        """
        if len(stereo_audio) == 0:
            return b""

        # Normalize and convert to 16-bit signed PCM
        int16_audio = (np.clip(stereo_audio, -1.0, 1.0) * 32767).astype(np.int16)

        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)  # 16-bit = 2 bytes
            wf.setframerate(sample_rate)
            wf.writeframes(int16_audio.tobytes())

        return bio.getvalue()

    @staticmethod
    def save_wav_file(file_path: str, stereo_audio: np.ndarray, sample_rate: int = 16000):
        """Saves stereo audio to a local WAV file."""
        wav_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(stereo_audio, sample_rate)
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(wav_bytes)
        logger.info("Saved WAV file: %s (%d bytes)", file_path, len(wav_bytes))

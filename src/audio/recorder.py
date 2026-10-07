"""
src/audio/recorder.py - Dual-Channel Audio Capture, Hardware Diarization Mixer & Persistent Disk Journal.

Captures two independent channels simultaneously at 16kHz:
  Left Channel:  Microphone (in-person lecturer & student questions)
  Right Channel: System Loopback (WASAPI loopback on Windows / ScreenCaptureKit / virtual driver on macOS)
Merges into a synchronized stereo stream for hardware diarization without heavy local ML models.

Fault-Tolerance & Storage Architecture:
- Flushes audio continuously to persistent 30-second segments on disk (~/.chalk/sessions/<SESSION_ID>/seg_XXXX.wav)
  via SessionJournal, preventing RAM accumulation during 7-hour lectures.
- Retains a rolling 90-second circular buffer in memory for instant interactive queries.
- Exposes audio compression utilities (<20MB inline payloads) for Gemini API ingestion.
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
from typing import Optional, Tuple, Callable, List, Dict, Any, Union
import numpy as np
import sounddevice as sd

from src.audio.vad_detector import SileroVADDetector, AudioOffsetMap
from src.engine.journal import SessionJournal
from src.audio.capture import compress_audio_payload, audio_to_wav_bytes, wav_bytes_to_audio

logger = logging.getLogger("chalk.audio")


class _RollingRewindBufferProxy:
    """Proxy providing backward-compatibility for direct .append() and len() on rewind buffer."""
    def __init__(self, recorder: "DualChannelAudioRecorder"):
        self._rec = recorder

    def append(self, sample: Any):
        s = np.asarray(sample, dtype=np.float32)
        if s.ndim == 1:
            s = s.reshape(1, -1)
        self._rec._append_to_ring_locked(s)

    def __len__(self) -> int:
        return self._rec._ring_count


class DualChannelAudioRecorder:
    """
    Simultaneous Dual-Channel Audio Recorder with Hardware Diarization and Persistent Disk Journal:
    - Left Channel: Microphone via sounddevice
    - Right Channel: System Loopback via soundcard (WASAPI on Windows / virtual device on macOS)
    - Fault-Tolerance: Flushes 30-second segments to disk journal
    - Low Latency: Rolling 90s rewind buffer in RAM
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_block_size: int = 1024,
        rewind_buffer_seconds: int = 90,
        vad_detector: Optional[SileroVADDetector] = None,
        on_break_detected: Optional[Callable[[], None]] = None,
        on_speech_resumed: Optional[Callable[[], None]] = None,
        session_id: Optional[str] = None,
        journal: Optional[SessionJournal] = None,
        journal_dir: Optional[str] = None,
        enable_journal: bool = True,
        segment_duration_sec: float = 30.0,
    ):
        self.sample_rate = sample_rate
        self.block_size = chunk_block_size
        self.rewind_buffer_seconds = rewind_buffer_seconds
        self.segment_duration_sec = segment_duration_sec
        self.enable_journal = enable_journal
        self.session_id = session_id
        self.journal_dir = journal_dir

        # VAD detector
        self.vad = vad_detector or SileroVADDetector(
            sample_rate=self.sample_rate,
            on_break_detected=on_break_detected,
            on_speech_resumed=on_speech_resumed,
        )

        # Persistent Disk Journal
        if journal is not None:
            self.journal = journal
        elif enable_journal:
            self.journal = SessionJournal(session_id=session_id, base_dir=journal_dir)
        else:
            self.journal = None

        # Threading & Control
        self._is_recording = False
        self._is_paused = False
        self._lock = threading.Lock()

        # Buffers:
        # 1. Fixed pre-allocated circular ring buffer for rewind queries (90s x 16kHz x 2ch x 4B = 11.52 MB)
        self._ring_capacity = self.sample_rate * self.rewind_buffer_seconds
        self._ring_buffer = np.zeros((self._ring_capacity, 2), dtype=np.float32)
        self._ring_head = 0
        self._ring_count = 0
        self._rolling_rewind_buffer = _RollingRewindBufferProxy(self)

        # 2. In-progress 30-second segment buffer (flushed to disk journal upon reaching 30s)
        self._current_segment_samples: List[np.ndarray] = []
        self._current_segment_sample_count: int = 0
        self._current_segment_start_wall_clock: float = time.time()

        # 3. Active chunk tracking: IDs of disk segments waiting to be dispatched to Gemini
        self._pending_chunk_segment_ids: List[str] = []

        # 4. Fallback in-memory list (only used when journal is disabled)
        self._fallback_active_chunk_samples: List[np.ndarray] = []

        # 5. Non-blocking asynchronous disk writer queue & thread
        self._disk_writer_queue = queue.Queue()
        self._disk_writer_thread: Optional[threading.Thread] = None

        # Inter-thread audio queues
        self._mic_queue = queue.Queue(maxsize=200)
        self._loopback_queue = queue.Queue(maxsize=200)

        # Background worker threads
        self._mic_stream: Optional[sd.InputStream] = None
        self._loopback_thread: Optional[threading.Thread] = None
        self._mixer_thread: Optional[threading.Thread] = None

        # Stats & Watchdog
        self.total_frames_recorded = 0
        self.latest_speech_prob = 0.0
        self.is_conversational_pause = False
        self.is_mic_silent_warning = False
        self._last_mic_sound_time = time.time()

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    def start(self, session_id: Optional[str] = None):
        """Start dual-channel capture threads and initialize recording state."""
        with self._lock:
            if self._is_recording:
                logger.warning("Recorder already running.")
                return

            self._is_recording = True
            self._is_paused = False
            self.vad.reset_state()
            self._current_segment_samples.clear()
            self._current_segment_sample_count = 0
            self._current_segment_start_wall_clock = time.time()
            self._pending_chunk_segment_ids.clear()
            self._fallback_active_chunk_samples.clear()

            if self.enable_journal and self.journal is None:
                self.journal = SessionJournal(session_id=session_id or self.session_id, base_dir=self.journal_dir)

        # 1. Start background disk writer worker
        if self._disk_writer_thread is None or not self._disk_writer_thread.is_alive():
            self._disk_writer_thread = threading.Thread(
                target=self._disk_writer_worker,
                daemon=True,
                name="ChalkDiskWriterWorker",
            )
            self._disk_writer_thread.start()

        # 2. Start Mic Stream via sounddevice
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

        # 3. Start Loopback capture thread
        self._loopback_thread = threading.Thread(
            target=self._loopback_capture_worker,
            daemon=True,
            name="ChalkLoopbackWorker",
        )
        self._loopback_thread.start()

        # 4. Start Stereo Mixer & VAD worker thread
        self._mixer_thread = threading.Thread(
            target=self._mixer_and_vad_worker,
            daemon=True,
            name="ChalkMixerVADWorker",
        )
        self._mixer_thread.start()

        logger.info("Chalk dual-channel audio pipeline active (Journal=%s).", bool(self.journal))

    def pause(self):
        """Pause audio accumulation (standby mode)."""
        with self._lock:
            self._is_paused = True
            # Flush partial segment on pause to ensure clean boundary
            if self._current_segment_samples:
                self._flush_current_segment_locked()
            logger.info("Chalk audio recording paused (standby).")

    def resume(self):
        """Resume audio accumulation from pause."""
        with self._lock:
            self._is_paused = False
            self._current_segment_start_wall_clock = time.time()
            self._last_mic_sound_time = time.time()
            self.vad.reset_state()
            logger.info("Chalk audio recording resumed.")

    def stop(self):
        """Stop all recording streams and flush remaining segments to disk."""
        with self._lock:
            self._is_recording = False
            self._is_paused = False
            # Flush any trailing segment frames to disk journal
            if self._current_segment_samples:
                self._flush_current_segment_locked()

        if self._mic_stream:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception as e:
                logger.debug("Error closing mic stream: %s", e)
            self._mic_stream = None

        # Ensure disk writes are flushed
        try:
            self._disk_writer_queue.join()
        except Exception:
            pass

        logger.info("Chalk audio recording stopped.")

    def _flush_current_segment_locked(self):
        """Dispatches the currently accumulating buffer to asynchronous writer queue without blocking."""
        if not self._current_segment_samples or not self.journal:
            return

        segment_audio = np.concatenate(self._current_segment_samples, axis=0)
        duration_sec = float(len(segment_audio) / self.sample_rate)
        start_wall_clock = self._current_segment_start_wall_clock

        if self._disk_writer_thread is not None and self._disk_writer_thread.is_alive():
            self._disk_writer_queue.put((segment_audio, start_wall_clock, duration_sec))
        else:
            seg_info = self.journal.write_segment(
                audio_data=segment_audio,
                start_wall_clock=start_wall_clock,
                duration_sec=duration_sec,
                sample_rate=self.sample_rate,
                status="pending",
            )
            self._pending_chunk_segment_ids.append(seg_info["id"])

        self._current_segment_samples.clear()
        self._current_segment_sample_count = 0
        self._current_segment_start_wall_clock = time.time()

    def _disk_writer_worker(self):
        """Background worker thread writing audio segments to disk without blocking audio loop."""
        while True:
            try:
                item = self._disk_writer_queue.get()
                if item is None:
                    break
                segment_audio, start_wall_clock, duration_sec = item
                if self.journal:
                    seg_info = self.journal.write_segment(
                        audio_data=segment_audio,
                        start_wall_clock=start_wall_clock,
                        duration_sec=duration_sec,
                        sample_rate=self.sample_rate,
                        status="pending",
                    )
                    with self._lock:
                        self._pending_chunk_segment_ids.append(seg_info["id"])
                    logger.debug("Asynchronously wrote segment %s (%.1fs)", seg_info["id"], duration_sec)
            except Exception as e:
                logger.error("Failed to write segment in background worker: %s", e)
            finally:
                self._disk_writer_queue.task_done()

    def _mic_callback(self, indata, frames, time_info, status):
        """Sounddevice input stream callback."""
        if status:
            logger.debug("Mic stream status: %s", status)
        if self._is_recording:
            try:
                self._mic_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                pass

    def _loopback_capture_worker(self):
        """
        Captures system audio loopback:
        On Windows: Uses soundcard.all_microphones(include_loopback=True) for WASAPI loopback.
        On macOS: Detects virtual aggregate/loopback interfaces (e.g. BlackHole, Soundflower).
                  If none is present, gracefully routes Left channel from default microphone
                  and pads Right channel with silence.
        """
        loopback_mic = None
        has_logged_macos_guidance = False

        try:
            import soundcard as sc

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
                "Routing Left Channel from default mic while Right Channel is padded with silence."
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
        Flushes 30-second segments to disk journal to avoid unbounded RAM growth.
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

            # 3. Hardware Diarization: Merge into Stereo (Left=Mic, Right=Loopback)
            stereo_frame = np.stack([mic_chunk, loopback_chunk], axis=-1)  # Shape: (N, 2)

            # 4. Local Silero VAD evaluation & Microphone Watchdog
            combined_mono = 0.6 * mic_chunk + 0.4 * loopback_chunk
            duration_sec = min_len / self.sample_rate
            prob, is_pause, break_fired = self.vad.update(combined_mono, duration_sec)

            self.latest_speech_prob = prob
            self.is_conversational_pause = is_pause

            # Microphone silence watchdog (alert if RMS is zero for >10 seconds while recording)
            mic_rms = float(np.sqrt(np.mean(mic_chunk**2) + 1e-12))
            if mic_rms > 0.001:
                self._last_mic_sound_time = time.time()
                self.is_mic_silent_warning = False
            elif not self._is_paused and (time.time() - self._last_mic_sound_time > 10.0):
                if not self.is_mic_silent_warning:
                    self.is_mic_silent_warning = True
                    logger.warning("Microphone watchdog: silence detected for >10 seconds while recording!")

            # 5. Buffer Management
            with self._lock:
                # Fast vectorized write into pre-allocated 11.5MB circular numpy array
                self._append_to_ring_locked(stereo_frame)

                # Active chunk accumulation
                if not self._is_paused:
                    self.total_frames_recorded += min_len
                    if self.journal:
                        self._current_segment_samples.append(stereo_frame)
                        self._current_segment_sample_count += min_len
                        # Check 30-second segment threshold
                        if self._current_segment_sample_count >= int(self.segment_duration_sec * self.sample_rate):
                            self._flush_current_segment_locked()
                    else:
                        self._fallback_active_chunk_samples.append(stereo_frame)

    def _append_to_ring_locked(self, stereo_frame: np.ndarray):
        """Fast vectorized write into pre-allocated circular numpy array (O(1) memory)."""
        N = len(stereo_frame)
        if N >= self._ring_capacity:
            self._ring_buffer[:] = stereo_frame[-self._ring_capacity:]
            self._ring_head = 0
            self._ring_count = self._ring_capacity
        else:
            end1 = min(self._ring_head + N, self._ring_capacity)
            l1 = end1 - self._ring_head
            self._ring_buffer[self._ring_head:end1] = stereo_frame[:l1]
            if l1 < N:
                l2 = N - l1
                self._ring_buffer[0:l2] = stereo_frame[l1:]
                self._ring_head = l2
            else:
                self._ring_head = (self._ring_head + N) % self._ring_capacity
            self._ring_count = min(self._ring_count + N, self._ring_capacity)

    def get_rewind_audio(self, seconds: int = 90) -> np.ndarray:
        """
        Extract the trailing audio buffer (default: trailing 90 seconds) from pre-allocated RAM ring buffer.
        Returns stereo numpy array shape (N, 2) at 16kHz float32 with O(1) performance and zero heap bloat.
        """
        with self._lock:
            num_samples = min(self._ring_count, int(seconds * self.sample_rate))
            if num_samples == 0:
                return np.zeros((0, 2), dtype=np.float32)

            start_pos = (self._ring_head - num_samples) % self._ring_capacity
            if start_pos + num_samples <= self._ring_capacity:
                return self._ring_buffer[start_pos : start_pos + num_samples].copy()
            else:
                part1 = self._ring_buffer[start_pos:]
                part2 = self._ring_buffer[: (start_pos + num_samples) % self._ring_capacity]
                return np.concatenate([part1, part2], axis=0)

    def get_and_flush_active_chunk(
        self,
        strip_silence: bool = True,
        return_offset_map: bool = False,
    ) -> Union[np.ndarray, Tuple[np.ndarray, Optional[AudioOffsetMap]]]:
        """
        Flushes and returns all accumulated stereo audio for the active chunk.
        Flushes partial in-progress segment to disk journal, reads all pending segment files,
        resets active segment tracking, and optionally strips silent gaps.
        """
        with self._lock:
            # 1. Flush in-progress segment to disk
            if self._current_segment_samples:
                self._flush_current_segment_locked()

        # Wait for any in-flight asynchronous segment disk writes to complete
        try:
            self._disk_writer_queue.join()
        except Exception:
            pass

        with self._lock:
            # 2. Retrieve audio from disk journal or in-memory fallback
            if self.journal:
                seg_ids = list(self._pending_chunk_segment_ids)
                self._pending_chunk_segment_ids.clear()
                if seg_ids:
                    concatenated, _ = self.journal.read_segments_audio(seg_ids)
                else:
                    concatenated = np.zeros((0, 2), dtype=np.float32)
            else:
                if self._fallback_active_chunk_samples:
                    concatenated = np.concatenate(self._fallback_active_chunk_samples, axis=0)
                    self._fallback_active_chunk_samples.clear()
                else:
                    concatenated = np.zeros((0, 2), dtype=np.float32)

        # 3. Strip silence if requested
        offset_map = None
        if strip_silence and len(concatenated) > 0:
            if return_offset_map:
                concatenated, offset_map = self.vad.strip_silent_gaps(
                    concatenated, sample_rate=self.sample_rate, return_offset_map=True
                )
            else:
                concatenated = self.vad.strip_silent_gaps(
                    concatenated, sample_rate=self.sample_rate, return_offset_map=False
                )
                offset_map = self.vad.last_offset_map

        if return_offset_map:
            return concatenated, offset_map
        return concatenated

    def get_active_buffer_duration_sec(self) -> float:
        """Returns the current duration in seconds accumulated in the active chunk."""
        with self._lock:
            current_unflushed = self._current_segment_sample_count / self.sample_rate
            if self.journal:
                journal_dur = 0.0
                for seg_id in self._pending_chunk_segment_ids:
                    seg = self.journal.get_segment(seg_id)
                    if seg:
                        journal_dur += float(seg.get("duration_sec", 0.0))
                return journal_dur + current_unflushed
            else:
                total_samples = sum(len(c) for c in self._fallback_active_chunk_samples)
                return (total_samples / self.sample_rate) + current_unflushed

    def reinsert_segment_ids(self, seg_ids: List[str]):
        """
        Reinserts existing segment IDs into the pending chunk queue without duplicating
        disk audio or losing offset-map alignment.
        """
        if not seg_ids:
            return
        with self._lock:
            for sid in reversed(seg_ids):
                if sid not in self._pending_chunk_segment_ids:
                    self._pending_chunk_segment_ids.insert(0, sid)
            logger.info("Re-queued %d segment IDs into active recording queue.", len(seg_ids))

    def reinsert_unprocessed_chunk(self, stereo_audio: np.ndarray):
        """
        Reinserts audio back into the active recording queue upon API failure or HTTP 429
        so no lecture audio is lost during temporary network or rate-limit dropouts.
        """
        if len(stereo_audio) == 0:
            return
        with self._lock:
            logger.info("Re-inserting %d audio samples into active recording queue.", len(stereo_audio))
            if self.journal:
                dur = len(stereo_audio) / self.sample_rate
                seg_info = self.journal.write_segment(
                    audio_data=stereo_audio,
                    start_wall_clock=time.time(),
                    duration_sec=dur,
                    sample_rate=self.sample_rate,
                    status="pending",
                )
                self._pending_chunk_segment_ids.insert(0, seg_info["id"])
            else:
                self._fallback_active_chunk_samples.insert(0, stereo_audio)

    # Static compression and serialization helpers
    @staticmethod
    def audio_to_wav_bytes(stereo_audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        """Converts a stereo float32 numpy array to 16-bit PCM WAV bytes in memory."""
        return audio_to_wav_bytes(stereo_audio, sample_rate=sample_rate)

    @staticmethod
    def save_wav_file(file_path: str, stereo_audio: np.ndarray, sample_rate: int = 16000):
        """Saves stereo audio to a local WAV file."""
        wav_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(stereo_audio, sample_rate)
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, "wb") as f:
            f.write(wav_bytes)
        logger.info("Saved WAV file: %s (%d bytes)", file_path, len(wav_bytes))

    @staticmethod
    def compress_audio(
        wav_bytes_or_audio: Union[bytes, np.ndarray], target_kbps: int = 32, sample_rate: int = 16000
    ) -> Tuple[bytes, str]:
        """Compresses audio payload under 20MB using AAC/m4a or downsampled PCM."""
        return compress_audio_payload(wav_bytes_or_audio, target_kbps=target_kbps, sample_rate=sample_rate)

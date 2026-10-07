"""
src/engine/journal.py - Persistent Disk Journal & Crash Recovery Engine.

Provides fault-tolerant session recording to disk:
1. Path structure: ~/.chalk/sessions/<SESSION_ID>/
2. Segments: Continuous 30-second stereo WAV segments (seg_0001.wav, seg_0002.wav, etc.)
3. Atomic Manifest: manifest.json with transactional updates via atomic rename
4. Startup Recovery: recover_unprocessed_sessions() scans for incomplete or interrupted sessions
"""

import os
import io
import re
import time
import json
import uuid
import wave
import shutil
import logging
import threading
from typing import Optional, List, Dict, Any, Tuple, Union
import numpy as np

logger = logging.getLogger("chalk.engine.journal")

DEFAULT_SESSIONS_DIR = os.path.expanduser("~/.chalk/sessions")


class SessionJournal:
    """
    Robust disk journaling engine for audio recording sessions.
    Stores audio continuously in 30-second segments with atomic manifest updates.
    """

    def __init__(
        self,
        session_id: Optional[str] = None,
        base_dir: Optional[str] = None,
        create_if_missing: bool = True,
    ):
        self.base_dir = os.path.abspath(os.path.expanduser(base_dir or DEFAULT_SESSIONS_DIR))
        self.session_id = session_id or self._generate_session_id()
        self.session_dir = os.path.join(self.base_dir, self.session_id)
        self.manifest_path = os.path.join(self.session_dir, "manifest.json")
        self._lock = threading.Lock()

        if create_if_missing:
            os.makedirs(self.session_dir, exist_ok=True)

        # Initialize or load manifest
        with self._lock:
            if os.path.exists(self.manifest_path):
                self.manifest = self._read_manifest_file()
                # Compute current segment counter from existing segments
                self.segment_counter = self._calculate_segment_counter()
            else:
                self.manifest = {
                    "session_id": self.session_id,
                    "created_at": time.time(),
                    "status": "recording",  # "recording", "completed", "recovering"
                    "segments": [],
                }
                self.segment_counter = 0
                if create_if_missing:
                    self._save_manifest_atomic_locked()

    @staticmethod
    def _generate_session_id() -> str:
        """Generates a unique, timestamped session identifier."""
        ts = int(time.time())
        rand_suffix = uuid.uuid4().hex[:8]
        return f"sess_{ts}_{rand_suffix}"

    def _read_manifest_file(self) -> Dict[str, Any]:
        """Reads and parses the manifest JSON file from disk with autonomous recovery on corruption."""
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "segments" in data:
                    return data
        except Exception as e:
            logger.warning("Failed to read or parse manifest at %s: %s. Rebuilding from disk segments...", self.manifest_path, e)

        # Autonomously rebuild manifest from disk seg_*.wav files
        return self._rebuild_manifest_from_disk_locked()

    def _rebuild_manifest_from_disk_locked(self) -> Dict[str, Any]:
        """Scans session directory for seg_*.wav files to reconstruct lost or corrupt manifest."""
        reconstructed_segments = []
        max_idx = 0

        if os.path.isdir(self.session_dir):
            wav_pattern = re.compile(r"^seg_(\d+)\.wav$")
            try:
                for fname in sorted(os.listdir(self.session_dir)):
                    match = wav_pattern.match(fname)
                    if match:
                        idx = int(match.group(1))
                        if idx > max_idx:
                            max_idx = idx
                        fpath = os.path.join(self.session_dir, fname)
                        dur = 30.0
                        try:
                            with wave.open(fpath, "rb") as wf:
                                dur = float(wf.getnframes() / max(1, wf.getframerate()))
                        except Exception:
                            # Estimate duration from file size
                            sz = os.path.getsize(fpath)
                            dur = max(0.1, float(sz - 44) / 64000.0)

                        mtime = os.path.getmtime(fpath)
                        reconstructed_segments.append({
                            "id": f"seg_{idx:04d}",
                            "file": fname,
                            "start_wall_clock": mtime,
                            "duration_sec": dur,
                            "status": "pending",
                        })
            except Exception as scan_err:
                logger.error("Error scanning disk segments in %s: %s", self.session_dir, scan_err)

        manifest = {
            "session_id": self.session_id,
            "created_at": time.time(),
            "status": "recording",
            "segments": reconstructed_segments,
        }
        self.manifest = manifest
        self.segment_counter = max_idx
        try:
            self._save_manifest_atomic_locked()
            logger.info("Successfully rebuilt manifest with %d segments (counter=%d)", len(reconstructed_segments), max_idx)
        except Exception as save_err:
            logger.error("Could not persist rebuilt manifest: %s", save_err)

        return manifest

    def _calculate_segment_counter(self) -> int:
        """Finds highest segment index across manifest and disk files to avoid overwriting."""
        max_idx = 0
        for seg in self.manifest.get("segments", []):
            seg_id = seg.get("id", "")
            if seg_id.startswith("seg_"):
                try:
                    idx = int(seg_id.split("_")[1])
                    if idx > max_idx:
                        max_idx = idx
                except ValueError:
                    pass

        # Also inspect disk directory in case manifest was partially out of sync
        if os.path.isdir(self.session_dir):
            wav_pattern = re.compile(r"^seg_(\d+)\.wav$")
            try:
                for fname in os.listdir(self.session_dir):
                    match = wav_pattern.match(fname)
                    if match:
                        idx = int(match.group(1))
                        if idx > max_idx:
                            max_idx = idx
            except Exception:
                pass

        return max_idx

    def _save_manifest_atomic_locked(self):
        """Atomically writes manifest to disk via temporary file rename."""
        os.makedirs(self.session_dir, exist_ok=True)
        tmp_name = f"manifest.json.tmp.{os.getpid()}.{threading.get_ident()}_{time.time_ns()}"
        tmp_path = os.path.join(self.session_dir, tmp_name)
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.manifest, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.manifest_path)
        except Exception as e:
            logger.error("Failed atomic manifest save to %s: %s", self.manifest_path, e)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def write_segment(
        self,
        audio_data: Union[np.ndarray, bytes],
        start_wall_clock: Optional[float] = None,
        duration_sec: Optional[float] = None,
        sample_rate: int = 16000,
        status: str = "pending",
    ) -> Dict[str, Any]:
        """
        Writes a 30-second audio buffer to disk as seg_XXXX.wav and appends to manifest.
        Accepts stereo/mono float32 numpy array or raw WAV bytes.
        """
        with self._lock:
            self.segment_counter += 1
            seg_id = f"seg_{self.segment_counter:04d}"
            filename = f"{seg_id}.wav"
            file_path = os.path.join(self.session_dir, filename)

            # 1. Process audio payload
            if isinstance(audio_data, np.ndarray):
                if duration_sec is None:
                    duration_sec = float(len(audio_data) / sample_rate)
                wav_bytes = self._audio_array_to_wav_bytes(audio_data, sample_rate=sample_rate)
            elif isinstance(audio_data, bytes):
                wav_bytes = audio_data
                if duration_sec is None:
                    duration_sec = self._estimate_wav_duration(wav_bytes, sample_rate)
            else:
                raise TypeError(f"audio_data must be np.ndarray or bytes, got {type(audio_data)}")

            if start_wall_clock is None:
                start_wall_clock = time.time()

            # 2. Write WAV file atomically with disk-full protection
            tmp_filename = f"{filename}.tmp.{os.getpid()}_{time.time_ns()}"
            tmp_filepath = os.path.join(self.session_dir, tmp_filename)
            try:
                with open(tmp_filepath, "wb") as f:
                    f.write(wav_bytes)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_filepath, file_path)
            except OSError as oe:
                logger.critical("Disk write failed for segment %s (Disk full or I/O failure): %s", seg_id, oe)
                self.manifest["status"] = "error"
                self.manifest["error"] = f"Disk I/O error: {oe}"
                if os.path.exists(tmp_filepath):
                    try:
                        os.remove(tmp_filepath)
                    except OSError:
                        pass
                raise

            # 3. Create and append segment record
            segment_record = {
                "id": seg_id,
                "file": filename,
                "start_wall_clock": float(start_wall_clock),
                "duration_sec": float(duration_sec),
                "status": status,  # "pending", "uploaded", "done"
            }
            self.manifest["segments"].append(segment_record)

            # 4. Atomically persist manifest
            self._save_manifest_atomic_locked()

            logger.info("Wrote journal segment %s (%s, %.1fs) to %s", seg_id, filename, duration_sec, self.session_dir)
            return dict(segment_record)

    def save_emergency_dump(self, payload: Dict[str, Any], error_msg: str) -> str:
        """
        Atomically saves session buffer and state to emergency_dump.json inside this session directory.
        """
        with self._lock:
            dump_path = os.path.join(self.session_dir, "emergency_dump.json")
            tmp_path = os.path.join(self.session_dir, f"emergency_dump.tmp.{os.getpid()}_{time.time_ns()}")
            data = {
                "session_id": self.session_id,
                "timestamp": time.time(),
                "error": error_msg,
                "manifest_snapshot": self.manifest,
                "payload": payload,
            }
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, default=str)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path, dump_path)
                logger.critical("Session emergency dump atomically saved to %s", dump_path)
                return dump_path
            except Exception as e:
                logger.error("Failed to write session emergency dump to %s: %s", dump_path, e)
                if os.path.exists(tmp_path):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                return ""

    def update_segment_status(self, segment_id: str, status: str) -> bool:
        """Updates the status of a specific segment in the manifest."""
        with self._lock:
            updated = False
            for seg in self.manifest.get("segments", []):
                if seg.get("id") == segment_id:
                    seg["status"] = status
                    updated = True
                    break
            if updated:
                self._save_manifest_atomic_locked()
            return updated

    def mark_completed(self):
        """Marks the entire session as completed."""
        with self._lock:
            self.manifest["status"] = "completed"
            self._save_manifest_atomic_locked()
            logger.info("Session %s marked as completed.", self.session_id)

    def complete_session(self):
        """Alias for mark_completed()."""
        self.mark_completed()

    def mark_status(self, status: str):
        """Sets the session status (e.g. 'recording', 'recovering', 'completed')."""
        with self._lock:
            self.manifest["status"] = status
            self._save_manifest_atomic_locked()

    def get_pending_segments(self) -> List[Dict[str, Any]]:
        """Returns all segments with status == 'pending'."""
        with self._lock:
            return [dict(s) for s in self.manifest.get("segments", []) if s.get("status") == "pending"]

    def get_all_segments(self) -> List[Dict[str, Any]]:
        """Returns a copy of all segments."""
        with self._lock:
            return [dict(s) for s in self.manifest.get("segments", [])]

    def get_segment(self, segment_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a segment metadata dictionary by ID."""
        with self._lock:
            for s in self.manifest.get("segments", []):
                if s.get("id") == segment_id:
                    return dict(s)
            return None

    def get_segment_filepath(self, segment_or_id: Union[str, Dict[str, Any]]) -> str:
        """Returns the absolute file path for a segment."""
        if isinstance(segment_or_id, dict):
            filename = segment_or_id.get("file", f"{segment_or_id.get('id', '')}.wav")
        else:
            filename = f"{segment_or_id}.wav" if not segment_or_id.endswith(".wav") else segment_or_id
        return os.path.join(self.session_dir, filename)

    def read_segment_audio(
        self, segment_or_id: Union[str, Dict[str, Any]], strict: bool = False
    ) -> Tuple[np.ndarray, int]:
        """
        Reads a segment WAV file from disk into a float32 numpy array.
        Returns (audio_array, sample_rate).
        Shape is (N, 2) for stereo or (N, 1) for mono.
        """
        file_path = self.get_segment_filepath(segment_or_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Segment audio file not found: {file_path}")

        try:
            with wave.open(file_path, "rb") as wf:
                n_channels = wf.getnchannels()
                sample_rate = wf.getframerate()
                sampwidth = wf.getsampwidth()
                n_frames = wf.getnframes()
                frames = wf.readframes(n_frames)
        except (wave.Error, Exception) as we:
            logger.error("Corrupted WAV header in %s: %s.", file_path, we)
            if strict:
                raise ValueError(f"Corrupted WAV audio file in {file_path}: {we}")
            return np.zeros((16000 * 30, 2), dtype=np.float32), 16000

        if sampwidth == 2:
            data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sampwidth == 4:
            data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            data = np.frombuffer(frames, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0

        if n_channels > 1:
            data = data.reshape(-1, n_channels)
        else:
            data = data.reshape(-1, 1)

        # Standardize mono to stereo if expected
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)

        return data, sample_rate

    def read_segments_audio(self, segment_ids: List[str]) -> Tuple[np.ndarray, int]:
        """
        Reads multiple segments from disk and concatenates them in order into a single stereo array.
        """
        arrays = []
        sr = 16000
        for sid in segment_ids:
            try:
                arr, seg_sr = self.read_segment_audio(sid)
                sr = seg_sr
                if len(arr) > 0:
                    arrays.append(arr)
            except Exception as e:
                logger.error("Failed to read segment %s: %s", sid, e)

        if not arrays:
            return np.zeros((0, 2), dtype=np.float32), sr

        concatenated = np.concatenate(arrays, axis=0)
        return concatenated, sr

    def get_audio_slice(
        self, target_timestamp_sec: float, slice_duration: float = 20.0
    ) -> Tuple[np.ndarray, int]:
        """
        Extracts a slice_duration audio snippet (default: 20s) centered on target_timestamp_sec
        from the session's recorded segments.
        Uses segment start_wall_clock to maintain accurate alignment even across pauses or breaks.
        Returns (audio_array, sample_rate).
        """
        sr = 16000
        if slice_duration <= 0.0:
            slice_duration = 20.0

        target_start = max(0.0, target_timestamp_sec - (slice_duration / 2.0))
        target_end = target_start + slice_duration

        with self._lock:
            segments = list(self.manifest.get("segments", []))

        if not segments:
            return np.zeros((0, 2), dtype=np.float32), sr

        # Determine reference start time from earliest start_wall_clock
        first_seg_start = None
        for s in segments:
            if s.get("start_wall_clock") is not None:
                first_seg_start = float(s["start_wall_clock"])
                break

        sliced_pieces = []
        cur_t = 0.0

        for seg in segments:
            seg_dur = float(seg.get("duration_sec", 30.0))
            seg_wall = seg.get("start_wall_clock")

            if seg_wall is not None and first_seg_start is not None:
                if target_timestamp_sec > 1e8:
                    seg_start = float(seg_wall)
                else:
                    seg_start = float(seg_wall) - first_seg_start
            else:
                seg_start = cur_t

            seg_end = seg_start + seg_dur
            cur_t = seg_end

            # Check if segment overlaps [target_start, target_end]
            if max(target_start, seg_start) < min(target_end, seg_end):
                try:
                    seg_audio, seg_sr = self.read_segment_audio(seg["id"])
                    sr = seg_sr
                    if len(seg_audio) > 0:
                        overlap_start = max(target_start, seg_start) - seg_start
                        overlap_end = min(target_end, seg_end) - seg_start
                        idx_start = max(0, int(overlap_start * sr))
                        idx_end = min(len(seg_audio), int(overlap_end * sr))
                        if idx_end > idx_start:
                            sliced_pieces.append(seg_audio[idx_start:idx_end])
                except Exception as e:
                    logger.warning("Error reading segment %s for audio slice: %s", seg.get("id"), e)

        if not sliced_pieces:
            return np.zeros((0, 2), dtype=np.float32), sr

        return np.concatenate(sliced_pieces, axis=0), sr

    def read_manifest(self) -> Dict[str, Any]:
        """Returns the current manifest in memory."""
        with self._lock:
            return json.loads(json.dumps(self.manifest))

    @staticmethod
    def _audio_array_to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
        """Converts float32 numpy array to 16-bit PCM WAV bytes."""
        if len(audio) == 0:
            return b""
        if audio.ndim == 1:
            # Duplicate mono to stereo
            audio = np.stack([audio, audio], axis=-1)
        elif audio.ndim == 2 and audio.shape[1] == 1:
            audio = np.repeat(audio, 2, axis=1)

        n_channels = audio.shape[1]
        int16_audio = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)

        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(n_channels)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(int16_audio.tobytes())

        return bio.getvalue()

    @staticmethod
    def _estimate_wav_duration(wav_bytes: bytes, sample_rate: int = 16000) -> float:
        """Estimates duration from WAV header or byte length."""
        try:
            bio = io.BytesIO(wav_bytes)
            with wave.open(bio, "rb") as wf:
                return float(wf.getnframes() / max(1, wf.getframerate()))
        except Exception:
            # Fallback estimation assuming 16kHz stereo 16-bit PCM (64,000 bytes/sec)
            bytes_per_sec = sample_rate * 2 * 2
            return max(0.0, float(len(wav_bytes) - 44) / bytes_per_sec)

    @classmethod
    def load(cls, session_id_or_path: str, base_dir: Optional[str] = None) -> "SessionJournal":
        """Loads an existing session journal from a session ID or path."""
        if os.path.isdir(session_id_or_path):
            sess_dir = os.path.abspath(session_id_or_path)
            sess_id = os.path.basename(sess_dir)
            parent_dir = os.path.dirname(sess_dir)
            return cls(session_id=sess_id, base_dir=parent_dir, create_if_missing=False)
        else:
            return cls(session_id=session_id_or_path, base_dir=base_dir, create_if_missing=False)


def recover_unprocessed_sessions(base_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Scans ~/.chalk/sessions/ on boot for sessions with status 'recording'
    or pending segments after a crash or lid close.
    Returns list of pending session metadata to resume the queue.
    """
    sessions_path = os.path.abspath(os.path.expanduser(base_dir or DEFAULT_SESSIONS_DIR))
    if not os.path.isdir(sessions_path):
        logger.debug("Sessions directory %s does not exist. No recovery needed.", sessions_path)
        return []

    recovered_sessions: List[Dict[str, Any]] = []

    try:
        entries = sorted(os.listdir(sessions_path))
    except OSError as e:
        logger.error("Could not list sessions directory %s: %s", sessions_path, e)
        return []

    for entry in entries:
        sess_dir = os.path.join(sessions_path, entry)
        if not os.path.isdir(sess_dir):
            continue

        manifest_file = os.path.join(sess_dir, "manifest.json")
        if not os.path.isfile(manifest_file):
            continue

        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
        except Exception as e:
            logger.warning("Corrupt or unreadable manifest at %s: %s", manifest_file, e)
            continue

        status = manifest_data.get("status", "")
        segments = manifest_data.get("segments", [])
        pending_segments = [s for s in segments if s.get("status") == "pending"]

        # A session needs recovery if it was interrupted while recording or has pending segments
        needs_recovery = (status in ("recording", "recovering")) or (len(pending_segments) > 0)

        if needs_recovery:
            # Transition status from recording to recovering if crashed
            if status == "recording":
                manifest_data["status"] = "recovering"
                try:
                    tmp_file = f"{manifest_file}.tmp.{os.getpid()}_{time.time_ns()}"
                    with open(tmp_file, "w", encoding="utf-8") as f:
                        json.dump(manifest_data, f, indent=2)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_file, manifest_file)
                except Exception as e:
                    logger.warning("Could not update recovery status in %s: %s", manifest_file, e)

            session_info = {
                "session_id": manifest_data.get("session_id", entry),
                "session_dir": sess_dir,
                "status": manifest_data.get("status", "recovering"),
                "created_at": manifest_data.get("created_at", 0.0),
                "manifest": manifest_data,
                "pending_segments": pending_segments,
                "total_segments": len(segments),
            }
            recovered_sessions.append(session_info)
            logger.info(
                "Found unrecovered session %s with %d pending segments (%s)",
                session_info["session_id"],
                len(pending_segments),
                session_info["status"],
            )

    recovered_sessions.sort(key=lambda s: s.get("created_at", 0.0))
    return recovered_sessions


def cleanup_old_sessions(
    base_dir: Optional[str] = None,
    max_age_days: int = 7,
    keep_min_sessions: int = 3,
) -> int:
    """
    Cleans up old completed sessions from ~/.chalk/sessions/ older than max_age_days
    to prevent unbounded disk growth (~230MB/hr) while strictly preserving at least keep_min_sessions.
    Returns the number of session directories removed.
    """
    sessions_path = os.path.abspath(os.path.expanduser(base_dir or DEFAULT_SESSIONS_DIR))
    if not os.path.isdir(sessions_path):
        return 0

    now = time.time()
    cutoff_time = now - (max_age_days * 86400)
    purged_count = 0

    try:
        entries = sorted(os.listdir(sessions_path))
    except OSError:
        return 0

    session_dirs = []
    for entry in entries:
        sess_dir = os.path.join(sessions_path, entry)
        if os.path.isdir(sess_dir):
            manifest_file = os.path.join(sess_dir, "manifest.json")
            created_at = os.path.getmtime(sess_dir)
            status = "unknown"
            if os.path.isfile(manifest_file):
                try:
                    with open(manifest_file, "r", encoding="utf-8") as f:
                        m_data = json.load(f)
                        created_at = float(m_data.get("created_at", created_at))
                        status = m_data.get("status", "unknown")
                except Exception:
                    pass
            session_dirs.append((created_at, status, sess_dir))

    session_dirs.sort(key=lambda x: x[0])  # Oldest first

    # Ensure we never delete below keep_min_sessions
    eligible_to_check = session_dirs[:-keep_min_sessions] if len(session_dirs) > keep_min_sessions else []

    for c_time, status, s_dir in eligible_to_check:
        if c_time < cutoff_time and status == "completed":
            try:
                shutil.rmtree(s_dir)
                purged_count += 1
                logger.info("Purged old completed session directory: %s", s_dir)
            except Exception as e:
                logger.warning("Could not delete old session %s: %s", s_dir, e)

    return purged_count

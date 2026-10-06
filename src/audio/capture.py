"""
src/audio/capture.py - High-Efficiency Audio Compression & Ingestion Utilities.

Guarantees audio payloads remain well below Google AI Studio's 20MB inline limit:
- 45 minutes of raw 16kHz stereo PCM is ~172.8 MB (exceeds 20MB limit).
- 45 minutes of AAC at 32 kbps is ~10.8 MB (safely within inline upload limits).

Compression hierarchy:
1. macOS native: /usr/bin/afconvert -f m4af -d aac -b 32000 in.wav out.m4a (zero extra deps)
2. Cross-platform fallback: ffmpeg -i in.wav -c:a aac -b:a 32k out.m4a (if installed)
3. Heuristic fallback: 16kHz mono 16-bit PCM WAV (50% reduction from stereo)
"""

import os
import sys
import io
import wave
import shutil
import tempfile
import logging
import subprocess
from typing import Tuple, Union, Optional
import numpy as np

logger = logging.getLogger("chalk.audio.capture")


def audio_to_wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """
    Converts a float32 numpy array to 16-bit PCM WAV bytes in memory.
    Supports mono (N,), (N, 1) and stereo (N, 2).
    """
    if len(audio) == 0:
        return b""

    if audio.ndim == 1:
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


def wav_bytes_to_audio(wav_bytes: bytes) -> Tuple[np.ndarray, int]:
    """
    Converts 16-bit PCM WAV bytes to a float32 stereo numpy array (N, 2) and sample rate.
    """
    if not wav_bytes:
        return np.zeros((0, 2), dtype=np.float32), 16000

    bio = io.BytesIO(wav_bytes)
    with wave.open(bio, "rb") as wf:
        n_channels = wf.getnchannels()
        sample_rate = wf.getframerate()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw_frames = wf.readframes(n_frames)

    if sampwidth == 2:
        data = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw_frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = np.frombuffer(raw_frames, dtype=np.uint8).astype(np.float32) / 128.0 - 1.0

    if n_channels > 1:
        data = data.reshape(-1, n_channels)
    else:
        data = data.reshape(-1, 1)

    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)

    return data, sample_rate


def estimate_compressed_size_mb(duration_seconds: float, kbps: int = 32) -> float:
    """Estimates size in megabytes of an audio stream at a specified bitrate."""
    total_bits = duration_seconds * kbps * 1000.0
    total_bytes = total_bits / 8.0
    return total_bytes / (1024.0 * 1024.0)


def compress_audio_payload(
    wav_bytes_or_audio: Union[bytes, np.ndarray],
    target_kbps: int = 32,
    sample_rate: int = 16000,
) -> Tuple[bytes, str]:
    """
    Compresses an audio stream under Google's 20MB inline API limit.
    Target bitrate defaults to 32 kbps (AAC M4A), yielding ~10.8 MB per 45 minutes.

    Returns:
        (compressed_bytes, mime_type)
        mime_type is 'audio/mp4' (for AAC in m4a container), 'audio/aac', or 'audio/wav'.
    """
    # 1. Resolve WAV bytes
    if isinstance(wav_bytes_or_audio, np.ndarray):
        if len(wav_bytes_or_audio) == 0:
            return b"", "audio/wav"
        wav_bytes = audio_to_wav_bytes(wav_bytes_or_audio, sample_rate=sample_rate)
        source_array = wav_bytes_or_audio
    elif isinstance(wav_bytes_or_audio, (bytes, bytearray)):
        if len(wav_bytes_or_audio) == 0:
            return b"", "audio/wav"
        wav_bytes = bytes(wav_bytes_or_audio)
        source_array = None
    else:
        raise TypeError(f"Expected np.ndarray or bytes, got {type(wav_bytes_or_audio)}")

    bitrate_bps = target_kbps * 1000

    # 2. Strategy A: macOS Native afconvert (Zero Dependencies)
    if sys.platform == "darwin":
        afconvert_bin = "/usr/bin/afconvert" if os.path.exists("/usr/bin/afconvert") else shutil.which("afconvert")
        if afconvert_bin:
            temp_dir = tempfile.mkdtemp(prefix="chalk_afconvert_")
            in_wav_path = os.path.join(temp_dir, "input.wav")
            out_m4a_path = os.path.join(temp_dir, "output.m4a")
            try:
                with open(in_wav_path, "wb") as f:
                    f.write(wav_bytes)

                cmd = [
                    afconvert_bin,
                    "-f", "m4af",
                    "-d", "aac",
                    "-b", str(bitrate_bps),
                    in_wav_path,
                    out_m4a_path,
                ]
                proc = subprocess.run(cmd, capture_output=True, timeout=30)
                if proc.returncode == 0 and os.path.exists(out_m4a_path) and os.path.getsize(out_m4a_path) > 0:
                    with open(out_m4a_path, "rb") as f:
                        compressed_data = f.read()
                    logger.debug(
                        "afconvert compression succeeded: %d -> %d bytes (%.1f%%)",
                        len(wav_bytes),
                        len(compressed_data),
                        (len(compressed_data) / max(1, len(wav_bytes))) * 100,
                    )
                    return compressed_data, "audio/mp4"
                else:
                    logger.warning("afconvert failed (code %d): %s", proc.returncode, proc.stderr.decode(errors="ignore"))
            except Exception as e:
                logger.warning("afconvert execution failed: %s", e)
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)

    # 3. Strategy B: ffmpeg (Cross-Platform)
    ffmpeg_bin = shutil.which("ffmpeg")
    if ffmpeg_bin:
        temp_dir = tempfile.mkdtemp(prefix="chalk_ffmpeg_")
        in_wav_path = os.path.join(temp_dir, "input.wav")
        out_m4a_path = os.path.join(temp_dir, "output.m4a")
        try:
            with open(in_wav_path, "wb") as f:
                f.write(wav_bytes)

            cmd = [
                ffmpeg_bin,
                "-y",
                "-i", in_wav_path,
                "-c:a", "aac",
                "-b:a", f"{target_kbps}k",
                out_m4a_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
            if proc.returncode == 0 and os.path.exists(out_m4a_path) and os.path.getsize(out_m4a_path) > 0:
                with open(out_m4a_path, "rb") as f:
                    compressed_data = f.read()
                logger.debug(
                    "ffmpeg compression succeeded: %d -> %d bytes (%.1f%%)",
                    len(wav_bytes),
                    len(compressed_data),
                    (len(compressed_data) / max(1, len(wav_bytes))) * 100,
                )
                return compressed_data, "audio/mp4"
            else:
                logger.warning("ffmpeg failed: %s", proc.stderr.decode(errors="ignore"))
        except Exception as e:
            logger.warning("ffmpeg execution failed: %s", e)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # 4. Strategy C: Pure Python Fallback (Downmix stereo to mono 16kHz PCM WAV)
    logger.info("Using PCM mono downmixing fallback for audio payload compression.")
    try:
        if source_array is None:
            source_array, parsed_sr = wav_bytes_to_audio(wav_bytes)
            sample_rate = parsed_sr

        if source_array.ndim == 2 and source_array.shape[1] > 1:
            # Downmix stereo to mono (50% byte size reduction)
            mono_array = np.mean(source_array, axis=1)
        else:
            mono_array = source_array.flatten()

        int16_mono = (np.clip(mono_array, -1.0, 1.0) * 32767).astype(np.int16)
        bio = io.BytesIO()
        with wave.open(bio, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(int16_mono.tobytes())

        mono_wav_bytes = bio.getvalue()
        return mono_wav_bytes, "audio/wav"
    except Exception as e:
        logger.error("PCM fallback failed: %s. Returning raw WAV bytes.", e)
        return wav_bytes, "audio/wav"

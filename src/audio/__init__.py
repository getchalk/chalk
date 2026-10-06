"""
src/audio - Audio Capture, Diarization, Silence Stripping & Compression.
"""

from src.audio.recorder import DualChannelAudioRecorder
from src.audio.vad_detector import SileroVADDetector, AudioOffsetMap, SegmentMapping
from src.audio.capture import compress_audio_payload, audio_to_wav_bytes, wav_bytes_to_audio

__all__ = [
    "DualChannelAudioRecorder",
    "SileroVADDetector",
    "AudioOffsetMap",
    "SegmentMapping",
    "compress_audio_payload",
    "audio_to_wav_bytes",
    "wav_bytes_to_audio",
]

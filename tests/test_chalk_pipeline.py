"""
tests/test_chalk_pipeline.py - Comprehensive Unit & Integration Test Suite for Chalk.
Tests all core engine, audio, vision, security, and tool calling components.
"""

import os
import sys
import time
import unittest
import numpy as np
from PIL import Image

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.security import key_manager
from src.engine.quota_manager import QuotaManager
from src.engine.elastic_chunker import ElasticChunker
from src.engine.session_state import ChunkState, SessionNotesManager
from src.audio.vad_detector import SileroVADDetector
from src.audio.recorder import DualChannelAudioRecorder
from src.vision.slide_filter import PerceptualSlideFilter
from src.vision.accessibility import AccessibilityTextExtractor
from src.api import tools


class TestChalkSecurity(unittest.TestCase):
    def test_key_manager_interface(self):
        # Ensure functions exist and don't raise unexpected errors
        self.assertFalse(key_manager.validate_api_key("")[0])
        self.assertFalse(key_manager.validate_api_key("short")[0])


class TestChalkEngine(unittest.TestCase):
    def setUp(self):
        self.qm = QuotaManager()
        self.chunker = ElasticChunker(quota_manager=self.qm)

    def test_adaptive_profile_clamping(self):
        # Real-time mode (RPD > 15)
        mode, min_w, max_w, thresh = self.qm.get_adaptive_profile(120.0)
        self.assertEqual(mode, "realtime")
        self.assertGreaterEqual(min_w, 11.0)
        self.assertLessEqual(max_w, 16.0)
        self.assertEqual(thresh, 8)

    def test_elastic_chunker_triggers(self):
        # Should not flush initially
        should, reason = self.chunker.check_boundary_conditions(100.0, False)
        self.assertFalse(should)

        # Inside target window (e.g. 11.5 min = 690s, where min_w=11 min, max_w=13 min) + conversational pause (>3.5s)
        should_pause, reason_pause = self.chunker.check_boundary_conditions(690.0, True)
        self.assertTrue(should_pause)
        self.assertIn("Conversational Pause", reason_pause)

        # Ceiling cutoff (e.g. 14 min = 840s >= 13 min max)
        should_ceil, reason_ceil = self.chunker.check_boundary_conditions(840.0, False)
        self.assertTrue(should_ceil)
        self.assertIn("Hard Ceiling", reason_ceil)

    def test_chunk_state_parsing(self):
        raw_output = """
# Lecture Notes Segment
Here is the derivation of the capital asset pricing model.
$$E(R_i) = R_f + \\beta_i (E(R_m) - R_f)$$

<!-- CHUNK_STATE
Topic: CAPM & Beta Derivation
Active_Variables: [R_i, R_f, beta_i, R_m]
Unresolved_Proofs: [Arbitrage Pricing Theory convergence]
Primary_Speaker: Fast Cadence, European Accent
-->
"""
        state = ChunkState.from_model_output(raw_output, chunk_index=1)
        self.assertEqual(state.topic, "CAPM & Beta Derivation")
        self.assertEqual(state.active_variables, ["R_i", "R_f", "beta_i", "R_m"])
        self.assertEqual(state.unresolved_proofs, ["Arbitrage Pricing Theory convergence"])
        self.assertIn("European Accent", state.primary_speaker)

        # Test markdown serialization
        block = state.to_markdown_block()
        self.assertIn("<!-- CHUNK_STATE", block)
        self.assertIn("CAPM & Beta Derivation", block)


class TestChalkAudio(unittest.TestCase):
    def test_audio_to_wav_conversion(self):
        # 1 second of stereo audio (16000 samples x 2 channels)
        stereo = np.zeros((16000, 2), dtype=np.float32)
        wav_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(stereo, sample_rate=16000)
        self.assertGreater(len(wav_bytes), 44)  # WAV header is 44 bytes

    def test_silence_stripping(self):
        vad = SileroVADDetector()
        # 3 seconds of zeros (silence)
        silence = np.zeros((48000, 2), dtype=np.float32)
        stripped = vad.strip_silent_gaps(silence, sample_rate=16000, max_silence_sec=1.5)
        # Stripped should be significantly smaller than original 3 seconds
        self.assertLess(len(stripped), len(silence))


class TestChalkVision(unittest.TestCase):
    def test_slide_filter_deduplication(self):
        sf = PerceptualSlideFilter(default_threshold=8)
        img1 = Image.new("RGB", (200, 200), (255, 255, 255))
        kf1 = sf.evaluate_frame(img1, 0.0)
        self.assertIsNotNone(kf1)
        self.assertEqual(kf1.timestamp_str, "[00:00]")

        # Duplicate identical frame should be filtered (None)
        kf2 = sf.evaluate_frame(img1, 5.0)
        self.assertIsNone(kf2)

        # High-contrast new frame (black with diagonal line) should trigger keyframe
        img2 = Image.new("RGB", (200, 200), (0, 0, 0))
        for i in range(200):
            img2.putpixel((i, i), (255, 255, 255))
            img2.putpixel((i, 199 - i), (255, 255, 255))

        kf3 = sf.evaluate_frame(img2, 10.0)
        self.assertIsNotNone(kf3)
        self.assertGreater(kf3.hamming_distance_from_prev, 8)


class TestChalkTools(unittest.TestCase):
    def test_read_local_file_text(self):
        # Test reading requirements.txt
        res = tools.read_local_file("requirements.txt")
        self.assertIn("google-genai", res)

    def test_read_nonexistent_file(self):
        res = tools.read_local_file("nonexistent_test_file_xyz.txt")
        self.assertIn("Error: File not found", res)


if __name__ == "__main__":
    unittest.main()

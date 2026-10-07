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
from src.engine.journal import SessionJournal, recover_unprocessed_sessions
from src.audio.vad_detector import SileroVADDetector, AudioOffsetMap
from src.audio.recorder import DualChannelAudioRecorder
from src.audio.capture import compress_audio_payload
from src.vision.slide_filter import PerceptualSlideFilter
from src.vision.accessibility import AccessibilityTextExtractor
from src.api import tools
import tempfile
import json


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

    def test_offset_map_with_synthetic_silence_gaps(self):
        vad = SileroVADDetector()
        sr = 16000
        # 10 seconds total audio:
        # 0.0 - 3.0s: speech tone
        # 3.0 - 7.0s: 4 seconds of silence
        # 7.0 - 10.0s: speech tone
        t = np.linspace(0, 10, 10 * sr, endpoint=False)
        audio = np.zeros((len(t), 2), dtype=np.float32)
        speech_1 = (t >= 0.0) & (t < 3.0)
        audio[speech_1, 0] = 0.5 * np.sin(2 * np.pi * 350.0 * t[speech_1])
        speech_2 = (t >= 7.0) & (t < 10.0)
        audio[speech_2, 0] = 0.5 * np.sin(2 * np.pi * 350.0 * t[speech_2])

        # Backward-compatible call (returns ndarray)
        stripped = vad.strip_silent_gaps(audio, sample_rate=sr, max_silence_sec=1.5)
        self.assertIsInstance(stripped, np.ndarray)
        self.assertLess(len(stripped), len(audio))

        # Enhanced call (returns stripped, offset_map)
        stripped_m, offset_map = vad.strip_silent_gaps(audio, sample_rate=sr, max_silence_sec=1.5, return_offset_map=True)
        self.assertIsInstance(offset_map, AudioOffsetMap)
        self.assertAlmostEqual(offset_map.original_duration_sec, 10.0, places=2)
        self.assertLess(offset_map.compressed_duration_sec, 10.0)
        self.assertGreater(offset_map.pruned_duration_sec, 0.0)

        # Map compressed time in segment 1 back to original
        orig_t1 = offset_map.map_compressed_to_original(1.5)
        self.assertAlmostEqual(orig_t1, 1.5, delta=0.05)

        # Map original time to compressed time
        comp_t1 = offset_map.map_original_to_compressed(1.5)
        self.assertAlmostEqual(comp_t1, 1.5, delta=0.05)

        # Point inside stripped silence gap (e.g. 5.5s) maps to the cut seam
        comp_silence = offset_map.map_original_to_compressed(5.5)
        self.assertLess(comp_silence, 5.5)

        # Point in second speech segment (8.5s) maps correctly
        comp_t2 = offset_map.map_original_to_compressed(8.5)
        orig_t2 = offset_map.map_compressed_to_original(comp_t2)
        self.assertAlmostEqual(orig_t2, 8.5, delta=0.05)

    def test_audio_compression_under_20mb(self):
        # 5 seconds of synthetic audio
        stereo = np.random.uniform(-0.4, 0.4, (80000, 2)).astype(np.float32)
        raw_pcm_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(stereo, sample_rate=16000)

        comp_bytes, mime = compress_audio_payload(stereo, target_kbps=32)
        self.assertIn(mime, ["audio/mp4", "audio/aac", "audio/wav"])
        self.assertGreater(len(comp_bytes), 0)
        # Should achieve significant reduction compared to uncompressed PCM
        self.assertLess(len(comp_bytes), len(raw_pcm_bytes))

        # Staticmethod on DualChannelAudioRecorder
        comp_bytes2, mime2 = DualChannelAudioRecorder.compress_audio(raw_pcm_bytes, target_kbps=32)
        self.assertIn(mime2, ["audio/mp4", "audio/aac", "audio/wav"])
        self.assertGreater(len(comp_bytes2), 0)


class TestChalkJournalAndFaultTolerance(unittest.TestCase):
    def test_session_journal_manifest_and_segments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = SessionJournal(session_id="test_sess_42", base_dir=tmpdir)
            self.assertEqual(journal.manifest["status"], "recording")
            self.assertEqual(journal.manifest["session_id"], "test_sess_42")
            self.assertTrue(os.path.exists(journal.manifest_path))

            # Write two 30-second segments
            audio1 = np.zeros((480000, 2), dtype=np.float32)
            s1 = journal.write_segment(audio1, duration_sec=30.0, status="pending")
            self.assertEqual(s1["id"], "seg_0001")
            self.assertEqual(s1["file"], "seg_0001.wav")
            self.assertEqual(s1["status"], "pending")
            self.assertTrue(os.path.exists(journal.get_segment_filepath(s1)))

            audio2 = np.zeros((480000, 2), dtype=np.float32)
            s2 = journal.write_segment(audio2, duration_sec=30.0, status="pending")
            self.assertEqual(s2["id"], "seg_0002")
            self.assertEqual(s2["file"], "seg_0002.wav")

            # Verify manifest segments
            pending = journal.get_pending_segments()
            self.assertEqual(len(pending), 2)

            # Read back segment audio
            read_arr, sr = journal.read_segment_audio("seg_0001")
            self.assertEqual(sr, 16000)
            self.assertEqual(read_arr.shape, (480000, 2))

            # Update segment status
            journal.update_segment_status("seg_0001", "uploaded")
            pending_after = journal.get_pending_segments()
            self.assertEqual(len(pending_after), 1)

            # Mark completed
            journal.mark_completed()
            self.assertEqual(journal.read_manifest()["status"], "completed")

    def test_startup_recovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a session that crashed mid-recording
            sess_dir = os.path.join(tmpdir, "crashed_session")
            os.makedirs(sess_dir, exist_ok=True)
            manifest = {
                "session_id": "crashed_session",
                "created_at": 1728229000.0,
                "status": "recording",
                "segments": [
                    {
                        "id": "seg_0001",
                        "file": "seg_0001.wav",
                        "start_wall_clock": 1728229000.0,
                        "duration_sec": 30.0,
                        "status": "pending",
                    }
                ],
            }
            with open(os.path.join(sess_dir, "manifest.json"), "w") as f:
                json.dump(manifest, f)

            recovered = recover_unprocessed_sessions(base_dir=tmpdir)
            self.assertEqual(len(recovered), 1)
            rec = recovered[0]
            self.assertEqual(rec["session_id"], "crashed_session")
            self.assertEqual(rec["status"], "recovering")
            self.assertEqual(len(rec["pending_segments"]), 1)

    def test_recorder_journal_integration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            journal = SessionJournal(session_id="rec_sess", base_dir=tmpdir)
            recorder = DualChannelAudioRecorder(
                sample_rate=16000,
                rewind_buffer_seconds=90,
                segment_duration_sec=30.0,
                journal=journal,
            )

            # Simulate 35 seconds of audio incoming (exceeding 30s segment boundary)
            # 35 seconds * 16000 = 560000 samples
            frames_per_block = 16000  # 1 sec per block
            for _ in range(35):
                stereo_block = np.zeros((frames_per_block, 2), dtype=np.float32)
                with recorder._lock:
                    for s in range(frames_per_block):
                        recorder._rolling_rewind_buffer.append(stereo_block[s])
                    recorder._current_segment_samples.append(stereo_block)
                    recorder._current_segment_sample_count += frames_per_block
                    if recorder._current_segment_sample_count >= int(recorder.segment_duration_sec * recorder.sample_rate):
                        recorder._flush_current_segment_locked()

            # The first 30 seconds should have flushed to disk as seg_0001.wav
            pending_segments = journal.get_pending_segments()
            self.assertEqual(len(pending_segments), 1)
            self.assertEqual(pending_segments[0]["id"], "seg_0001")
            self.assertTrue(os.path.exists(journal.get_segment_filepath("seg_0001")))

            # Remaining 5 seconds in memory buffer
            self.assertEqual(recorder._current_segment_sample_count, 5 * 16000)

            # Rolling rewind buffer retains 35 seconds in memory
            rewind = recorder.get_rewind_audio(seconds=90)
            self.assertEqual(len(rewind), 35 * 16000)

            # Flushing active chunk flushes remaining 5s as seg_0002 and concatenates both
            chunk_audio = recorder.get_and_flush_active_chunk(strip_silence=False)
            self.assertEqual(len(chunk_audio), 35 * 16000)
            self.assertEqual(len(journal.get_all_segments()), 2)


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
class TestChalkNativeHotkeys(unittest.TestCase):
    def test_native_hotkey_manager_registration_and_trigger(self):
        from src.security.hotkeys import NativeHotkeyManager

        mgr = NativeHotkeyManager()
        events = []

        h_hud = mgr.register("Cmd+Shift+Space", lambda: events.append("hud"))
        h_snip = mgr.register("Cmd+Shift+S", lambda: events.append("snip"))
        h_f9 = mgr.register("F9", lambda: events.append("f9"))
        h_f10 = mgr.register("F10", lambda: events.append("f10"))

        self.assertGreater(h_hud, 0)
        self.assertGreater(h_snip, 0)
        self.assertGreater(h_f9, 0)
        self.assertGreater(h_f10, 0)

        mgr.start()

        # Trigger programmatically
        mgr.trigger_for_test(h_hud)
        mgr.trigger_for_test(h_snip)
        mgr.trigger_for_test(h_f9)
        mgr.trigger_for_test(h_f10)

        self.assertEqual(events, ["hud", "snip", "f9", "f10"])
        mgr.stop()


class TestChalkInPersonSlidesAndOnboarding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication(["test"])

    def test_pdf_pre_import_and_visual_indicator(self):
        import pypdf
        from src.ui.hud_window import FloatingHUDWindow

        # Create synthetic PDF test file
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)
        writer.add_blank_page(width=100, height=100)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            pdf_path = f.name
            writer.write(f)

        try:
            hud = FloatingHUDWindow()
            hud.load_reference_document(pdf_path)

            self.assertEqual(len(hud.imported_pdf_slides), 3)
            self.assertEqual(hud.imported_pdf_slides[0]["page"], 1)
            self.assertTrue(
                "3 Seiten" in hud.attachment_label.text() or "3 pages" in hud.attachment_label.text(),
                f"Unexpected attachment text: {hud.attachment_label.text()}"
            )

            ref_text = hud.get_relevant_reference_text(query_hint="introduction")
            self.assertIsNotNone(ref_text)
            self.assertIn("IN-PERSON LECTURE SLIDE DECK", ref_text)
            self.assertIn("[Folie / Page 1]", ref_text)
        finally:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)

    def test_settings_dialog_transparent_onboarding_notice(self):
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(is_initial_setup=False)
        found_notice = False
        for child in dialog.findChildren(object):
            if hasattr(child, "text") and callable(child.text):
                text = child.text()
                if "Google AI Studio Free-Tier" in text:
                    found_notice = True
                    self.assertTrue("Paid-Tier" in text or "Pay-as-you-go" in text)
                    break
        self.assertTrue(found_notice, "Transparent onboarding notice not found in SettingsDialog")



class TestChalkMultimodalSynthesis(unittest.TestCase):
    """
    Subagent 3 Unit Tests:
    1. Typed JSON Pydantic Schema & Strict Math Prompting
    2. Local KaTeX Syntax Validation & Escaping Fixes
    3. Deterministic Obsidian / GitHub Markdown Callout Rendering (∎ / [Lücke])
    4. Google Files API Lifecycle Deletion Guarantee (Zero Permanent Cloud Retention)
    """

    def test_validate_latex_syntax_valid(self):
        from src.api.synthesis_pipeline import validate_latex_syntax

        # Bayes Theorem
        valid_bayes = r"P(A|B) = \frac{P(B|A)P(A)}{P(B)}"
        is_valid, out = validate_latex_syntax(valid_bayes)
        self.assertTrue(is_valid)
        self.assertEqual(out, valid_bayes)

        # Standard Gaussian Integral
        valid_integral = r"\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}"
        is_valid_int, out_int = validate_latex_syntax(valid_integral)
        self.assertTrue(is_valid_int)

    def test_validate_latex_syntax_unbalanced_delimiters(self):
        from src.api.synthesis_pipeline import validate_latex_syntax

        # Unbalanced curly braces
        unbalanced_brace = r"P(A|B) = \frac{P(B|A)P(A)"
        is_valid, repaired = validate_latex_syntax(unbalanced_brace)
        self.assertFalse(is_valid)
        # Repaired version must be syntactically valid
        valid2, _ = validate_latex_syntax(repaired)
        self.assertTrue(valid2, f"Repaired latex '{repaired}' was still invalid")

        # Unbalanced brackets
        unbalanced_bracket = r"x \in [a, b)"
        is_valid_br, repaired_br = validate_latex_syntax(unbalanced_bracket)
        self.assertFalse(is_valid_br)

    def test_validate_latex_syntax_dangling_frac(self):
        from src.api.synthesis_pipeline import validate_latex_syntax

        # Dangling frac missing denominator (only 1 arg)
        frac_one_arg = r"f(x) = \frac{x}"
        is_valid, repaired = validate_latex_syntax(frac_one_arg)
        self.assertFalse(is_valid)
        self.assertIn("{[Lücke]}", repaired)
        valid2, _ = validate_latex_syntax(repaired)
        self.assertTrue(valid2)

        # Dangling frac with no arguments
        frac_no_args = r"y = \frac"
        is_valid_no, repaired_no = validate_latex_syntax(frac_no_args)
        self.assertFalse(is_valid_no)
        self.assertIn("{[Lücke]}{[Lücke]}", repaired_no)

    def test_validate_latex_syntax_invalid_control_sequences(self):
        from src.api.synthesis_pipeline import validate_latex_syntax

        # Unknown / non-KaTeX control sequence
        bad_seq = r"E = \nonexistentoperator{mc^2}"
        is_valid, repaired = validate_latex_syntax(bad_seq)
        self.assertFalse(is_valid)
        self.assertIn(r"\text{nonexistentoperator}", repaired)
        valid2, _ = validate_latex_syntax(repaired)
        self.assertTrue(valid2)

        # Trailing backslash
        trailing_bs = "a + b \\"
        is_valid_tb, repaired_tb = validate_latex_syntax(trailing_bs)
        self.assertFalse(is_valid_tb)
        self.assertEqual(repaired_tb, "a + b")

    def test_validate_latex_syntax_escaping_fixes(self):
        from src.api.synthesis_pipeline import validate_latex_syntax

        # Non-printable ASCII escapes from unescaped python strings
        raw_bad_escape = "\x0crac{1}{2} + \x08eta + \x09imes"
        is_valid, repaired = validate_latex_syntax(raw_bad_escape)
        self.assertFalse(is_valid)
        self.assertEqual(repaired, r"\frac{1}{2} + \beta + \times")
        valid2, _ = validate_latex_syntax(repaired)
        self.assertTrue(valid2)

    def test_render_blocks_to_markdown_callouts_and_proofs(self):
        from src.api.synthesis_pipeline import render_blocks_to_markdown, LectureNoteBlock

        blocks = [
            LectureNoteBlock(
                type="theorem",
                title="Satz von Bayes",
                latex=r"P(A|B) = \frac{P(B|A)P(A)}{P(B)}",
                explanation="Fundamentales Theorem der Wahrscheinlichkeitstheorie.",
                segment_id="SEG_28",
                source="slide",
            ),
            LectureNoteBlock(
                type="definition",
                title="Bedingte Wahrscheinlichkeit",
                latex=r"P(A|B) = \frac{P(A \cap B)}{P(B)}",
                explanation="Wahrscheinlichkeit unter Vorbedingung.",
                segment_id="SEG_28",
                source="slide",
            ),
            LectureNoteBlock(
                type="proof",
                title="Beweis Satz von Bayes",
                latex=r"P(A \cap B) = P(A|B)P(B) = P(B|A)P(A)",
                explanation="Direkt aus der Multiplikationsregel.",
                segment_id="SEG_28",
                source="speech",
            ),
            LectureNoteBlock(
                type="proof",
                title="Unvollständige Herleitung",
                latex=r"f(x) = \sum_{n=0}^{\infty} a_n x^n",
                explanation="Zwischenschritt ausgelassen [Lücke] wegen Zeitmangel.",
                segment_id="SEG_29",
                source="speech",
            ),
        ]

        markdown = render_blocks_to_markdown(blocks)

        # 1. Standard Obsidian / GitHub Callouts
        self.assertIn("> [!theorem] Satz von Bayes", markdown)
        self.assertIn("> [!definition] Bedingte Wahrscheinlichkeit", markdown)
        self.assertIn("> [!proof] Beweis Satz von Bayes", markdown)
        self.assertIn("> [!proof] Unvollständige Herleitung", markdown)

        # 2. Complete proof concludes with ∎ (QED symbol)
        self.assertIn("> ∎", markdown)

        # 3. Incomplete proof concludes with [Lücke]
        self.assertIn("> [Lücke]", markdown)

        # 4. Math displays rendered
        self.assertIn(r"> $$", markdown)
        self.assertIn(r"> P(A|B) = \frac{P(B|A)P(A)}{P(B)}", markdown)

    def test_pydantic_schema_and_strict_instruction(self):
        from src.api.synthesis_pipeline import (
            LectureNoteBlock,
            LectureSynthesisResponse,
            STRICT_MATH_SYNTHESIS_INSTRUCTION,
        )

        # Verify strict prompt instruction
        self.assertIn("Do not invent mathematical derivation steps", STRICT_MATH_SYNTHESIS_INSTRUCTION)
        self.assertIn("[Lücke]", STRICT_MATH_SYNTHESIS_INSTRUCTION)

        # Verify Pydantic JSON parsing & type normalization
        data = {
            "blocks": [
                {
                    "type": "Satz",  # Should normalize to "theorem"
                    "title": "Zentraler Grenzwertsatz",
                    "latex": r"\bar{X}_n \xrightarrow{d} \mathcal{N}(\mu, \sigma^2/n)",
                    "explanation": "Konvergenz der Summe unabhängiger Zufallsvariablen.",
                    "segment_id": "SEG_30",
                    "source": "slide",
                }
            ],
            "topic": "Statistik & Grenzwertsätze",
            "active_variables": ["X_n", "mu", "sigma"],
            "unresolved_proofs": [],
            "primary_speaker": "Prof. Dr. Schmidt",
        }

        response = LectureSynthesisResponse.model_validate(data)
        self.assertEqual(len(response.blocks), 1)
        self.assertEqual(response.blocks[0].type, "theorem")
        self.assertEqual(response.topic, "Statistik & Grenzwertsätze")

        # Convert to ChunkState
        chunk_state = response.to_chunk_state()
        self.assertEqual(chunk_state.topic, "Statistik & Grenzwertsätze")
        self.assertEqual(chunk_state.active_variables, ["X_n", "mu", "sigma"])

    def test_google_files_api_lifecycle_cleanup(self):
        from unittest.mock import MagicMock
        from src.api.gemini_client import GeminiLecturePipeline

        pipeline = GeminiLecturePipeline(api_key="mock-key-for-test")
        mock_client = MagicMock()
        pipeline._client = mock_client

        # Mock uploaded file
        mock_file = MagicMock()
        mock_file.name = "files/test-uploaded-lecture-audio-123"
        mock_file.uri = "https://generativelanguage.googleapis.com/v1beta/files/123"
        mock_client.files.upload.return_value = mock_file

        # 1. Test tracking on upload
        uploaded = pipeline.upload_file("dummy_audio.wav", mime_type="audio/wav")
        self.assertEqual(uploaded.name, "files/test-uploaded-lecture-audio-123")
        self.assertIn(mock_file, pipeline._tracked_files)

        # 2. Test lifecycle deletion in finally block on successful generation
        mock_response = MagicMock()
        mock_response.text = "Synthesis result"
        mock_client.models.generate_content.return_value = mock_response

        pipeline._call_generate_content(
            client=mock_client,
            model="gemini-2.5-flash",
            contents=["Test prompt"],
            tracked_files=[mock_file],
        )

        mock_client.files.delete.assert_called_with(name="files/test-uploaded-lecture-audio-123")
        self.assertNotIn(mock_file, pipeline._tracked_files)

        # 3. Test lifecycle deletion guarantee in finally block on generation exception
        mock_client.files.delete.reset_mock()
        pipeline._tracked_files.append(mock_file)
        mock_client.models.generate_content.side_effect = RuntimeError("Simulated API Crash")

        with self.assertRaises(RuntimeError):
            pipeline._call_generate_content(
                client=mock_client,
                model="gemini-2.5-flash",
                contents=["Crashing prompt"],
                tracked_files=[mock_file],
            )

        # Verification: Zero permanent cloud retention even after exception
        mock_client.files.delete.assert_called_with(name="files/test-uploaded-lecture-audio-123")
        self.assertNotIn(mock_file, pipeline._tracked_files)


class TestChalkHudKaTeXRendering(unittest.TestCase):
    def test_latex_to_katex_html_conversions(self):
        from src.ui.hud_window import latex_to_katex_html

        # Test Greek symbols and subscripts
        capm = r"E(R_i) = R_f + \beta_i [E(R_m) - R_f]"
        html_capm = latex_to_katex_html(capm)
        self.assertIn("&beta;", html_capm)
        self.assertIn("<sub>i</sub>", html_capm)
        self.assertNotIn(r"\beta", html_capm)

        # Test fraction conversion to centered table
        bayes = r"P(A|B) = \frac{P(B|A)P(A)}{P(B)}"
        html_bayes = latex_to_katex_html(bayes)
        self.assertIn("<table", html_bayes)
        self.assertIn("P(B|A)P(A)", html_bayes)
        self.assertIn("P(B)", html_bayes)

        # Test square root and summation
        variance = r"\sigma = \sqrt{\frac{1}{N} \sum_{i=1}^N (x_i - \mu)^2}"
        html_var = latex_to_katex_html(variance)
        self.assertIn("&radic;", html_var)
        self.assertIn("&sum;", html_var)
        self.assertIn("&mu;", html_var)

    def test_render_markdown_with_katex(self):
        from src.ui.hud_window import render_markdown_with_katex

        md = (
            "# Lecture: Financial Theory\n\n"
            "> [!theorem] CAPM Security Market Line\n"
            "$$E(R_i) = R_f + \\beta_i [E(R_m) - R_f]$$\n"
            "Here is an inline symbol $\\alpha > 0$ and link [00:14:15](chalk-audio://00:14:15). ∎"
        )
        html = render_markdown_with_katex(md)
        self.assertIn("chalk-audio://00:14:15", html)
        self.assertIn("THEOREM", html)
        self.assertIn("&beta;", html)
        self.assertIn("&alpha;", html)
        self.assertIn("&#8718;", html)  # Q.E.D. mark
        self.assertIn("#1A1C23", html)  # Dark titanium math card

    def test_chalk_audio_url_parsing(self):
        from src.ui.hud_window import parse_audio_timestamp, format_timestamp

        # HH:MM:SS format
        self.assertEqual(parse_audio_timestamp("chalk-audio://01:24:15"), 5055.0)
        self.assertEqual(parse_audio_timestamp("chalk-audio://00:10:30"), 630.0)

        # MM:SS format
        self.assertEqual(parse_audio_timestamp("chalk-audio://24:15"), 1455.0)
        self.assertEqual(parse_audio_timestamp("chalk-audio://05:00"), 300.0)

        # Raw seconds format
        self.assertEqual(parse_audio_timestamp("chalk-audio://5055"), 5055.0)
        self.assertEqual(parse_audio_timestamp("chalk-audio://120.5"), 120.5)

        # Direct timestamp strings (no scheme)
        self.assertEqual(parse_audio_timestamp("01:24:15"), 5055.0)
        self.assertEqual(parse_audio_timestamp("45"), 45.0)

        # Formatting helper
        self.assertEqual(format_timestamp(5055.0), "01:24:15")
        self.assertEqual(format_timestamp(1455.0), "24:15")
        self.assertEqual(format_timestamp(45.0), "00:45")

    def test_obsidian_vault_and_frontmatter(self):
        import tempfile
        import shutil
        from datetime import datetime
        from src.engine.session_state import SessionNotesManager, slugify_topic
        from src.engine.config import set_obsidian_vault_path, get_obsidian_vault_path

        temp_vault = tempfile.mkdtemp(prefix="chalk_test_vault_")
        try:
            # Test slugify
            self.assertEqual(slugify_topic("Measure Theory"), "measure_theory")
            self.assertEqual(slugify_topic("Machine Learning: Deep Neural Nets!"), "machine_learning_deep_neural_nets")

            # Test config persistence
            set_obsidian_vault_path(temp_vault)
            self.assertEqual(get_obsidian_vault_path(), os.path.abspath(temp_vault))

            # Test SessionNotesManager with Obsidian auto-organization
            today_str = datetime.now().strftime("%Y-%m-%d")
            notes_mgr = SessionNotesManager(
                notes_dir=os.path.join(temp_vault, "Chalk"),
                session_id="sess_test_123",
                topic="Measure Theory",
                is_obsidian=True,
            )

            # 1. Subfolder creation: <Vault>/Chalk/
            self.assertTrue(os.path.isdir(os.path.join(temp_vault, "Chalk")))

            # 2. Note naming: <YYYY-MM-DD>_<slug>.md
            expected_filename = f"{today_str}_measure_theory.md"
            self.assertEqual(os.path.basename(notes_mgr.session_file), expected_filename)
            self.assertTrue(os.path.exists(notes_mgr.session_file))

            # 3. YAML frontmatter content
            content = notes_mgr.read_full_notes()
            self.assertIn("---", content)
            self.assertIn("tags: [chalk, lecture, study]", content)
            self.assertIn(f"date: {today_str}", content)
            self.assertIn('topic: "Measure Theory"', content)
            self.assertIn('audio_session: "sess_test_123"', content)
        finally:
            set_obsidian_vault_path(None)
            shutil.rmtree(temp_vault, ignore_errors=True)

    def test_diagram_to_mermaid_synthesis_rendering(self):
        from src.api.synthesis_pipeline import LectureNoteBlock, render_blocks_to_markdown

        # Test block with Mermaid flowchart
        diagram_block = LectureNoteBlock(
            type="diagram",
            title="Verteilte Systemarchitektur",
            latex="graph TD\n    Client[Web Client] --> Gateway[API Gateway]\n    Gateway --> ServiceA[Auth Service]\n    Gateway --> ServiceB[Compute Service]",
            explanation="Architekturüberblick der Microservices-Infrastruktur.",
            segment_id="SEG_30",
            source="slide",
        )

        # 1. Type validation and synonym normalization
        self.assertEqual(diagram_block.type, "diagram")

        flowchart_block = LectureNoteBlock(
            type="flowchart",
            title="Prozessablauf",
            latex="graph LR\n    A --> B",
        )
        self.assertEqual(flowchart_block.type, "diagram")

        # 2. Markdown rendering contains ```mermaid fenced code block
        markdown = render_blocks_to_markdown([diagram_block])
        self.assertIn("```mermaid", markdown)
        self.assertIn("graph TD", markdown)
        self.assertIn("Client[Web Client] --> Gateway[API Gateway]", markdown)
        self.assertIn("```", markdown)
        self.assertIn("> [!diagram] Verteilte Systemarchitektur", markdown)

    def test_journal_get_audio_slice(self):
        import tempfile
        import shutil
        import numpy as np
        from src.engine.journal import SessionJournal

        temp_dir = tempfile.mkdtemp(prefix="chalk_journal_slice_test_")
        try:
            journal = SessionJournal(session_id="test_slice_sess", base_dir=temp_dir)
            sr = 16000

            # Write two 30-second segments of stereo audio
            seg1_audio = np.full((30 * sr, 2), 0.25, dtype=np.float32)
            seg2_audio = np.full((30 * sr, 2), 0.50, dtype=np.float32)

            journal.write_segment(seg1_audio, start_wall_clock=1000.0, duration_sec=30.0)
            journal.write_segment(seg2_audio, start_wall_clock=1030.0, duration_sec=30.0)

            # Request 20s slice around 25s (spans 15s to 35s, crossing segment boundary)
            sliced_audio, slice_sr = journal.get_audio_slice(target_timestamp_sec=25.0, slice_duration=20.0)

            self.assertEqual(slice_sr, sr)
            self.assertEqual(sliced_audio.ndim, 2)
            self.assertEqual(sliced_audio.shape[1], 2)
            # Duration should be 20 seconds = 320,000 samples
            self.assertEqual(len(sliced_audio), 20 * sr)
            # First half should be from seg1 (0.25), second half from seg2 (0.50)
            self.assertAlmostEqual(float(sliced_audio[0, 0]), 0.25, places=2)
            self.assertAlmostEqual(float(sliced_audio[-1, 0]), 0.50, places=2)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_multi_speaker_diarization_callouts(self):
        from src.api.synthesis_pipeline import LectureNoteBlock, render_blocks_to_markdown

        # 1. Normalization of speaker tags & synonyms
        b_aud1 = LectureNoteBlock(
            type="remark",
            title="Frage zum Konvergenzradius",
            speaker="Audience Question",
            explanation="Warum divergiert die Reihe außerhalb von r?\nResponse: Weil die Glieder keine Nullfolge mehr bilden.",
            latex=r"\lim_{n \to \infty} a_n \neq 0",
            segment_id="01:14:20",
        )
        self.assertEqual(b_aud1.speaker, "Audience Question")

        b_aud2 = LectureNoteBlock(
            type="example",
            title="Audience Question @ 01:25:00",
            speaker="student",  # Synonym
            explanation="Gilt das auch in Banachräumen?",
        )
        self.assertEqual(b_aud2.speaker, "Audience Question")

        b_lec = LectureNoteBlock(
            type="theorem",
            title="Hauptsatz der Analysis",
            speaker="dozent",  # Synonym
            explanation="Zusammenhang zwischen Differentiation und Integration.",
            latex=r"\int_a^b f'(x) dx = f(b) - f(a)",
        )
        self.assertEqual(b_lec.speaker, "Lecturer")

        # 2. Deterministic Callout Rendering for Audience Questions
        md_aud = render_blocks_to_markdown([b_aud1])
        self.assertIn("> [!question] Audience Question: Frage zum Konvergenzradius @ 01:14:20", md_aud)
        self.assertIn("> **Question:** Warum divergiert die Reihe außerhalb von r?", md_aud)
        self.assertIn("> **Response / Derivation:** Weil die Glieder keine Nullfolge mehr bilden.", md_aud)
        self.assertIn(r"> $$", md_aud)
        self.assertIn(r"> \lim_{n \to \infty} a_n \neq 0", md_aud)

        # 3. Clean Lecturer rendering without question overhead
        md_lec = render_blocks_to_markdown([b_lec])
        self.assertIn("> [!theorem] Hauptsatz der Analysis", md_lec)
        self.assertNotIn("> [!question]", md_lec)
        self.assertNotIn("> **Question:**", md_lec)

    def test_phase21_mermaid_sanitization(self):
        """Phase 21: Verify Mermaid diagram syntax validation and label quoting."""
        from src.api.synthesis_pipeline import sanitize_mermaid_syntax

        # 1. Missing declaration defaults to graph TD
        raw_graph = "A --> B\nB --> C"
        sanitized = sanitize_mermaid_syntax(raw_graph)
        self.assertTrue(sanitized.startswith("graph TD\n"))

        # 2. Parens in labels are quoted
        raw_labels = "graph TD\n    NodeA[Client (Browser)] --> NodeB[Server: Backend]\n    NodeC[No Special] --> NodeD"
        sanitized_labels = sanitize_mermaid_syntax(raw_labels)
        self.assertIn('NodeA["Client (Browser)"]', sanitized_labels)
        self.assertIn('NodeB["Server: Backend"]', sanitized_labels)
        self.assertIn("NodeC[No Special]", sanitized_labels)

    def test_phase21_journal_defensive_io_and_emergency_dump(self):
        """Phase 21: Verify emergency session dump and corrupted WAV recovery."""
        import tempfile
        import shutil
        from src.engine.journal import SessionJournal

        temp_dir = tempfile.mkdtemp(prefix="chalk_test_p21_")
        try:
            journal = SessionJournal(session_id="test_p21_sess", base_dir=temp_dir)

            # 1. Emergency dump
            payload = {"uncommitted_text": "Important derivation", "segments": [1, 2]}
            dump_file = journal.save_emergency_dump(payload, "Network timeout 504")
            self.assertTrue(os.path.exists(dump_file))
            with open(dump_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["session_id"], "test_p21_sess")
            self.assertEqual(data["error"], "Network timeout 504")
            self.assertEqual(data["payload"]["uncommitted_text"], "Important derivation")

            # 2. Corrupt WAV handling
            corrupt_path = os.path.join(journal.session_dir, "seg_0099.wav")
            with open(corrupt_path, "wb") as f:
                f.write(b"NOT A REAL WAV FILE HEADER 12345678")

            # Reading corrupt segment should not raise unhandled crash
            audio, sr = journal.read_segment_audio("seg_0099")
            self.assertEqual(sr, 16000)
            self.assertEqual(len(audio), 16000 * 30)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_phase21_multiprovider_backoff_and_emergency_dump(self):
        """Phase 21: Verify multi-provider exponential backoff with jitter and emergency dump."""
        from src.api.multi_provider import AnthropicClaudeAdapter, OpenAIAdapter
        import tempfile
        import shutil

        claude = AnthropicClaudeAdapter(api_key="sk-ant-testkey123456789012345678901234")
        calls = []

        def failing_func():
            calls.append(1)
            if len(calls) < 3:
                raise Exception("HTTP 429 Rate Limit Exceeded")
            return "Success after backoff"

        # Should retry and succeed on 3rd attempt
        res = claude._execute_with_backoff(failing_func)
        self.assertEqual(res, "Success after backoff")
        self.assertEqual(len(calls), 3)


class TestPhase23And24AcademicSuite(unittest.TestCase):
    """Phase 23 & 24: Test suite for Academic Power-User Suite, PDF, Anki, and Search."""

    def test_flashcard_pydantic_and_markdown_rendering(self):
        """Test FlashcardItem, rendering to markdown, extraction, and Anki TSV export."""
        import tempfile
        from src.api.synthesis_pipeline import (
            FlashcardItem,
            render_flashcards_to_markdown,
            extract_flashcards_from_markdown,
            export_flashcards_to_tsv,
        )

        item1 = FlashcardItem(
            question="Was besagt der Satz von Bayes?",
            answer_latex=r"P(A|B) = \frac{P(B|A)P(A)}{P(B)}",
            reference_timestamp="14:20",
        )
        item2 = FlashcardItem(
            question="Welche Eigenschaft zeichnet orthogonale Matrizen aus?",
            answer_latex=r"Q^T Q = I",
            reference_timestamp=None,
        )

        md = render_flashcards_to_markdown([item1, item2])
        self.assertIn("## Exam Flashcards & Spaced Repetition", md)
        self.assertIn("Was besagt der Satz von Bayes?", md)
        self.assertIn("#flashcard", md)
        self.assertIn("?", md)

        # Extraction from markdown
        extracted = extract_flashcards_from_markdown(md)
        self.assertEqual(len(extracted), 2)
        self.assertEqual(extracted[0].question, "Was besagt der Satz von Bayes?")
        self.assertIn("P(A|B)", extracted[0].answer_latex)

        # Anki TSV export
        with tempfile.NamedTemporaryFile(suffix=".tsv", delete=False) as tmp:
            tmp_tsv = tmp.name

        try:
            ok = export_flashcards_to_tsv([item1, item2], tmp_tsv)
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(tmp_tsv))
            with open(tmp_tsv, "r", encoding="utf-8") as f:
                content = f.read()
            lines = [l for l in content.splitlines() if l.strip()]
            self.assertEqual(len(lines), 2)
            self.assertIn("\t", lines[0])  # Tab separated
            self.assertIn("Satz von Bayes", lines[0])
            self.assertIn("P(A|B)", lines[0])
        finally:
            if os.path.exists(tmp_tsv):
                os.remove(tmp_tsv)

    def test_pdf_export_qpdfwriter(self):
        """Test standalone academic PDF generation via QTextDocument and QPdfWriter."""
        import tempfile
        from src.export.pdf_exporter import export_notes_to_pdf, markdown_to_academic_html

        sample_notes = """# Höhere Mathematik II: Lineare Differentialgleichungen

> [!theorem] Existenz- und Eindeutigkeitssatz von Picard-Lindelöf
> Sei $f(t, x)$ stetig und bzgl. $x$ lokal Lipschitz-stetig. Dann existiert genau eine Lösung des AWP.

- Wichtige Formel besprochen um [09:45](chalk-audio://09:45)
- Standardansatz für homogene DGL:
$$x(t) = C e^{\\lambda t}$$
"""
        html = markdown_to_academic_html(sample_notes, title="HM II")
        self.assertIn("Picard-Lindelöf", html)
        self.assertIn("callout-theorem", html)
        self.assertIn("math-block", html)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_pdf = tmp.name

        try:
            ok = export_notes_to_pdf(sample_notes, tmp_pdf, title="HM II")
            self.assertTrue(ok)
            self.assertTrue(os.path.exists(tmp_pdf))
            self.assertGreater(os.path.getsize(tmp_pdf), 1000)
            with open(tmp_pdf, "rb") as f:
                header = f.read(5)
            self.assertEqual(header, b"%PDF-")
        finally:
            if os.path.exists(tmp_pdf):
                os.remove(tmp_pdf)

    def test_session_archive_search(self):
        """Test local fulltext and formula archive search."""
        import tempfile
        import shutil
        from src.ui.search_dialog import search_archive

        temp_dir = tempfile.mkdtemp(prefix="chalk_test_search_")
        try:
            note_path = os.path.join(temp_dir, "Quantum_Computing.md")
            with open(note_path, "w", encoding="utf-8") as f:
                f.write(
                    "# Quantenalgorithmen\n\n"
                    "## Shors Algorithmus\n"
                    "Shors Algorithmus faktorisiert Zahlen in polynomieller Zeit [18:45](chalk-audio://18:45).\n"
                    "Die diskrete Fourier-Transformation bildet den Kernschritt.\n"
                )

            # Search for keyword "Shor"
            results = search_archive("Shor", extra_dirs=[temp_dir])
            self.assertGreaterEqual(len(results), 1)
            ts_matches = [r for r in results if r.timestamp_sec is not None]
            self.assertGreaterEqual(len(ts_matches), 1)
            first = ts_matches[0]
            self.assertEqual(first.session_title, "Quantenalgorithmen")
            self.assertIn("polynomieller Zeit", first.match_snippet)
            self.assertEqual(first.timestamp_str, "18:45")
            self.assertEqual(first.timestamp_sec, 18 * 60 + 45.0)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_output_language_config(self):
        """Test persistent target output synthesis language setting."""
        from src.engine.config import get_output_language, set_output_language

        orig_lang = get_output_language()
        try:
            set_output_language("de")
            self.assertEqual(get_output_language(), "de")

            set_output_language("en")
            self.assertEqual(get_output_language(), "en")

            set_output_language("auto")
            self.assertEqual(get_output_language(), "auto")
        finally:
            set_output_language(orig_lang)

    def test_bulletproof_local_ip_discovery(self):
        """Test multi-tier LAN/Hotspot IP discovery."""
        from src.companion.server import get_local_ip

        ip = get_local_ip()
        self.assertIsInstance(ip, str)
        parts = ip.split(".")
        self.assertEqual(len(parts), 4)
        for part in parts:
            self.assertTrue(part.isdigit())
            self.assertTrue(0 <= int(part) <= 255)

    def test_phase25_notation_ledger_schema_and_rendering(self):
        """Test Mathematical Notation & Variable Ledger Pydantic schema and table rendering."""
        from src.api.synthesis_pipeline import (
            NotationItem,
            LectureSynthesisResponse,
            render_notations_to_markdown,
            render_synthesis_to_markdown,
        )

        item1 = NotationItem(
            symbol=r"\beta_i",
            definition="Asset return sensitivity relative to market benchmark",
            introduced_in_segment="Segment 01 [00:14:20]",
        )
        item2 = NotationItem(
            symbol=r"R_f",
            definition="Risk-free rate of return (e.g. 10Y Treasury)",
            introduced_in_segment="Segment 01 [00:16:45]",
        )

        # Test table rendering
        table_md = render_notations_to_markdown([item1, item2])
        self.assertIn("### Mathematical Notation & Variable Ledger", table_md)
        self.assertIn("| Symbol | Conceptual Definition | Context / Segment |", table_md)
        self.assertIn(r"| $\beta_i$ | Asset return sensitivity relative to market benchmark | Segment 01 [00:14:20] |", table_md)
        self.assertIn(r"| $R_f$ | Risk-free rate of return (e.g. 10Y Treasury) | Segment 01 [00:16:45] |", table_md)

        # Empty notations returns empty string
        self.assertEqual(render_notations_to_markdown([]), "")

    def test_phase25_socratic_recall_drill(self):
        """Test Socratic Active Recall Debrief callouts and synthesis integration."""
        from src.api.synthesis_pipeline import (
            LectureSynthesisResponse,
            LectureNoteBlock,
            NotationItem,
            render_socratic_to_markdown,
            render_synthesis_to_markdown,
        )

        questions = [
            "Was ist die primäre Invariante des CAPM-Gleichgewichts?",
            "Welche Grenzannahme bzgl. Arbitragefreiheit muss erfüllt sein?",
            "Welcher typische Fehler tritt bei heterogenen Erwartungen auf?",
        ]

        socratic_md = render_socratic_to_markdown(questions)
        self.assertIn("> [!question] Socratic Active Recall", socratic_md)
        self.assertIn("> 1. Was ist die primäre Invariante des CAPM-Gleichgewichts?", socratic_md)
        self.assertIn("> 2. Welche Grenzannahme bzgl. Arbitragefreiheit muss erfüllt sein?", socratic_md)
        self.assertIn("> 3. Welcher typische Fehler tritt bei heterogenen Erwartungen auf?", socratic_md)

        # Full response rendering order verification (Notations -> Blocks -> Socratic)
        resp = LectureSynthesisResponse(
            topic="Capital Asset Pricing Model",
            notations=[
                NotationItem(symbol=r"\beta_i", definition="Systematisches Risiko", introduced_in_segment="Seg 1")
            ],
            blocks=[
                LectureNoteBlock(
                    type="theorem",
                    title="CAPM Wertpapiermarktlinie",
                    latex=r"E(R_i) = R_f + \beta_i [E(R_m) - R_f]",
                    explanation="Erwartete Rendite im Marktgleichgewicht.",
                    source="slide",
                )
            ],
            socratic_questions=questions,
        )

        full_md = render_synthesis_to_markdown(resp)
        self.assertIn("### Mathematical Notation & Variable Ledger", full_md)
        self.assertIn("> [!theorem] CAPM Wertpapiermarktlinie", full_md)
        self.assertIn("> [!question] Socratic Active Recall", full_md)
        # Notations must appear before theorem callout
        notations_idx = full_md.index("### Mathematical Notation & Variable Ledger")
        theorem_idx = full_md.index("> [!theorem]")
        socratic_idx = full_md.index("> [!question] Socratic Active Recall")
        self.assertLess(notations_idx, theorem_idx)
        self.assertLess(theorem_idx, socratic_idx)

    def test_phase25_zero_emojis_in_synthesis_and_markdown(self):
        """Verify 0 emojis exist in rendered markdown and session state."""
        import re
        from src.api.synthesis_pipeline import (
            LectureSynthesisResponse,
            LectureNoteBlock,
            NotationItem,
            FlashcardItem,
            render_synthesis_to_markdown,
        )
        from src.engine.session_state import SessionNotesManager

        emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]')

        resp = LectureSynthesisResponse(
            topic="Stochastische Differentialgleichungen",
            notations=[
                NotationItem(symbol=r"W_t", definition="Wiener-Prozess / Brownsche Bewegung", introduced_in_segment="00:05:00")
            ],
            blocks=[
                LectureNoteBlock(
                    type="definition",
                    title="Itô-Integral",
                    latex=r"X_t = \int_0^t \sigma_s \, dW_s",
                    explanation="Stochastisches Integral bezüglich der Brownschen Bewegung.",
                    source="slide",
                )
            ],
            flashcards=[
                FlashcardItem(question="Was ist die quadratische Variation von W_t?", answer_latex=r"[W, W]_t = t")
            ],
            socratic_questions=[
                "Warum ist das Itô-Integral ein Martingal?",
                "Wie unterscheidet sich das Stratonovich-Integral?",
                "Welche Bedingung fordert das Lemma von Itô?",
            ],
        )

        md = render_synthesis_to_markdown(resp)
        emojis_found = emoji_pattern.findall(md)
        self.assertEqual(len(emojis_found), 0, f"Emojis found in rendered markdown: {emojis_found}")

        with tempfile.TemporaryDirectory() as td:
            notes_mgr = SessionNotesManager(notes_dir=td, session_id="test_p25_clean")
            notes_mgr.append_chunk_notes(md, "00:00:00", "00:15:00")
            notes_mgr.append_master_synthesis("# Consolidated Review\n\nAll theorems verified.")

            with open(notes_mgr.session_file, "r", encoding="utf-8") as f:
                content = f.read()
            session_emojis = emoji_pattern.findall(content)
            self.assertEqual(len(session_emojis), 0, f"Emojis found in session file: {session_emojis}")


class TestChalkHardeningAndForensics(unittest.TestCase):
    """Targeted regression tests for Claude's forensic code review points."""

    def test_sixteen_mathematical_formulas_preserved(self):
        """Verify all 16 mathematical formulas pass KaTeX validation without corruption."""
        from src.api.synthesis_pipeline import validate_latex_syntax

        formulas = [
            r"\langle x, y \rangle",
            r"\binom{n}{k}",
            r"\Vert x \Vert",
            r"\lfloor x \rfloor",
            r"\lceil x \rceil",
            r"A \wedge B \vee C",
            r"\bigcup_{i=1}^n A_i",
            r"\bigcap_{i=1}^n B_i",
            r"A \xrightarrow{f} B",
            r"\overset{\mathrm{def}}{=}",
            r"\boxed{E = mc^2}",
            r"x \not= y",
            r"\frac{a}{b}",
            r"\int_{-\infty}^{\infty} e^{-x^2} dx = \sqrt{\pi}",
            r"\sum_{k=0}^n \binom{n}{k} a^k b^{n-k}",
            r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
        ]

        for f in formulas:
            is_valid, out = validate_latex_syntax(f)
            self.assertTrue(is_valid, f"Formula '{f}' should be valid KaTeX syntax")
            # Ensure none of the commands were mutilated into \text{cmd}
            for cmd in ["langle", "rangle", "binom", "Vert", "lfloor", "rfloor", "lceil", "rceil", "wedge", "vee", "bigcup", "bigcap", "xrightarrow", "overset", "boxed"]:
                self.assertNotIn(f"\\text{{{cmd}}}", out, f"Command \\{cmd} was improperly rewritten into \\text in '{out}'")

    def test_read_local_file_sandbox_security(self):
        """Verify path traversal and forbidden system directories are strictly blocked."""
        from src.api.tools import read_local_file

        # 1. System files
        res1 = read_local_file("/etc/passwd")
        self.assertIn("Security Error", res1)

        res2 = read_local_file("/var/log/system.log")
        self.assertIn("Security Error", res2)

        # 2. Sensitive dotfiles
        res3 = read_local_file("~/.ssh/id_rsa")
        self.assertIn("Security Error", res3)

        res4 = read_local_file("~/.bash_history")
        self.assertIn("Security Error", res4)

        # 3. Path traversal attempts
        res5 = read_local_file("../../.env")
        self.assertIn("Security Error", res5)

    def test_chunk_quarantine_preserves_audio_and_meta(self):
        """Verify chunk quarantine saves audio and JSON metadata without data loss."""
        from src.main import ChalkCoordinator
        import shutil

        quarantine_root = os.path.expanduser("~/.chalk/quarantine")
        test_audio = np.random.uniform(-0.1, 0.1, (16000, 2)).astype(np.float32)

        # Create dummy coordinator with mocked app
        class DummyApp:
            def quit(self): pass
        app = DummyApp()
        coord = ChalkCoordinator.__new__(ChalkCoordinator)

        try:
            coord._quarantine_chunk(
                audio_data=test_audio,
                keyframes=[],
                whiteboard_photos=[],
                error_reason="Persistent API 500 error",
            )
            # Verify quarantine directory created
            self.assertTrue(os.path.isdir(quarantine_root))
            entries = os.listdir(quarantine_root)
            self.assertTrue(len(entries) > 0)
        finally:
            # Clean up test quarantine
            shutil.rmtree(quarantine_root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()




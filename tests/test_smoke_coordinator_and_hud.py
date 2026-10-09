"""
tests/test_smoke_coordinator_and_hud.py - Headless Smoke Test Suite for HUD and Coordinator Slots.
Instantiates PyQt6 HUD and coordinator offscreen, calls primary slots and functions,
and verifies thread-safe signal and slot execution without SIGABRT crashes.
"""

import os
import sys
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch

# Configure offscreen Qt platform before importing PyQt6
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtCore import Qt

from src.engine.session_state import ChunkState
from src.ui.hud_window import FloatingHUDWindow
from src.main import ChalkCoordinator


class TestSmokeCoordinatorAndHUD(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance()
        if cls.app is None:
            cls.app = QApplication(["--platform", "offscreen"])

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="chalk_smoke_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_hud_offscreen_functions(self):
        """Verifies FloatingHUDWindow instantiates and primary methods execute cleanly offscreen."""
        hud = FloatingHUDWindow()
        hud.show()

        # Call methods across primary capabilities
        hud.set_daemon_status("recording", "Recording active")
        hud.set_daemon_status("idle", "Idle")
        hud.switch_tab(0)
        hud.switch_tab(1)
        hud.switch_tab(2)
        hud.toggle_expand()
        hud.toggle_expand()
        hud.apply_theme("dark")
        hud.apply_theme("light")
        hud.change_language("de")
        hud.change_language("en")
        hud.display_live_notes("# Notes\n- Point 1\n- Point 2")
        hud.refresh_live_notes_view()
        hud.show_socratic_debrief(["Q1: Core derivation?", "Q2: Boundary condition?"])

        # Test audio slice playback with invalid offset (should report slice unavailable without playing wrong live audio)
        hud.play_audio_slice(offset_seconds=9999.0)

        hud.hide()
        hud.deleteLater()

    @patch("src.main.get_api_key", return_value="dummy_key_for_testing")
    @patch("src.main.DualChannelAudioRecorder")
    @patch("src.main.EventGatedScreenGrabber")
    @patch("src.main.ElasticChunker")
    @patch("src.main.ChalkSystemTray")
    @patch("src.companion.server.CompanionDaemon")
    def test_coordinator_slots_execution(
        self,
        mock_daemon,
        mock_tray,
        mock_chunker,
        mock_grabber,
        mock_recorder,
        mock_key,
    ):
        """Directly invokes coordinator slots to verify robust crash-free handling."""
        coord = ChalkCoordinator(app=self.app)
        coord.notes_dir = self.temp_dir
        coord.notes_manager.session_file = os.path.join(self.temp_dir, "test_notes.md")

        # 1. _on_chunk_success
        test_state = ChunkState(topic="Linear Algebra", active_variables=["v", "lambda"])
        test_markdown = "## Linear Algebra\n> [!theorem] Spectral Theorem\n> $$A = Q \\Lambda Q^T$$\n"
        coord._on_chunk_success(test_markdown, test_state, "00:00", "15:00")

        # 2. _on_chunk_failed with non-auth error (e.g. transient 500 error)
        coord.recorder.reinsert_segment_ids = MagicMock()
        coord.chunker.set_retry_backoff = MagicMock()
        coord.screen_grabber.reinsert_unprocessed_keyframes = MagicMock()
        coord._on_chunk_failed(
            RuntimeError("Server 500 error"),
            None,
            [],
            whiteboard_photos=None,
            segment_ids=["seg_0001", "seg_0002"],
            prev_start_sec=0.0,
        )
        coord.recorder.reinsert_segment_ids.assert_called_with(["seg_0001", "seg_0002"])
        coord.chunker.set_retry_backoff.assert_called_with(2)

        # 3. _on_chunk_failed with auth error (audio recording must NEVER be paused!)
        coord.recorder.pause = MagicMock()
        coord._on_chunk_failed(
            RuntimeError("401 API_KEY_INVALID"),
            None,
            [],
            whiteboard_photos=None,
            segment_ids=["seg_0003"],
            prev_start_sec=30.0,
        )
        coord.recorder.pause.assert_not_called()

        # 4. Companion photo slot on HUD
        test_photo = os.path.join(self.temp_dir, "photo_01.jpg")
        with open(test_photo, "wb") as f:
            f.write(b"dummy")
        coord.hud._on_whiteboard_photo_received(test_photo, "14:00:00")
        self.assertIn(test_photo, coord.hud.whiteboard_photos)
        popped = coord.hud.pop_unprocessed_whiteboard_photos()
        self.assertEqual(popped, [test_photo])

        # 5. Break detection and speech resumed
        coord.recorder.pause = MagicMock()
        coord.recorder.resume = MagicMock()
        coord.screen_grabber.pause = MagicMock()
        coord.screen_grabber.resume = MagicMock()
        coord._dispatch_chunk_flush = MagicMock()
        coord._handle_break_detected()
        coord.screen_grabber.pause.assert_called_once()
        coord.recorder.pause.assert_called_once()

        coord._handle_speech_resumed()
        coord.screen_grabber.resume.assert_called_once()
        coord.recorder.resume.assert_called_once()

        # Clean shutdown
        coord.hud.deleteLater()


if __name__ == "__main__":
    unittest.main()

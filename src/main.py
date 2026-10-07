"""
src/main.py - Application Entry Point & Thread Lifecycle Coordinator.
Wires together:
- True Zero-Knowledge BYOK Key Manager & Settings Modal
- Dual-Channel Hardware Diarization Audio Capture & Silero VAD
- Event-Gated Screen Grabber & pHash Slide Deduplication
- Adaptive Rate Controller Quota Manager & Elastic Chunker
- Hybrid Gemini Flash / Pro Pipeline with Local Tool Calling
- Floating Agent HUD (Cmd+Shift+Space / Ctrl+Shift+Space), Snip Marquee (Cmd+Shift+S / Alt+S), and pystray System Tray
- Native Zero-Permission Hotkeys (Cmd/Ctrl+Shift+Space, Cmd/Ctrl+Shift+S, F9, F10)
- Autonomous Break Detection (>180s) and HTTP 429 Recovery
"""

import sys
import os
import time
import subprocess
import threading
import logging
from typing import Optional, List, Any, Dict, Tuple

from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QEvent
from PyQt6.QtWidgets import QApplication, QMessageBox


class ChalkApplication(QApplication):
    """
    Custom QApplication subclass that intercepts macOS QFileOpenEvent
    for custom URL scheme 'chalk-audio://...'.
    """
    url_opened = pyqtSignal(str)

    def event(self, event: QEvent) -> bool:
        if event.type() == QEvent.Type.FileOpen:
            try:
                url_str = ""
                if hasattr(event, "url"):
                    url_val = event.url()
                    url_str = url_val.toString() if hasattr(url_val, "toString") else str(url_val)
                if not url_str and hasattr(event, "file"):
                    url_str = event.file()
                if url_str:
                    logger.info("ChalkApplication intercepted URL event: %s", url_str)
                    self.url_opened.emit(url_str)
                    return True
            except Exception as e:
                logger.warning("Error handling QFileOpenEvent: %s", e)
        return super().event(event)

# Module Imports
from src.security.key_manager import has_api_key, get_api_key
from src.security.hotkeys import NativeHotkeyManager
from src.ui.settings_dialog import SettingsDialog, ensure_api_key_configured
from src.audio.vad_detector import SileroVADDetector
from src.audio.recorder import DualChannelAudioRecorder
from src.vision.slide_filter import PerceptualSlideFilter
from src.vision.accessibility import AccessibilityTextExtractor
from src.vision.screen_grabber import EventGatedScreenGrabber
from src.engine.quota_manager import QuotaManager
from src.engine.session_state import SessionNotesManager, ChunkState
from src.engine.journal import recover_unprocessed_sessions
from src.engine.elastic_chunker import ElasticChunker
from src.api.gemini_client import GeminiLecturePipeline
from src.api.tools import register_tool_context
from src.ui.hud_window import FloatingHUDWindow
from src.ui.tray import ChalkSystemTray
from src.ui.i18n import tr, get_ui_language

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s) %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("chalk.main")


def send_desktop_notification(title: str, message: str):
    """Dispatches a native OS desktop notification without external binaries."""
    try:
        if sys.platform == "darwin":
            clean_title = title.replace('\\', '\\\\').replace('"', '\\"')
            clean_msg = message.replace('\\', '\\\\').replace('"', '\\"')
            script = f'display notification "{clean_msg}" with title "{clean_title}"'
            subprocess.Popen(["osascript", "-e", script])
        elif sys.platform == "win32":
            clean_title = title.replace('"', '`"').replace('$', '`$')
            clean_msg = message.replace('"', '`"').replace('$', '`$')
            cmd = (
                f'[reflection.assembly]::loadwithpartialname("System.Windows.Forms");'
                f'$notify = new-object system.windows.forms.notifyicon;'
                f'$notify.icon = [system.drawing.systemicons]::information;'
                f'$notify.visible = $true;'
                f'$notify.showballoontip(0, "{clean_title}", "{clean_msg}", [system.windows.forms.tooltipicon]::None);'
                f'Start-Sleep -Seconds 4; $notify.dispose()'
            )
            subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd])
        else:
            subprocess.Popen(["notify-send", title, message])
    except Exception as e:
        logger.debug("Desktop notification notice: %s", e)


class ChunkSynthesisWorker(QThread):
    """Background worker for live Gemini Flash chunk synthesis."""
    success = pyqtSignal(str, object, str, str)  # markdown, chunk_state, start_time_str, end_time_str
    failed = pyqtSignal(Exception, object, object, list)  # error, audio_data, keyframes, whiteboard_photos

    def __init__(
        self,
        pipeline: GeminiLecturePipeline,
        audio_data,
        keyframes,
        scratchpad: str,
        doc_text: Optional[str],
        prev_state: Optional[ChunkState],
        start_t: str,
        end_t: str,
        whiteboard_photos: Optional[List[Any]] = None,
    ):
        super().__init__()
        self.pipeline = pipeline
        self.audio_data = audio_data
        self.keyframes = keyframes
        self.scratchpad = scratchpad
        self.doc_text = doc_text
        self.prev_state = prev_state
        self.start_t = start_t
        self.end_t = end_t
        self.whiteboard_photos = whiteboard_photos or []

    def run(self):
        try:
            markdown, state = self.pipeline.process_live_chunk(
                stereo_audio=self.audio_data,
                keyframes=self.keyframes,
                user_scratchpad=self.scratchpad,
                reference_doc_text=self.doc_text,
                previous_chunk_state=self.prev_state,
                start_time_str=self.start_t,
                end_time_str=self.end_t,
                use_structured_output=True,
                whiteboard_photos=self.whiteboard_photos,
            )
            self.success.emit(markdown, state, self.start_t, self.end_t)
        except Exception as e:
            self.failed.emit(e, self.audio_data, self.keyframes, self.whiteboard_photos)


class MasterSynthesisWorker(QThread):
    """Background worker for Gemini Pro master synthesis."""
    success = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, pipeline: GeminiLecturePipeline, full_notes: str):
        super().__init__()
        self.pipeline = pipeline
        self.full_notes = full_notes

    def run(self):
        try:
            res = self.pipeline.synthesize_master_lecture(self.full_notes)
            self.success.emit(res)
        except Exception as e:
            self.failed.emit(str(e))


class ChalkCoordinator(QObject):
    """
    Central controller coordinating audio, vision, engine, UI, and hotkeys.
    """
    sig_toggle_recording = pyqtSignal()
    sig_force_flush = pyqtSignal()
    sig_toggle_hud = pyqtSignal()
    sig_snip_screen = pyqtSignal()
    sig_break_detected = pyqtSignal()
    sig_speech_resumed = pyqtSignal()

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.session_start_time = time.time()
        self.current_chunk_start_sec = 0.0

        # 1. Subsystems
        self.quota_manager = QuotaManager()
        self.notes_manager = SessionNotesManager()
        self.pipeline = GeminiLecturePipeline(quota_manager=self.quota_manager)

        # 2. Audio & VAD
        self.vad_detector = SileroVADDetector(
            on_break_detected=lambda: self.sig_break_detected.emit(),
            on_speech_resumed=lambda: self.sig_speech_resumed.emit(),
        )
        self.recorder = DualChannelAudioRecorder(vad_detector=self.vad_detector)

        # 3. Vision
        self.slide_filter = PerceptualSlideFilter()
        self.ax_extractor = AccessibilityTextExtractor()
        self.screen_grabber = EventGatedScreenGrabber(
            slide_filter=self.slide_filter,
            accessibility_extractor=self.ax_extractor,
            on_slide_advanced=self._on_slide_advanced,
        )

        # 4. Engine Chunker
        self.chunker = ElasticChunker(
            quota_manager=self.quota_manager,
            on_rate_limit_backoff=self._on_rate_limit_backoff,
        )

        # 5. Register Tool Context
        register_tool_context(
            recorder=self.recorder,
            screen_grabber=self.screen_grabber,
            notes_manager=self.notes_manager,
            gemini_client=self.pipeline,
        )

        # 6. UI: Floating HUD & System Tray
        self.hud = FloatingHUDWindow(
            recorder=self.recorder,
            pipeline=self.pipeline,
            quota_manager=self.quota_manager,
            notes_manager=self.notes_manager,
        )
        self.hud.request_toggle_recording.connect(self.toggle_recording)
        self.hud.request_force_flush.connect(self.force_chunk_flush)
        self.hud.request_master_synthesis.connect(self.finish_lecture_session)

        self.tray = ChalkSystemTray(
            on_toggle_recording=lambda: self.sig_toggle_recording.emit(),
            on_force_flush=lambda: self.sig_force_flush.emit(),
            on_toggle_hud=lambda: self.sig_toggle_hud.emit(),
            on_open_notes=self.open_notes_folder,
            on_open_obsidian=self.hud._open_in_obsidian,
            on_open_default_editor=self.hud._open_in_default_editor,
            on_open_settings=self.open_settings_dialog,
            on_exit=self.exit_application,
        )

        # Signal connections for thread-safe UI actions from global hotkeys
        self.sig_toggle_recording.connect(self.toggle_recording)
        self.sig_force_flush.connect(self.force_chunk_flush)
        self.sig_toggle_hud.connect(self.hud.toggle_visibility)
        self.sig_snip_screen.connect(self.hud.trigger_screen_snip)
        self.sig_break_detected.connect(self._handle_break_detected)
        self.sig_speech_resumed.connect(self._handle_speech_resumed)

        # Active background workers & fault tolerance
        self._active_chunk_worker: Optional[ChunkSynthesisWorker] = None
        self._active_master_worker: Optional[MasterSynthesisWorker] = None
        self._pending_master_synthesis = False
        self._chunk_fail_count = 0

        # Startup session crash recovery detection
        try:
            unprocessed = recover_unprocessed_sessions()
            if unprocessed:
                total_pending = sum(len(s.get("pending_segments", [])) for s in unprocessed)
                logger.info(
                    "Detected %d unfinalized session(s) with %d pending segment(s) on startup.",
                    len(unprocessed),
                    total_pending,
                )
                self.hud.chat_history.append(
                    f"<b>Session Recovery:</b> Detected {len(unprocessed)} interrupted session(s) "
                    f"with {total_pending} pending audio segment(s). Preserved in journal.\n"
                )
        except Exception as e:
            logger.debug("Error checking session recovery on startup: %s", e)

        # Boundary evaluation timer (evaluates every 2 seconds)
        self.boundary_timer = QTimer(self)
        self.boundary_timer.timeout.connect(self._evaluate_chunk_boundaries)
        self.boundary_timer.start(2000)

        # Global Hotkeys Listener
        self._init_global_hotkeys()

    def start_session(self):
        """Starts recording and monitoring session."""
        logger.info("Starting Chalk lecture session...")
        self.session_start_time = time.time()
        self.current_chunk_start_sec = 0.0

        self.recorder.start()
        self.screen_grabber.start(session_start_time=self.session_start_time)
        self.tray.start()
        self.tray.set_status("green")
        self.hud.set_daemon_status("recording")

        send_desktop_notification(tr("notify_recording_started_title"), tr("notify_recording_started_body"))

    def _init_global_hotkeys(self):

        """
        Registers system-wide hotkeys using native OS APIs (Zero Permissions).
        macOS: Carbon RegisterEventHotKey (Cmd+Shift+Space, Cmd+Shift+S, F9, F10)
        Windows: user32.RegisterHotKey (Ctrl+Shift+Space, Ctrl+Shift+S, F9, F10)
        """
        try:
            self.hotkey_manager = NativeHotkeyManager()
            if sys.platform == "darwin":
                self.hotkey_manager.register("Cmd+Shift+Space", lambda: self.sig_toggle_hud.emit())
                self.hotkey_manager.register("Cmd+Shift+S", lambda: self.sig_snip_screen.emit())
                self.hotkey_manager.register("Alt+S", lambda: self.sig_snip_screen.emit())
            else:
                self.hotkey_manager.register("Ctrl+Shift+Space", lambda: self.sig_toggle_hud.emit())
                self.hotkey_manager.register("Ctrl+Shift+S", lambda: self.sig_snip_screen.emit())
                self.hotkey_manager.register("Alt+S", lambda: self.sig_snip_screen.emit())

            self.hotkey_manager.register("F9", lambda: self.sig_toggle_recording.emit())
            self.hotkey_manager.register("F10", lambda: self.sig_force_flush.emit())
            self.hotkey_manager.start()

            hud_key = "Cmd+Shift+Space" if sys.platform == "darwin" else "Ctrl+Shift+Space"
            snip_key = "Cmd+Shift+S" if sys.platform == "darwin" else "Ctrl+Shift+S"
            logger.info(
                "Native zero-permission hotkeys registered: HUD (%s), Snip (%s / Alt+S), F9 (Toggle), F10 (Flush)",
                hud_key,
                snip_key,
            )
        except Exception as e:
            logger.warning("Could not register native global hotkeys: %s", e)

    def _on_slide_advanced(self, keyframe):
        """Notified by screen grabber when a new slide keyframe is found."""
        self.chunker.notify_slide_advanced(keyframe)

    def _evaluate_chunk_boundaries(self):
        """Periodic evaluation of dynamic elastic chunk boundaries."""
        if not self.recorder.is_recording or self.recorder.is_paused or self._active_chunk_worker:
            return

        duration_sec = self.recorder.get_active_buffer_duration_sec()
        is_pause = self.recorder.is_conversational_pause

        should_flush, reason = self.chunker.check_boundary_conditions(
            current_audio_duration_sec=duration_sec,
            is_conversational_pause=is_pause,
        )

        if should_flush:
            logger.info("Triggering chunk flush: %s", reason)
            self._dispatch_chunk_flush(trigger_reason=reason)

    def _dispatch_chunk_flush(self, trigger_reason: str = "Boundary Trigger"):
        """Packages accumulated audio & slides and fires Gemini Flash worker."""
        if self._active_chunk_worker:
            logger.warning("Chunk worker already processing. Postponing.")
            return

        audio = self.recorder.get_and_flush_active_chunk(strip_silence=True)
        keyframes = self.screen_grabber.get_and_flush_keyframes()
        whiteboard_photos = []
        if hasattr(self.hud, "pop_unprocessed_whiteboard_photos"):
            whiteboard_photos = self.hud.pop_unprocessed_whiteboard_photos()

        # If completely empty, skip
        if len(audio) == 0 and len(keyframes) == 0 and len(whiteboard_photos) == 0:
            return

        now_sec = time.time() - self.session_start_time
        start_m, start_s = int(self.current_chunk_start_sec // 60), int(self.current_chunk_start_sec % 60)
        end_m, end_s = int(now_sec // 60), int(now_sec % 60)
        start_str = f"[{start_m:02d}:{start_s:02d}]"
        end_str = f"[{end_m:02d}:{end_s:02d}]"
        self.current_chunk_start_sec = now_sec

        logger.info(
            "Dispatching chunk %s to %s (%d audio samples, %d slides, %d whiteboard photos)",
            start_str,
            end_str,
            len(audio),
            len(keyframes),
            len(whiteboard_photos),
        )

        # UI state -> Blue (Processing)
        self.tray.set_status("blue")
        self.hud.set_daemon_status("processing")

        scratchpad = self.hud.get_scratchpad_content()
        if hasattr(self.hud, "get_relevant_reference_text"):
            doc_text = self.hud.get_relevant_reference_text(query_hint=scratchpad)
        else:
            doc_text = self.hud.attached_document_text
        prev_state = self.notes_manager.last_state

        self._active_chunk_worker = ChunkSynthesisWorker(
            pipeline=self.pipeline,
            audio_data=audio,
            keyframes=keyframes,
            scratchpad=scratchpad,
            doc_text=doc_text,
            prev_state=prev_state,
            start_t=start_str,
            end_t=end_str,
            whiteboard_photos=whiteboard_photos,
        )
        self._active_chunk_worker.success.connect(self._on_chunk_success)
        self._active_chunk_worker.failed.connect(self._on_chunk_failed)
        self._active_chunk_worker.finished.connect(self._active_chunk_worker.deleteLater)
        self._active_chunk_worker.start()

    def _on_chunk_success(self, markdown_text: str, new_state: ChunkState, start_t: str, end_t: str):
        self._active_chunk_worker = None
        self._chunk_fail_count = 0
        self.chunker.mark_chunk_flushed()

        # Append to notes file
        self.notes_manager.append_chunk_notes(markdown_text, start_t, end_t)

        # Notify UI
        self.hud.chat_history.append(
            f"<b>[SYNC] Chunk Synthesized {start_t}–{end_t}:</b> {html.escape(new_state.topic)}\n"
        )

        # Restore status
        if self.recorder.is_paused:
            self.tray.set_status("yellow")
            self.hud.set_daemon_status("paused")
        else:
            self.tray.set_status("green")
            self.hud.set_daemon_status("recording")

        if getattr(self, "_pending_master_synthesis", False):
            self._trigger_master_synthesis_flow()

    def _on_chunk_failed(self, error: Exception, audio_data, keyframes, whiteboard_photos=None):
        self._active_chunk_worker = None
        err_msg = str(error)
        logger.error("Chunk synthesis encountered error: %s", err_msg)

        # 1. Authentication / Permission errors (401, 403, API_KEY_INVALID)
        if any(term in err_msg for term in ("401", "403", "API_KEY_INVALID", "INVALID_ARGUMENT", "PERMISSION_DENIED")):
            logger.critical("Authentication / API Key error: %s. Halting chunk retries.", err_msg)
            self.recorder.pause()
            self.tray.set_status("yellow")
            self.hud.set_daemon_status("paused", "API Key Invalid")
            send_desktop_notification("Chalk: Authentication Error", "API key invalid or expired. Check Settings.")
            return

        # 2. HTTP 429 Rate Limits
        if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
            logger.warning("HTTP 429 detected. Initiating 5-minute backoff.")
            self.chunker.handle_rate_limit_429(backoff_seconds=300)
            self.tray.set_status("yellow")
            self.hud.set_daemon_status("paused", "429 Rate Limit Backoff")
            self.recorder.reinsert_unprocessed_chunk(audio_data)
            self.screen_grabber.reinsert_unprocessed_keyframes(keyframes)
            send_desktop_notification(tr("notify_rate_limit_title"), tr("notify_rate_limit_body"))
            return

        # 3. Consecutive failure tracking & quarantine
        self._chunk_fail_count = getattr(self, "_chunk_fail_count", 0) + 1
        if self._chunk_fail_count > 5:
            logger.warning("Chunk exceeded 5 retries. Quarantining audio & slides to prevent data loss.")
            self._quarantine_chunk(audio_data, keyframes, whiteboard_photos, err_msg)
            self._chunk_fail_count = 0
            if getattr(self, "_pending_master_synthesis", False):
                self._trigger_master_synthesis_flow()
            return

        # Exponential backoff retry staging
        backoff_sec = min(30, 2 ** self._chunk_fail_count)
        logger.info("Reinserting chunk for retry (%d/5) with %ds backoff.", self._chunk_fail_count, backoff_sec)
        self.recorder.reinsert_unprocessed_chunk(audio_data)
        self.screen_grabber.reinsert_unprocessed_keyframes(keyframes)
        if whiteboard_photos and hasattr(self.hud, "whiteboard_photos"):
            self.hud.whiteboard_photos.extend(whiteboard_photos)
            if hasattr(self.hud, "_update_attachment_banner"):
                self.hud._update_attachment_banner()

        self.tray.set_status("yellow")
        self.hud.set_daemon_status("paused", f"Retry {self._chunk_fail_count}/5 ({backoff_sec}s)")

    def _quarantine_chunk(self, audio_data, keyframes, whiteboard_photos, error_reason: str):
        """Saves failing chunk to ~/.chalk/quarantine/ so no lecture data is ever lost."""
        try:
            quarantine_dir = os.path.expanduser(f"~/.chalk/quarantine/chunk_{int(time.time())}")
            os.makedirs(quarantine_dir, exist_ok=True)
            meta = {
                "timestamp": time.time(),
                "error": error_reason,
                "keyframes_count": len(keyframes) if keyframes else 0,
                "audio_samples": len(audio_data) if audio_data is not None else 0,
            }
            with open(os.path.join(quarantine_dir, "metadata.json"), "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2)

            if audio_data is not None and len(audio_data) > 0:
                from src.audio.capture import audio_to_wav_bytes
                wav_b = audio_to_wav_bytes(audio_data, sample_rate=16000)
                with open(os.path.join(quarantine_dir, "audio.wav"), "wb") as f:
                    f.write(wav_b)

            send_desktop_notification(
                "Chalk: Chunk Quarantined",
                "Persistent error during synthesis. Data safely saved to ~/.chalk/quarantine/."
            )
        except Exception as qe:
            logger.error("Failed to quarantine chunk: %s", qe)

    def _handle_break_detected(self):
        """Autonomous Break Detection: >180s silence."""
        logger.info("Autonomous Break Detected. Flushing active chunk and switching to Standby.")
        self._dispatch_chunk_flush(trigger_reason="Break Detected (>180s silence)")
        self.recorder.pause()
        self.tray.set_status("yellow")
        self.hud.set_daemon_status("standby", "Lecture Break")
        send_desktop_notification(tr("notify_break_detected_title"), tr("notify_break_detected_body"))

    def _handle_speech_resumed(self):
        """Speech resumed after break."""
        logger.info("Speech resumed after break. Reactivating recording.")
        self.recorder.resume()
        self.tray.set_status("green")
        self.hud.set_daemon_status("recording")
        send_desktop_notification(tr("notify_speech_resumed_title"), tr("notify_speech_resumed_body"))

    def _on_rate_limit_backoff(self, seconds: int):
        self.tray.set_status("yellow")
        self.hud.set_daemon_status("paused", f"429 Backoff ({seconds}s)")

    def toggle_recording(self):
        """Toggle recording state (F9)."""
        if self.recorder.is_recording:
            if self.recorder.is_paused:
                self.recorder.resume()
                self.tray.set_status("green")
                self.hud.set_daemon_status("recording")
                send_desktop_notification(tr("notify_recording_resumed_title"), tr("notify_recording_resumed_body"))
            else:
                self.recorder.pause()
                self.tray.set_status("yellow")
                self.hud.set_daemon_status("paused")
                send_desktop_notification(tr("notify_recording_paused_title"), tr("notify_recording_paused_body"))
        else:
            self.start_session()

    def force_chunk_flush(self):
        """Forces immediate chunk synthesis (F10)."""
        logger.info("Manual chunk flush requested (F10).")
        self._dispatch_chunk_flush(trigger_reason="Manual Force Flush (F10)")

    def finish_lecture_session(self):
        """Ends the lecture session and launches Gemini Pro Master Synthesis."""
        logger.info("Finishing lecture session. Triggering Master Synthesis...")
        if self.recorder.is_recording:
            self.recorder.stop()
        self.screen_grabber.stop()
        self.tray.set_status("blue")
        self.hud.set_daemon_status("processing", "Master Synthesis")

        # Flush any remaining audio/slides first
        rem_audio = self.recorder.get_and_flush_active_chunk(strip_silence=False)
        rem_slides = self.screen_grabber.get_and_flush_keyframes()
        whiteboard_photos = []
        if hasattr(self.hud, "pop_unprocessed_whiteboard_photos"):
            whiteboard_photos = self.hud.pop_unprocessed_whiteboard_photos()

        self._pending_master_synthesis = True

        if len(rem_audio) > 0 or len(rem_slides) > 0 or len(whiteboard_photos) > 0:
            logger.info("Dispatching final residual chunk before master synthesis...")
            self._dispatch_chunk_flush(trigger_reason="Final Lecture Flush")
        elif self._active_chunk_worker is None:
            self._trigger_master_synthesis_flow()
        else:
            logger.info("Awaiting active chunk worker completion before master synthesis...")

    def _trigger_master_synthesis_flow(self):
        """Finalizes journal and triggers Master Synthesis Worker once all chunks are complete."""
        self._pending_master_synthesis = False
        if self.recorder.journal:
            try:
                self.recorder.journal.mark_completed()
            except Exception as e:
                logger.error("Failed to mark journal completed: %s", e)

        full_notes = self.notes_manager.read_full_notes()
        send_desktop_notification(tr("notify_master_complete_title"), tr("status_processing"))

        self._active_master_worker = MasterSynthesisWorker(self.pipeline, full_notes)
        self._active_master_worker.success.connect(self._on_master_success)
        self._active_master_worker.failed.connect(self._on_master_failed)
        self._active_master_worker.finished.connect(self._active_master_worker.deleteLater)
        self._active_master_worker.start()

    def _on_master_success(self, master_markdown: str):
        self._active_master_worker = None
        self.notes_manager.append_master_synthesis(master_markdown)
        self.tray.set_status("green")
        self.hud.set_daemon_status("standby", "Session Completed")

        self.hud.chat_history.append(
            "<b>Master Synthesis Completed.</b>\n"
            "Anki Cloze study deck, standardized formula derivations, and exam warnings generated.\n"
        )
        self.hud.show_socratic_debrief(master_markdown)
        send_desktop_notification(tr("notify_master_complete_title"), tr("notify_master_complete_body"))
        self.open_notes_folder()

    def _on_master_failed(self, error_msg: str):
        self._active_master_worker = None
        self.tray.set_status("yellow")
        self.hud.set_daemon_status("standby", "Synthesis Error")
        logger.error("Master synthesis failed: %s", error_msg)
        self.hud.chat_history.append(f"<b>Master synthesis error:</b> {error_msg}")

    def open_notes_folder(self):
        notes_dir = self.notes_manager.notes_dir
        if sys.platform == "darwin":
            subprocess.Popen(["open", notes_dir])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", notes_dir])
        else:
            subprocess.Popen(["xdg-open", notes_dir])

    def _on_language_changed(self, new_lang: str):
        logger.info("Language changed event received in coordinator: %s", new_lang)
        if hasattr(self, "hud") and self.hud:
            self.hud.retranslate_ui()
        if hasattr(self, "tray") and self.tray:
            self.tray.retranslate_menu()

    def open_settings_dialog(self):
        dialog = SettingsDialog(parent=self.hud, is_initial_setup=False)
        dialog.language_changed.connect(self._on_language_changed)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.pipeline.reload_key()
            logger.info("API key reloaded in pipeline from settings modal.")


    def handle_audio_url(self, url: str):
        """Dispatches audio scrubbing URL to floating HUD."""
        logger.info("Coordinator received audio URL: %s", url)
        if not self.hud.isVisible():
            self.hud.show()
        self.hud.raise_()
        self.hud.activateWindow()
        self.hud.open_audio_url(url)

    def exit_application(self):
        logger.info("Shutting down Chalk daemon...")
        if hasattr(self, "hotkey_manager") and self.hotkey_manager:
            try:
                self.hotkey_manager.stop()
            except Exception as e:
                logger.debug("Error stopping hotkey manager: %s", e)
        self.recorder.stop()
        self.screen_grabber.stop()
        self.tray.stop()
        self.app.quit()


def main():
    app = ChalkApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # Keep running in system tray

    # Step 1: Ensure BYOK API Key is configured in OS native vault
    if not ensure_api_key_configured():
        logger.warning("No API key configured. Exiting.")
        sys.exit(0)

    # Step 2: Initialize Chalk Coordinator & Lifecycle
    coordinator = ChalkCoordinator(app)
    app.url_opened.connect(coordinator.handle_audio_url)

    # Check CLI arguments for chalk-audio:// URL
    has_audio_url = False
    for arg in sys.argv[1:]:
        if arg.startswith("chalk-audio://"):
            has_audio_url = True
            QTimer.singleShot(400, lambda u=arg: coordinator.handle_audio_url(u))
            break

    if has_audio_url:
        logger.info("Launched with chalk-audio:// URL. Running in playback-only mode.")
    else:
        # Start in standby mode: Tray and HUD are active, recording triggers via F9 or click
        logger.info("Chalk daemon initialized in Standby mode. Press F9 or Tray icon to start recording.")
        coordinator.tray.start()
        coordinator.tray.set_status("yellow")
        coordinator.hud.set_daemon_status("standby", "Ready (Press F9)")

    # Step 3: Run Qt Event Loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

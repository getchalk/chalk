"""
src/ui/tray.py - System Tray Daemon with Dynamic Status Dot.
- Green: Actively recording (Mic + System Loopback + Screen)
- Yellow: Paused (Break detected via Silero VAD or manual pause)
- Blue: Processing chunk via Gemini API worker
Context menu: Toggle Recording (F9), Force Chunk Flush (F10), Show HUD (Alt+Space),
In Obsidian öffnen, Im Standard-Editor öffnen, Notizen-Ordner öffnen, Einstellungen, Beenden.
"""

import os
import sys
import subprocess
import threading
import logging
from typing import Optional, Callable
from PIL import Image, ImageDraw
import pystray

from src.ui.i18n import tr, get_ui_language

logger = logging.getLogger("chalk.ui.tray")


def create_tray_status_icon(color: str = "green", size: int = 64) -> Image.Image:
    """
    Generates the literal chalk stick on slate emblem with dynamic status pip:
    - Green: Actively recording (Mic + System Loopback + Slides)
    - Yellow: Paused / Standby (Break detected via Silero VAD or manual standby)
    - Blue: Processing chunk / Master synthesis via Gemini
    """
    try:
        from assets.generate_icon import render_tray_icon_base
        return render_tray_icon_base(size=size, status_color=color)
    except Exception as e:
        logger.debug("Tray icon fallback rendering: %s", e)
        # Fallback in-memory generator
        img = Image.new("RGBA", (size, size), (7, 8, 11, 255))
        draw = ImageDraw.Draw(img)
        palette = {
            "green": (34, 197, 94, 255),
            "yellow": (245, 158, 11, 255),
            "blue": (59, 130, 246, 255),
        }
        fill_col = palette.get(color.lower(), palette["green"])
        # Centered chalk mark
        draw.line([(size * 0.3, size * 0.7), (size * 0.7, size * 0.3)], fill=(248, 250, 252, 255), width=max(2, size // 8))
        # Status pip
        draw.ellipse([size - 8, 2, size - 2, 8], fill=fill_col)
        return img


class ChalkSystemTray:
    """
    Manages the background system tray daemon and context menu.
    """

    def __init__(
        self,
        on_toggle_recording: Optional[Callable[[], None]] = None,
        on_force_flush: Optional[Callable[[], None]] = None,
        on_toggle_hud: Optional[Callable[[], None]] = None,
        on_open_notes: Optional[Callable[[], None]] = None,
        on_open_obsidian: Optional[Callable[[], None]] = None,
        on_open_default_editor: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ):
        self.on_toggle_recording = on_toggle_recording
        self.on_force_flush = on_force_flush
        self.on_toggle_hud = on_toggle_hud
        self.on_open_notes = on_open_notes
        self.on_open_obsidian = on_open_obsidian
        self.on_open_default_editor = on_open_default_editor
        self.on_open_settings = on_open_settings
        self.on_exit = on_exit

        self.current_state = "green"
        self._icon: Optional[pystray.Icon] = None

    def _build_menu(self) -> pystray.Menu:
        """Constructs the context menu dynamically using current i18n translations."""
        return pystray.Menu(
            pystray.MenuItem(tr("tray_toggle_recording"), self._action_toggle_recording),
            pystray.MenuItem(tr("tray_force_flush"), self._action_force_flush),
            pystray.MenuItem(tr("tray_toggle_hud"), self._action_toggle_hud),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("tray_open_obsidian"), self._action_open_obsidian),
            pystray.MenuItem(tr("tray_open_default_editor"), self._action_open_default_editor),
            pystray.MenuItem(tr("tray_open_notes"), self._action_open_notes),
            pystray.MenuItem(tr("tray_settings"), self._action_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(tr("tray_exit"), self._action_exit),
        )

    def retranslate_menu(self):
        """Dynamically refreshes the context menu upon language change."""
        if self._icon:
            try:
                self._icon.menu = self._build_menu()
                if hasattr(self._icon, "update_menu"):
                    self._icon.update_menu()
            except Exception as e:
                logger.debug("Tray menu retranslation notice: %s", e)

    def start(self):
        """Builds and launches the system tray icon detached."""
        menu = self._build_menu()
        initial_img = create_tray_status_icon(self.current_state)
        self._icon = pystray.Icon(
            name="Chalk",
            icon=initial_img,
            title="Chalk — Autonomous Desktop Lecture Engine",
            menu=menu,
        )

        # Run detached in background thread
        self._icon.run_detached()
        logger.info("Chalk system tray daemon active.")

    def set_status(self, state: str):
        """
        Updates the tray icon color:
        'green' / 'recording' -> [REC] (green status dot)
        'yellow' / 'paused' / 'standby' -> [PAUSE] (yellow status dot)
        'blue' / 'processing' -> [PROC] (blue status dot)
        """
        color_map = {
            "green": "green",
            "recording": "green",
            "yellow": "yellow",
            "paused": "yellow",
            "standby": "yellow",
            "blue": "blue",
            "processing": "blue",
        }
        color = color_map.get(state.lower(), "green")
        self.current_state = color

        if self._icon:
            self._icon.icon = create_tray_status_icon(color)
            if color == "green":
                self._icon.title = f"Chalk: {tr('notify_recording_started_title')}"
            elif color == "yellow":
                self._icon.title = f"Chalk: {tr('status_standby')}"
            elif color == "blue":
                self._icon.title = f"Chalk: {tr('status_processing')}"


    def stop(self):
        """Stops the tray icon."""
        if self._icon:
            self._icon.stop()
            self._icon = None

    # Context menu action dispatches
    def _action_toggle_recording(self, icon, item):
        if self.on_toggle_recording:
            self.on_toggle_recording()

    def _action_force_flush(self, icon, item):
        if self.on_force_flush:
            self.on_force_flush()

    def _action_toggle_hud(self, icon, item):
        if self.on_toggle_hud:
            self.on_toggle_hud()

    def _action_open_obsidian(self, icon, item):
        if self.on_open_obsidian:
            self.on_open_obsidian()

    def _action_open_default_editor(self, icon, item):
        if self.on_open_default_editor:
            self.on_open_default_editor()

    def _action_open_notes(self, icon, item):
        if self.on_open_notes:
            self.on_open_notes()
        else:
            notes_dir = os.path.abspath("Notes")
            os.makedirs(notes_dir, exist_ok=True)
            if sys.platform == "darwin":
                subprocess.Popen(["open", notes_dir])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", notes_dir])
            else:
                subprocess.Popen(["xdg-open", notes_dir])

    def _action_open_settings(self, icon, item):
        if self.on_open_settings:
            self.on_open_settings()

    def _action_exit(self, icon, item):
        if self.on_exit:
            self.on_exit()
        else:
            self.stop()
            sys.exit(0)

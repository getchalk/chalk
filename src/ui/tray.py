"""
src/ui/tray.py - System Tray Daemon with Dynamic Status Dot.
Uses pystray to run a background system tray icon with colored status dots:
🟢 Green: Actively recording (Mic + System Loopback + Screen)
🟡 Yellow: Paused (Break detected via Silero VAD or manual pause)
🔵 Blue: Processing chunk via Gemini API worker
Context menu: Toggle Recording (F9), Force Chunk Flush (F10), Show HUD (Alt+Space),
Open Notes Folder, Settings, Exit.
"""

import os
import sys
import subprocess
import threading
import logging
from typing import Optional, Callable
from PIL import Image, ImageDraw
import pystray

logger = logging.getLogger("chalk.ui.tray")


def create_tray_status_icon(color: str = "green", size: int = 64) -> Image.Image:
    """
    Generates the crisp monochrome calcite crystal emblem with dynamic status dot:
    🟢 Green: Actively recording (Mic + System Loopback + Slides)
    🟡 Yellow: Paused / Standby (Break detected via Silero VAD or manual standby)
    🔵 Blue: Processing chunk / Master synthesis via Gemini
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
        on_open_settings: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ):
        self.on_toggle_recording = on_toggle_recording
        self.on_force_flush = on_force_flush
        self.on_toggle_hud = on_toggle_hud
        self.on_open_notes = on_open_notes
        self.on_open_settings = on_open_settings
        self.on_exit = on_exit

        self.current_state = "green"
        self._icon: Optional[pystray.Icon] = None

    def start(self):
        """Builds and launches the system tray icon detached."""
        menu = pystray.Menu(
            pystray.MenuItem("Toggle Recording (F9)", self._action_toggle_recording),
            pystray.MenuItem("Force Chunk Flush (F10)", self._action_force_flush),
            pystray.MenuItem("Show / Hide HUD (Alt+Space)", self._action_toggle_hud),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Notes Folder", self._action_open_notes),
            pystray.MenuItem("Settings (API Key)", self._action_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit Chalk", self._action_exit),
        )

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
        'green' / 'recording' -> 🟢
        'yellow' / 'paused' / 'standby' -> 🟡
        'blue' / 'processing' -> 🔵
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
                self._icon.title = "Chalk: Recording (Mic + Loopback + Slides)"
            elif color == "yellow":
                self._icon.title = "Chalk: Standby / Paused"
            elif color == "blue":
                self._icon.title = "Chalk: Processing chunk via Gemini"

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

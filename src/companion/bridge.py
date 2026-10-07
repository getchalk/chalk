"""
src/companion/bridge.py - Thread-Safe Signal Bridge between HTTP Server & PyQt6 HUD.

Allows the background HTTP daemon thread to safely dispatch incoming smartphone uploads
and status events to the PyQt6 main event loop without GUI thread race conditions.
"""

import logging
from typing import Optional, Callable

logger = logging.getLogger("chalk.companion.bridge")

try:
    from PyQt6.QtCore import QObject, pyqtSignal
    PYQT_AVAILABLE = True
except ImportError:
    PYQT_AVAILABLE = False
    # Fallback dummy QObject for headless CLI or testing
    class QObject:  # type: ignore
        pass

    class _DummySignal:
        def __init__(self):
            self._callbacks = []

        def connect(self, slot: Callable):
            self._callbacks.append(slot)

        def emit(self, *args, **kwargs):
            for cb in self._callbacks:
                try:
                    cb(*args, **kwargs)
                except Exception as e:
                    logger.error("Error invoking dummy signal callback: %s", e)

    def pyqtSignal(*args, **kwargs):  # type: ignore
        return _DummySignal()


class CompanionBridge(QObject):
    """
    Thread-safe event dispatcher for the Whiteboard Camera companion server.
    Emits signals that are safely queued to the PyQt6 main thread.
    """
    if PYQT_AVAILABLE:
        # Signals: (image_path, timestamp_str)
        photo_received = pyqtSignal(str, str)
        # Signals: (client_ip)
        client_connected = pyqtSignal(str)
        # Signals: (status_text)
        status_message = pyqtSignal(str)
    else:
        photo_received = _DummySignal()
        client_connected = _DummySignal()
        status_message = _DummySignal()

    def __init__(self, parent: Optional[QObject] = None):
        if PYQT_AVAILABLE:
            super().__init__(parent)
        self._upload_count = 0
        self._photo_callbacks = []

    def add_photo_callback(self, cb: Callable[[str, str], None]):
        """Registers a direct Python callback (useful for testing or non-Qt workflows)."""
        self._photo_callbacks.append(cb)

    def notify_photo_received(self, image_path: str, timestamp_str: str):
        """Dispatches an incoming whiteboard photo to the GUI main thread."""
        self._upload_count += 1
        logger.info("CompanionBridge: Photo #%d received -> %s at %s", self._upload_count, image_path, timestamp_str)
        self.photo_received.emit(image_path, timestamp_str)
        for cb in self._photo_callbacks:
            try:
                cb(image_path, timestamp_str)
            except Exception as e:
                logger.error("Error in photo callback: %s", e)

    def notify_client_connected(self, client_ip: str):
        """Notifies GUI that a phone browser opened the companion page."""
        logger.info("CompanionBridge: Phone connected from %s", client_ip)
        self.client_connected.emit(client_ip)

    def notify_status(self, text: str):
        """Dispatches status text update to GUI."""
        self.status_message.emit(text)

    @property
    def upload_count(self) -> int:
        return self._upload_count

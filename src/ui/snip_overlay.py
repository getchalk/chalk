"""
src/ui/snip_overlay.py - Draggable Screen Snip Marquee Tool (Alt+S).
Freezes the display with a translucent dark scrim, allows dragging a marquee crop box,
captures the exact bounded rectangle, and attaches the snippet to the Copilot HUD prompt.
"""

from typing import Optional
from PIL import Image
from PyQt6.QtCore import Qt, QRect, QPoint, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPixmap, QImage, QFont
from PyQt6.QtWidgets import QWidget, QApplication

from src.vision.screen_grabber import EventGatedScreenGrabber


class SnipOverlayWidget(QWidget):
    """
    Fullscreen translucent overlay for dragging a crop marquee box.
    """
    snip_captured = pyqtSignal(object)  # Emits PIL.Image
    snip_cancelled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setCursor(Qt.CursorShape.CrossCursor)

        self.start_point: Optional[QPoint] = None
        self.end_point: Optional[QPoint] = None
        self.is_selecting = False
        self.captured_pixmap: Optional[QPixmap] = None

    def start_snip(self):
        """Freezes screen and opens overlay with Retina/DPI awareness."""
        # Grab master high-res screen
        self._source_pil_img = EventGatedScreenGrabber.capture_screenshot()
        rgb_data = self._source_pil_img.convert("RGBA").tobytes("raw", "RGBA")
        qimage = QImage(rgb_data, self._source_pil_img.width, self._source_pil_img.height, QImage.Format.Format_RGBA8888)
        self.captured_pixmap = QPixmap.fromImage(qimage)

        # Set geometry to cover all screens
        screens = QApplication.screens()
        total_rect = QRect()
        for s in screens:
            total_rect = total_rect.united(s.geometry())
        self.setGeometry(total_rect)

        # High-DPI scaling factors between logical points and physical pixels
        self._scale_x = self._source_pil_img.width / max(1, total_rect.width())
        self._scale_y = self._source_pil_img.height / max(1, total_rect.height())
        self.captured_pixmap.setDevicePixelRatio(self._scale_x)

        self.start_point = None
        self.end_point = None
        self.is_selecting = False
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.position().toPoint()
            self.end_point = self.start_point
            self.is_selecting = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self.cancel_snip()

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.end_point = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_selecting:
            self.is_selecting = False
            self.end_point = event.position().toPoint()
            self._finish_selection()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_snip()
        else:
            super().keyPressEvent(event)

    def cancel_snip(self):
        self.hide()
        self.snip_cancelled.emit()

    def _finish_selection(self):
        self.hide()
        if not self.start_point or not self.end_point or not hasattr(self, "_source_pil_img") or not self._source_pil_img:
            self.snip_cancelled.emit()
            return

        rect = QRect(self.start_point, self.end_point).normalized()
        if rect.width() < 10 or rect.height() < 10:
            self.snip_cancelled.emit()
            return

        # Direct physical pixel crop from source image ensures 100% sharpness on Retina/4K displays
        crop_x = int(rect.x() * self._scale_x)
        crop_y = int(rect.y() * self._scale_y)
        crop_w = int(rect.width() * self._scale_x)
        crop_h = int(rect.height() * self._scale_y)

        crop_box = (
            max(0, crop_x),
            max(0, crop_y),
            min(self._source_pil_img.width, crop_x + crop_w),
            min(self._source_pil_img.height, crop_y + crop_h),
        )
        pil_img = self._source_pil_img.crop(crop_box).convert("RGB")
        self.snip_captured.emit(pil_img)

    def paintEvent(self, event):
        painter = QPainter(self)
        if not self.captured_pixmap:
            return

        # Draw base frozen desktop
        painter.drawPixmap(0, 0, self.captured_pixmap)

        # Dark translucent overlay scrim
        painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

        # Highlight selection box if dragging
        if self.start_point and self.end_point:
            sel_rect = QRect(self.start_point, self.end_point).normalized()
            # Draw clear un-dimmed view inside box
            painter.drawPixmap(sel_rect, self.captured_pixmap, sel_rect)

            # Glow border
            pen = QPen(QColor(129, 140, 248), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(sel_rect)

            # Size indicator badge
            badge_text = f"{sel_rect.width()} × {sel_rect.height()} px"
            painter.setFont(QFont("-apple-system, sans-serif", 10))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(15, 17, 23, 220))
            badge_rect = QRect(sel_rect.left(), max(0, sel_rect.top() - 24), 110, 20)
            painter.drawRoundedRect(badge_rect, 4, 4)

            painter.setPen(QColor(243, 244, 246))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

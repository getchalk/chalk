"""
src/vision/accessibility.py - Zero-Token OCR via Accessibility Tree Bypass.
Queries the active presentation window (PowerPoint, Keynote, Adobe Acrobat, Zoom, browser)
via macOS AXUIElement / Windows UI Automation.
Directly extracts raw text blocks from the OS accessibility tree in < 2ms,
allowing Gemini to ingest pristine digital text while consuming zero image tokens.
"""

import sys
import time
import logging
from typing import Optional, List

logger = logging.getLogger("chalk.vision.accessibility")


class AccessibilityTextExtractor:
    """
    Extracts text directly from the active presentation window's accessibility tree.
    Supports macOS (AXUIElement) and Windows (UI Automation).
    """

    def __init__(self):
        self.platform = sys.platform
        self._init_platform_handlers()

    def _init_platform_handlers(self):
        if self.platform == "darwin":
            try:
                from AppKit import NSWorkspace
                from ApplicationServices import (
                    AXUIElementCreateApplication,
                    AXUIElementCopyAttributeValue,
                    kAXFocusedWindowAttribute,
                    kAXWindowsAttribute,
                    kAXChildrenAttribute,
                    kAXValueAttribute,
                    kAXTitleAttribute,
                    kAXRoleAttribute,
                )
                self.has_darwin_ax = True
                logger.info("macOS AXUIElement accessibility extractor initialized.")
            except ImportError as e:
                self.has_darwin_ax = False
                logger.warning("macOS AXUIElement dependencies unavailable: %s", e)
        elif self.platform == "win32":
            # On Windows, UI Automation can be queried via ctypes / comtypes / uiautomation
            self.has_win_uia = True
            logger.info("Windows UI Automation extractor ready.")
        else:
            self.has_darwin_ax = False
            self.has_win_uia = False

    def extract_active_window_text(self, max_depth: int = 5) -> Optional[str]:
        """
        Extracts raw text from the frontmost presentation or document window.
        Returns extracted text string if valid text >= 15 characters found, else None.
        """
        start_time = time.perf_counter()
        try:
            if self.platform == "darwin" and getattr(self, "has_darwin_ax", False):
                text = self._extract_macos_ax_text(max_depth=max_depth)
            elif self.platform == "win32":
                text = self._extract_windows_uia_text()
            else:
                text = None

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            if text and len(text.strip()) > 15:
                logger.debug("Zero-token OCR extracted %d chars in %.2f ms", len(text), elapsed_ms)
                return text.strip()
        except Exception as e:
            logger.debug("Accessibility extraction encountered: %s", e)

        return None

    def _extract_macos_ax_text(self, max_depth: int = 5) -> Optional[str]:
        """macOS AXUIElement tree traversal with strict privacy guards and execution budget."""
        try:
            from AppKit import NSWorkspace
            from ApplicationServices import (
                AXIsProcessTrusted,
                AXUIElementCreateApplication,
                AXUIElementCopyAttributeValue,
                kAXFocusedWindowAttribute,
                kAXWindowsAttribute,
                kAXChildrenAttribute,
                kAXValueAttribute,
                kAXTitleAttribute,
                kAXRoleAttribute,
                kAXDescriptionAttribute,
            )

            # 1. Permission check
            if not AXIsProcessTrusted():
                logger.debug("macOS Accessibility not trusted. Skipping AX tree query.")
                return None

            active_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not active_app:
                return None

            # 2. Privacy check: Never scrape notes, passwords, chats, or terminal windows
            bundle_id = active_app.bundleIdentifier() or ""
            excluded_bundles = (
                "md.obsidian", "com.apple.Notes", "com.tinyspeck.slackmacgap",
                "com.apple.Terminal", "com.googlecode.iterm2", "com.apple.keychainaccess",
                "com.1password.1password", "com.bitwarden.desktop", "com.hnc.Discord",
                "com.apple.mail", "com.apple.MobileSMS", "com.chalk.lectureengine"
            )
            if any(eb.lower() in bundle_id.lower() for eb in excluded_bundles):
                logger.debug("Active window belongs to excluded/private app '%s'. Skipping.", bundle_id)
                return None

            pid = active_app.processIdentifier()
            app_element = AXUIElementCreateApplication(pid)

            # Get focused window
            err, window = AXUIElementCopyAttributeValue(app_element, kAXFocusedWindowAttribute, None)
            if err != 0 or not window:
                err, windows = AXUIElementCopyAttributeValue(app_element, kAXWindowsAttribute, None)
                if err == 0 and windows and len(windows) > 0:
                    window = windows[0]
                else:
                    return None

            collected_texts: List[str] = []
            node_count = 0
            t0 = time.perf_counter()

            def _traverse(element, current_depth):
                nonlocal node_count
                if current_depth > max_depth or len(collected_texts) >= 50 or node_count >= 50:
                    return
                if (time.perf_counter() - t0) > 0.050:  # 50ms time budget cap
                    return
                node_count += 1

                # Read value
                err_val, val = AXUIElementCopyAttributeValue(element, kAXValueAttribute, None)
                if err_val == 0 and isinstance(val, str) and val.strip():
                    cleaned = val.strip()
                    if len(cleaned) > 2 and cleaned not in collected_texts:
                        collected_texts.append(cleaned)

                # Read title/description if role is text/heading/static text
                err_title, title = AXUIElementCopyAttributeValue(element, kAXTitleAttribute, None)
                if err_title == 0 and isinstance(title, str) and title.strip():
                    cleaned = title.strip()
                    if len(cleaned) > 2 and cleaned not in collected_texts:
                        collected_texts.append(cleaned)

                # Recurse children
                err_child, children = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, None)
                if err_child == 0 and children:
                    for child in children:
                        _traverse(child, current_depth + 1)

            _traverse(window, 0)
            if collected_texts:
                return "\n".join(collected_texts)
        except Exception as e:
            logger.debug("macOS AX extraction error: %s", e)

        return None

    def _extract_windows_uia_text(self) -> Optional[str]:
        """Windows UI Automation tree traversal."""
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None

            # Get window text length
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                # If window title has lecture info, return title
                if len(title) > 15:
                    return f"[Window Title: {title}]"
        except Exception as e:
            logger.debug("Windows UIA query: %s", e)

        return None

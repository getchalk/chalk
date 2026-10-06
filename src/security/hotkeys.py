"""
src/security/hotkeys.py - Native OS Global Hotkey Manager.

Provides native global hotkey registration across macOS and Windows with
ZERO Keylogger / Input-Monitoring permissions:
- macOS: Uses Carbon RegisterEventHotKey via ctypes.
  Standard macOS API that operates directly at the WindowServer event router level.
  Requires ZERO Input Monitoring and ZERO Accessibility permissions.
- Windows: Uses user32.RegisterHotKey via ctypes.
  Standard Win32 API that dispatches WM_HOTKEY to a dedicated message thread.
  Requires ZERO elevated permissions.
- Fallback: Graceful headless / Qt-native event filter for automated tests and CI.
"""

import sys
import ctypes
import threading
import logging
from typing import Callable, Dict, Optional, Tuple, List

logger = logging.getLogger("chalk.security.hotkeys")


# ==============================================================================
# macOS Carbon Hotkey Implementation (Zero Permissions)
# ==============================================================================

class _MacCarbonHotkeyBackend:
    """
    Native macOS global hotkey listener using Carbon Event Manager via ctypes.
    Requires ZERO Accessibility and ZERO Input Monitoring permissions.
    """

    # Carbon constants
    kEventClassKeyboard = int.from_bytes(b"kbd ", byteorder="big")
    kEventHotKeyPressed = 5
    kEventParamDirectObject = int.from_bytes(b"----", byteorder="big")
    typeEventHotKeyID = int.from_bytes(b"hkid", byteorder="big")

    # Modifiers
    MOD_CMD = 0x0100
    MOD_SHIFT = 0x0200
    MOD_OPT = 0x0800
    MOD_CTRL = 0x1000

    # Virtual Keycodes (macOS Hardware Keycodes)
    KEY_CODES = {
        "space": 49,
        "s": 1,
        "a": 0,
        "d": 2,
        "f": 3,
        "h": 4,
        "g": 5,
        "z": 6,
        "x": 7,
        "c": 8,
        "v": 9,
        "b": 11,
        "q": 12,
        "w": 13,
        "e": 14,
        "r": 15,
        "y": 16,
        "t": 17,
        "1": 18,
        "2": 19,
        "3": 20,
        "4": 21,
        "6": 22,
        "5": 23,
        "equal": 24,
        "9": 25,
        "7": 26,
        "minus": 27,
        "8": 28,
        "0": 29,
        "o": 31,
        "u": 32,
        "i": 34,
        "p": 35,
        "l": 37,
        "j": 38,
        "k": 40,
        "n": 45,
        "m": 46,
        "return": 36,
        "enter": 36,
        "tab": 48,
        "escape": 53,
        "esc": 53,
        "f1": 122,
        "f2": 120,
        "f3": 99,
        "f4": 118,
        "f5": 96,
        "f6": 97,
        "f7": 98,
        "f8": 100,
        "f9": 101,
        "f10": 109,
        "f11": 103,
        "f12": 111,
    }

    class EventTypeSpec(ctypes.Structure):
        _fields_ = [
            ("eventClass", ctypes.c_uint32),
            ("eventKind", ctypes.c_uint32),
        ]

    class EventHotKeyID(ctypes.Structure):
        _fields_ = [
            ("signature", ctypes.c_uint32),
            ("id", ctypes.c_uint32),
        ]

    EventHandlerProc = ctypes.CFUNCTYPE(
        ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )

    def __init__(self):
        self._carbon = None
        self._handler_ref = ctypes.c_void_p()
        self._c_handler = None  # Crucial: retain reference to prevent GC
        self._registered_refs: Dict[int, ctypes.c_void_p] = {}
        self._callbacks: Dict[int, Callable[[], None]] = {}
        self._next_id = 1
        self._signature = int.from_bytes(b"CHLK", byteorder="big")
        self._is_active = False

        self._init_carbon()

    def _init_carbon(self):
        try:
            self._carbon = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/Carbon.framework/Carbon"
            )

            self._carbon.GetEventDispatcherTarget.restype = ctypes.c_void_p
            self._carbon.GetApplicationEventTarget.restype = ctypes.c_void_p

            self._carbon.InstallEventHandler.restype = ctypes.c_int32
            self._carbon.InstallEventHandler.argtypes = [
                ctypes.c_void_p,
                self.EventHandlerProc,
                ctypes.c_uint32,
                ctypes.POINTER(self.EventTypeSpec),
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]

            self._carbon.RegisterEventHotKey.restype = ctypes.c_int32
            self._carbon.RegisterEventHotKey.argtypes = [
                ctypes.c_uint32,
                ctypes.c_uint32,
                self.EventHotKeyID,
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ]

            self._carbon.UnregisterEventHotKey.restype = ctypes.c_int32
            self._carbon.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]

            self._carbon.RemoveEventHandler.restype = ctypes.c_int32
            self._carbon.RemoveEventHandler.argtypes = [ctypes.c_void_p]

            self._carbon.GetEventParameter.restype = ctypes.c_int32
            self._carbon.GetEventParameter.argtypes = [
                ctypes.c_void_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_uint32),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
                ctypes.c_void_p,
            ]
        except Exception as e:
            logger.error("Failed loading Carbon framework: %s", e)
            self._carbon = None

    def _event_handler_callback(self, next_handler, the_event, user_data):
        hk_id = self.EventHotKeyID()
        status = self._carbon.GetEventParameter(
            the_event,
            self.kEventParamDirectObject,
            self.typeEventHotKeyID,
            None,
            ctypes.sizeof(hk_id),
            None,
            ctypes.byref(hk_id),
        )
        if status == 0 and hk_id.id in self._callbacks:
            callback = self._callbacks[hk_id.id]
            try:
                callback()
            except Exception as e:
                logger.error("Error executing hotkey callback (ID %d): %s", hk_id.id, e)
        return 0

    def parse_hotkey(self, shortcut: str) -> Tuple[int, int]:
        """Parses shortcut string into (keycode, modifiers)."""
        tokens = [t.strip().strip("<>").lower() for t in shortcut.split("+")]
        modifiers = 0
        keycode = None

        for token in tokens:
            if token in ("cmd", "command"):
                modifiers |= self.MOD_CMD
            elif token == "shift":
                modifiers |= self.MOD_SHIFT
            elif token in ("alt", "opt", "option"):
                modifiers |= self.MOD_OPT
            elif token in ("ctrl", "control"):
                modifiers |= self.MOD_CTRL
            elif token in self.KEY_CODES:
                keycode = self.KEY_CODES[token]
            elif len(token) == 1 and token.isalnum():
                keycode = self.KEY_CODES.get(token)

        if keycode is None:
            raise ValueError(f"Could not resolve keycode for hotkey: '{shortcut}'")

        return keycode, modifiers

    def register(self, shortcut: str, callback: Callable[[], None]) -> int:
        if not self._carbon:
            raise RuntimeError("Carbon framework unavailable.")

        keycode, modifiers = self.parse_hotkey(shortcut)
        hotkey_id = self._next_id
        self._next_id += 1
        self._callbacks[hotkey_id] = callback

        # If already started, register immediately
        if self._is_active:
            self._register_carbon_hotkey(hotkey_id, keycode, modifiers)
        else:
            # Store pending registration
            self._registered_refs[hotkey_id] = (keycode, modifiers)

        return hotkey_id

    def _register_carbon_hotkey(self, hotkey_id: int, keycode: int, modifiers: int):
        target = self._carbon.GetEventDispatcherTarget()
        hk_id_struct = self.EventHotKeyID(self._signature, hotkey_id)
        ref = ctypes.c_void_p()
        err = self._carbon.RegisterEventHotKey(
            keycode,
            modifiers,
            hk_id_struct,
            target,
            0,
            ctypes.byref(ref),
        )
        if err != 0:
            logger.warning("RegisterEventHotKey failed with error code: %d", err)
        else:
            self._registered_refs[hotkey_id] = ref
            logger.debug("Registered Carbon hotkey ID %d (code=%d, mods=%d)", hotkey_id, keycode, modifiers)

    def start(self):
        if self._is_active or not self._carbon:
            return

        self._c_handler = self.EventHandlerProc(self._event_handler_callback)
        target = self._carbon.GetEventDispatcherTarget()
        event_type = self.EventTypeSpec(self.kEventClassKeyboard, self.kEventHotKeyPressed)

        status = self._carbon.InstallEventHandler(
            target,
            self._c_handler,
            1,
            ctypes.byref(event_type),
            None,
            ctypes.byref(self._handler_ref),
        )
        if status != 0:
            logger.error("InstallEventHandler failed with code %d", status)
            return

        self._is_active = True

        # Register all queued hotkeys
        pending = list(self._registered_refs.items())
        for hid, val in pending:
            if isinstance(val, tuple):
                keycode, modifiers = val
                self._register_carbon_hotkey(hid, keycode, modifiers)

    def stop(self):
        if not self._is_active:
            return

        for hid, ref in list(self._registered_refs.items()):
            if isinstance(ref, ctypes.c_void_p) and ref.value:
                try:
                    self._carbon.UnregisterEventHotKey(ref)
                except Exception:
                    pass

        self._registered_refs.clear()

        if self._handler_ref.value:
            try:
                self._carbon.RemoveEventHandler(self._handler_ref)
            except Exception:
                pass
            self._handler_ref = ctypes.c_void_p()

        self._is_active = False


# ==============================================================================
# Windows user32.RegisterHotKey Implementation (Zero Permissions)
# ==============================================================================

class _WindowsHotkeyBackend:
    """
    Native Windows global hotkey listener using user32.RegisterHotKey via ctypes.
    Runs a lightweight message loop thread. Requires ZERO special permissions.
    """

    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    VK_CODES = {
        "space": 0x20,
        "s": 0x53,
        "a": 0x41,
        "d": 0x44,
        "f": 0x46,
        "c": 0x43,
        "v": 0x56,
        "f1": 0x70,
        "f2": 0x71,
        "f3": 0x72,
        "f4": 0x73,
        "f5": 0x74,
        "f6": 0x75,
        "f7": 0x76,
        "f8": 0x77,
        "f9": 0x78,
        "f10": 0x79,
        "f11": 0x7A,
        "f12": 0x7B,
    }

    def __init__(self):
        self._hotkeys: Dict[int, Tuple[int, int, Callable[[], None]]] = {}
        self._next_id = 1
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._stop_event = threading.Event()
        self._is_active = False

    def parse_hotkey(self, shortcut: str) -> Tuple[int, int]:
        tokens = [t.strip().strip("<>").lower() for t in shortcut.split("+")]
        modifiers = self.MOD_NOREPEAT
        vk = None

        for token in tokens:
            if token in ("ctrl", "control"):
                modifiers |= self.MOD_CONTROL
            elif token == "shift":
                modifiers |= self.MOD_SHIFT
            elif token in ("alt", "opt", "option"):
                modifiers |= self.MOD_ALT
            elif token in ("win", "windows", "cmd"):
                modifiers |= self.MOD_WIN
            elif token in self.VK_CODES:
                vk = self.VK_CODES[token]
            elif len(token) == 1 and token.isalnum():
                vk = ord(token.upper())

        if vk is None:
            raise ValueError(f"Could not resolve virtual key for hotkey: '{shortcut}'")

        return vk, modifiers

    def register(self, shortcut: str, callback: Callable[[], None]) -> int:
        vk, modifiers = self.parse_hotkey(shortcut)
        hid = self._next_id
        self._next_id += 1
        self._hotkeys[hid] = (vk, modifiers, callback)
        return hid

    def start(self):
        if self._is_active:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._msg_loop,
            daemon=True,
            name="ChalkWindowsHotkeyListener",
        )
        self._thread.start()
        self._is_active = True

    def _msg_loop(self):
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()

            registered_ids = []
            for hid, (vk, mods, _) in self._hotkeys.items():
                if user32.RegisterHotKey(None, hid, mods, vk):
                    registered_ids.append(hid)
                else:
                    logger.warning("Failed to register Windows hotkey %d", hid)

            msg = wintypes.MSG()
            while not self._stop_event.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == 0x0312:  # WM_HOTKEY
                    hid = msg.wParam
                    if hid in self._hotkeys:
                        _, _, cb = self._hotkeys[hid]
                        try:
                            cb()
                        except Exception as e:
                            logger.error("Error in Windows hotkey callback %d: %s", hid, e)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            for hid in registered_ids:
                user32.UnregisterHotKey(None, hid)
        except Exception as e:
            logger.error("Windows hotkey message loop terminated with error: %s", e)

    def stop(self):
        if not self._is_active:
            return
        self._stop_event.set()
        if self._thread_id:
            try:
                user32 = ctypes.windll.user32
                user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
        self._is_active = False


# ==============================================================================
# Fallback Backend (Headless / Testing / Unsupported Environments)
# ==============================================================================

class _FallbackHotkeyBackend:
    """Fallback hotkey manager for CI and headless testing."""

    def __init__(self):
        self._hotkeys: Dict[int, Tuple[str, Callable[[], None]]] = {}
        self._next_id = 1
        self._is_active = False

    def register(self, shortcut: str, callback: Callable[[], None]) -> int:
        hid = self._next_id
        self._next_id += 1
        self._hotkeys[hid] = (shortcut, callback)
        return hid

    def start(self):
        self._is_active = True
        logger.debug("Fallback hotkey backend active (%d hotkeys).", len(self._hotkeys))

    def stop(self):
        self._is_active = False

    def trigger(self, shortcut_or_id):
        """Simulates triggering a hotkey in testing."""
        for hid, (sc, cb) in self._hotkeys.items():
            if shortcut_or_id in (hid, sc):
                cb()
                return True
        return False


# ==============================================================================
# Unified Native Hotkey Manager
# ==============================================================================

class NativeHotkeyManager:
    """
    Unified cross-platform global hotkey manager.
    Enforces ZERO Keylogger / ZERO Input Monitoring permissions.
    """

    def __init__(self):
        self._backend = None
        self._registered_shortcuts: List[str] = []

        if sys.platform == "darwin":
            try:
                self._backend = _MacCarbonHotkeyBackend()
            except Exception as e:
                logger.warning("Carbon hotkey backend initialization failed, falling back: %s", e)
                self._backend = _FallbackHotkeyBackend()
        elif sys.platform == "win32":
            try:
                self._backend = _WindowsHotkeyBackend()
            except Exception as e:
                logger.warning("Windows hotkey backend initialization failed, falling back: %s", e)
                self._backend = _FallbackHotkeyBackend()
        else:
            self._backend = _FallbackHotkeyBackend()

    def register(self, shortcut: str, callback: Callable[[], None]) -> int:
        """
        Registers a global hotkey callback.
        Supports:
        - "Cmd+Shift+Space" / "Ctrl+Shift+Space"
        - "Cmd+Shift+S" / "Ctrl+Shift+S" / "Alt+S"
        - "F9", "F10"
        """
        try:
            hid = self._backend.register(shortcut, callback)
            self._registered_shortcuts.append(shortcut)
            return hid
        except Exception as e:
            logger.warning("Failed registering hotkey '%s': %s", shortcut, e)
            return -1

    def start(self):
        """Activates native hotkey event monitoring."""
        if self._backend:
            self._backend.start()

    def stop(self):
        """Deactivates and cleans up native hotkeys."""
        if self._backend:
            self._backend.stop()

    def trigger_for_test(self, shortcut_or_id):
        """Testing hook to programmatically trigger a hotkey."""
        if hasattr(self._backend, "trigger"):
            return self._backend.trigger(shortcut_or_id)
        elif hasattr(self._backend, "_callbacks") and shortcut_or_id in self._backend._callbacks:
            self._backend._callbacks[shortcut_or_id]()
            return True
        return False

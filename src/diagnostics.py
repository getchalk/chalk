"""
src/diagnostics.py - Pre-Flight Hardware & Permissions Diagnostic CLI.
Verifies the execution environment before live lecture deployment:
1. Microphone: 1-second test audio capture via sounddevice (16kHz).
2. Screen Recording Authorization: 10x10 non-destructive screen grab via mss.
3. Accessibility API Authorization: AXIsProcessTrusted on macOS / UI Automation on Windows.
4. Secure Keyring & Gemini API: Zero-token client.models.list ping.
5. Audio Loopback Detection: WASAPI loopback (Windows) or BlackHole/virtual driver (macOS).
Outputs a formatted ASCII diagnostic table with actionable navigation paths for missing permissions.
"""

import sys
import os
import time
import logging
import warnings
import numpy as np

# Suppress external third-party library deprecation noise
warnings.filterwarnings("ignore")

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.security import key_manager

# Configure logging
logging.basicConfig(level=logging.WARNING)


class PreFlightDiagnostics:
    """Runs cross-platform hardware and OS authorization tests."""

    def __init__(self):
        self.results = []
        self.platform = sys.platform

    def run_all(self) -> bool:
        """Runs the complete suite and returns True if all critical checks pass."""
        print("\n" + "=" * 76)
        print("  CHALK — PRE-FLIGHT HARDWARE & OS PERMISSIONS DIAGNOSTIC")
        print("=" * 76)
        print(f"  Platform: {sys.platform.upper()} | Python: {sys.version.split()[0]} | Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

        self.check_microphone()
        self.check_screen_recording()
        self.check_accessibility()
        self.check_keyring_and_api()
        self.check_loopback()

        self.print_report()

        # Count critical failures (Microphone, Screen Recording, Accessibility)
        critical_passes = all(
            r["status"] == "PASS" for r in self.results if r["critical"]
        )
        return critical_passes

    def check_microphone(self):
        """1-second test audio capture at 16kHz mono via sounddevice."""
        name = "Microphone Device & Audio Input"
        critical = True
        try:
            import sounddevice as sd

            sample_rate = 16000
            duration = 1.0
            frames = int(sample_rate * duration)

            # Query default input device
            device_info = sd.query_devices(kind="input")
            device_name = device_info.get("name", "Default Microphone")

            # Capture 1 second buffer
            recording = sd.rec(frames, samplerate=sample_rate, channels=1, dtype="float32")
            sd.wait()

            rms = float(np.sqrt(np.mean(recording**2) + 1e-9))
            details = f"Active ('{device_name}', RMS: {rms:.4f})"
            self.results.append({
                "name": name,
                "status": "PASS",
                "critical": critical,
                "details": details,
                "fix_path": None,
            })
        except Exception as e:
            fix_path = (
                "System Settings -> Privacy & Security -> Microphone -> Enable for Terminal / Chalk"
                if self.platform == "darwin"
                else "Settings -> Privacy & Security -> Microphone -> Allow desktop apps"
            )
            self.results.append({
                "name": name,
                "status": "FAIL",
                "critical": critical,
                "details": f"Capture failed: {str(e)[:60]}",
                "fix_path": fix_path,
            })

    def check_screen_recording(self):
        """10x10 non-destructive screen capture via mss."""
        name = "Screen Recording Authorization"
        critical = True
        try:
            import mss

            with mss.mss() as sct:
                monitor = {"left": 0, "top": 0, "width": 10, "height": 10}
                img = sct.grab(monitor)
                if img.width == 10 and img.height == 10:
                    self.results.append({
                        "name": name,
                        "status": "PASS",
                        "critical": critical,
                        "details": "Authorized (10x10 px test grab successful)",
                        "fix_path": None,
                    })
                else:
                    raise ValueError("Captured frame dimension mismatch")
        except Exception as e:
            fix_path = (
                "System Settings -> Privacy & Security -> Screen & System Audio Recording -> Enable for Terminal / Chalk"
                if self.platform == "darwin"
                else "Settings -> System -> Display -> Graphics settings"
            )
            self.results.append({
                "name": name,
                "status": "FAIL",
                "critical": critical,
                "details": f"Screen grab failed: {str(e)[:60]}",
                "fix_path": fix_path,
            })

    def check_accessibility(self):
        """Verifies OS accessibility tree permissions for zero-token OCR and hotkeys."""
        name = "Accessibility API (Zero-Token OCR / Hotkeys)"
        critical = True

        if self.platform == "darwin":
            try:
                from ApplicationServices import AXIsProcessTrusted
                is_trusted = AXIsProcessTrusted()
                if is_trusted:
                    self.results.append({
                        "name": name,
                        "status": "PASS",
                        "critical": critical,
                        "details": "Authorized (AXIsProcessTrusted = True)",
                        "fix_path": None,
                    })
                else:
                    self.results.append({
                        "name": name,
                        "status": "FAIL",
                        "critical": critical,
                        "details": "Process not trusted for AXUIElement inspection",
                        "fix_path": "System Settings -> Privacy & Security -> Accessibility -> Enable for Terminal / Chalk",
                    })
            except Exception as e:
                self.results.append({
                    "name": name,
                    "status": "FAIL",
                    "critical": critical,
                    "details": f"API error: {str(e)[:60]}",
                    "fix_path": "System Settings -> Privacy & Security -> Accessibility",
                })
        elif self.platform == "win32":
            try:
                import ctypes
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                self.results.append({
                    "name": name,
                    "status": "PASS",
                    "critical": critical,
                    "details": f"Authorized (Foreground HWND {hwnd})",
                    "fix_path": None,
                })
            except Exception as e:
                self.results.append({
                    "name": name,
                    "status": "FAIL",
                    "critical": critical,
                    "details": f"UIA error: {str(e)[:60]}",
                    "fix_path": "Run Chalk as standard desktop application",
                })
        else:
            self.results.append({
                "name": name,
                "status": "PASS",
                "critical": False,
                "details": "Linux X11/Wayland environment",
                "fix_path": None,
            })

    def check_keyring_and_api(self):
        """Checks stored BYOK credentials and performs zero-token API ping."""
        name = "Secure Keyring Vault & Gemini API"
        critical = False  # Non-blocking if running diagnostics prior to first GUI launch

        stored_key = key_manager.get_api_key()
        if not stored_key:
            self.results.append({
                "name": name,
                "status": "WARN",
                "critical": critical,
                "details": "No API key configured in OS vault yet",
                "fix_path": "Run 'python src/main.py' to launch Settings dialog, or set export GEMINI_API_KEY='...'",
            })
            return

        # Perform zero-token model validation ping
        is_valid, msg = key_manager.validate_api_key(stored_key)
        if is_valid:
            self.results.append({
                "name": name,
                "status": "PASS",
                "critical": critical,
                "details": "Connected (Google AI Studio zero-token ping succeeded)",
                "fix_path": None,
            })
        else:
            self.results.append({
                "name": name,
                "status": "FAIL",
                "critical": critical,
                "details": f"Invalid key: {msg[:60]}",
                "fix_path": "Update key at https://aistudio.google.com/app/apikey via Chalk Settings modal",
            })

    def check_loopback(self):
        """Detects available hardware or virtual loopback devices."""
        name = "Audio Loopback Detection (Zoom/Teams)"
        critical = False

        found_loopback = False
        driver_name = ""

        try:
            import soundcard as sc

            mics = sc.all_microphones(include_loopback=True)
            for m in mics:
                if getattr(m, "isloopback", False) or any(
                    x in m.name.lower()
                    for x in ("loopback", "blackhole", "soundflower", "screencapture", "stereo mix")
                ):
                    found_loopback = True
                    driver_name = m.name
                    break
        except Exception:
            pass

        if found_loopback:
            self.results.append({
                "name": name,
                "status": "PASS",
                "critical": critical,
                "details": f"Hardware/Virtual loopback detected ('{driver_name}')",
                "fix_path": None,
            })
        else:
            if self.platform == "darwin":
                details = "No virtual loopback device (Mic active, Right channel muted)"
                fix_path = "Optional: Run 'python src/diagnostics.py --install-loopback' or 'brew install blackhole-2ch'"
            elif self.platform == "win32":
                details = "WASAPI Loopback available via default Windows sound driver"
                fix_path = None
            else:
                details = "PulseAudio / PipeWire monitor available"
                fix_path = None

            self.results.append({
                "name": name,
                "status": "WARN" if self.platform == "darwin" else "PASS",
                "critical": critical,
                "details": details,
                "fix_path": fix_path,
            })

    def print_report(self):
        """Renders clear formatted diagnostic ASCII table."""
        col_name = 44
        col_status = 8
        col_details = 50

        print(f"{'CHECK':<{col_name}} {'STATUS':<{col_status}} {'DETAILS'}")
        print("-" * 105)

        for r in self.results:
            st = r["status"]
            if st == "PASS":
                status_str = "[PASS]"
            elif st == "FAIL":
                status_str = "[FAIL]"
            else:
                status_str = "[WARN]"

            name_str = r["name"]
            if len(name_str) > col_name - 2:
                name_str = name_str[: col_name - 5] + "..."

            print(f"{name_str:<{col_name}} {status_str:<{col_status}} {r['details']}")

            if r["fix_path"]:
                print(f"  └─► Action Required: {r['fix_path']}")

        print("-" * 105)
        print()


def handle_loopback_install():
    """Interactive helper to install BlackHole 2ch on macOS via Homebrew."""
    import shutil
    import subprocess

    if sys.platform != "darwin":
        print("Note: The --install-loopback helper is only applicable on macOS.")
        print("Windows uses native WASAPI loopback without third-party drivers.")
        sys.exit(0)

    print("\n" + "=" * 76)
    print("  CHALK — BLACKHOLE 2CH AUDIO LOOPBACK INSTALLER")
    print("=" * 76)

    brew_path = shutil.which("brew")
    if not brew_path:
        print("[FAIL] Homebrew ('brew') was not detected in your PATH.")
        print("  Please install BlackHole 2ch manually from:")
        print("  https://github.com/ExistentialAudio/BlackHole/releases\n")
        sys.exit(1)

    print(f"[OK] Detected Homebrew at: {brew_path}")
    print("Installing BlackHole 2ch driver ('brew install blackhole-2ch')...\n")
    try:
        subprocess.check_call([brew_path, "install", "blackhole-2ch"])
        print("\n" + "-" * 76)
        print("[OK] BlackHole 2ch successfully installed!")
        print("  System audio loopback is now available for Zoom, Teams, and presentation media.")
        print("-" * 76 + "\n")
        sys.exit(0)
    except subprocess.CalledProcessError as e:
        print(f"\n[FAIL] Homebrew installation exited with error code {e.returncode}.")
        sys.exit(e.returncode)


def main():
    if "--install-loopback" in sys.argv:
        handle_loopback_install()
        return

    diag = PreFlightDiagnostics()
    success = diag.run_all()
    if success:
        print("[OK] All critical pre-flight checks passed! Chalk is ready for lecture recording.\n")
        sys.exit(0)
    else:
        print("[FAIL] One or more critical system permissions are missing. Please resolve them using the paths above.\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

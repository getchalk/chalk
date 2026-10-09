"""
build_standalone.py - PyInstaller Compilation Script for Chalk.
Bundles Chalk as a single standalone executable with --noconsole, --onefile,
and the new minimalist assets/app.ico.
Includes hidden imports and injects macOS Info.plist permission manifests:
- NSScreenCaptureUsageDescription
- NSMicrophoneUsageDescription
- NSAppleEventsUsageDescription
"""

import os
import sys
import subprocess
import shutil

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
ENTRY_POINT = os.path.join(PROJECT_ROOT, "src", "main.py")
ASSETS_DIR = os.path.join(PROJECT_ROOT, "assets")
ICO_PATH = os.path.join(ASSETS_DIR, "app.ico")
ICNS_PATH = os.path.join(ASSETS_DIR, "app.icns")
ICON_PATH = ICNS_PATH if sys.platform == "darwin" and os.path.exists(ICNS_PATH) else ICO_PATH
ENTITLEMENTS_PATH = os.path.join(ASSETS_DIR, "entitlements.plist")
SPEC_PATH = os.path.join(PROJECT_ROOT, "Chalk.spec")


def ensure_pyinstaller():
    """Ensures pyinstaller is installed in the current environment."""
    try:
        import PyInstaller
        print(f"PyInstaller version {PyInstaller.__version__} detected.")
    except ImportError:
        print("Installing pyinstaller...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def generate_spec_file():
    """
    Generates a production Chalk.spec with macOS permission keys in Info.plist.
    """
    spec_content = f"""# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None
project_root = r"{PROJECT_ROOT}"
assets_dir = r"{ASSETS_DIR}"
entry_point = r"{ENTRY_POINT}"
icon_path = r"{ICON_PATH}"
entitlements_path = r"{ENTITLEMENTS_PATH}"

added_datas = [
    (assets_dir, 'assets'),
]

hidden_imports = [
    'soundcard',
    'sounddevice',
    'pystray',
    'pystray._darwin',
    'pystray._win32',
    'keyring',
    'keyring.backends',
    'keyring.backends.macOS',
    'keyring.backends.Windows',
    'keyring.backends.SecretService',
    'PyQt6',
    'PyQt6.QtCore',
    'PyQt6.QtGui',
    'PyQt6.QtWidgets',
    'google.genai',
    'google.genai.types',
    'pypdf',
    'pptx',
    'imagehash',
    'mss',
    'PIL',
    'torch',
    'torchaudio',
    'src.security.hotkeys',
    'src.engine.config',
    'src.engine.journal',
    'src.api.multi_provider',
    'src.api.synthesis_pipeline',
    'src.companion',
    'src.companion.qr_generator',
    'src.companion.bridge',
    'src.companion.server',
    'src.ui.i18n',
]

a = Analysis(

    [entry_point],
    pathex=[project_root],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if sys.platform == 'darwin':
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Chalk',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=entitlements_path if os.path.exists(entitlements_path) else None,
        icon=icon_path,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='Chalk',
    )
    app = BUNDLE(
        coll,
        name='Chalk.app',
        icon=icon_path,
        bundle_identifier='com.chalk.lectureengine',
        info_plist={{
            'CFBundleName': 'Chalk',
            'CFBundleDisplayName': 'Chalk',
            'CFBundleIdentifier': 'com.chalk.lectureengine',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
            'NSScreenCaptureUsageDescription': 'Chalk requires screen recording permission to synchronize slide transitions and support the screen snip tool during lectures.',
            'NSMicrophoneUsageDescription': 'Chalk requires microphone access to record professor lectures, in-room discussions, and student questions.',
            'NSAudioCaptureUsageDescription': 'Chalk requires system audio recording permission to capture remote lecturer or digital media audio during sessions.',
            'NSAppleEventsUsageDescription': 'Chalk requires accessibility permissions for zero-token presentation text extraction from slide decks.',
            'CFBundleURLTypes': [
                {{
                    'CFBundleURLName': 'so.chalk.audio',
                    'CFBundleURLSchemes': ['chalk-audio'],
                }}
            ],
        }},
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name='Chalk',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        icon=icon_path,
    )
"""
    with open(SPEC_PATH, "w", encoding="utf-8") as f:
        f.write(spec_content)
    print(f"Generated PyInstaller spec with macOS permissions manifest: {SPEC_PATH}")


def build_binary():
    ensure_pyinstaller()

    # Ensure icon exists
    if not os.path.exists(ICON_PATH):
        print("Generating icon...")
        from assets.generate_icon import create_chalk_icon
        create_chalk_icon(ASSETS_DIR)

    generate_spec_file()

    # Build using spec non-interactively
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        SPEC_PATH,
    ]

    print("Executing PyInstaller build with spec:")
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=PROJECT_ROOT)

    dist_dir = os.path.join(PROJECT_ROOT, "dist")
    print(f"\n[OK] Standalone build complete. Binaries located in: {dist_dir}")


if __name__ == "__main__":
    build_binary()

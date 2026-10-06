# -*- mode: python ; coding: utf-8 -*-
import sys
import os

block_cipher = None
project_root = r"/Users/user/.gemini/antigravity/scratch/chalk"
assets_dir = r"/Users/user/.gemini/antigravity/scratch/chalk/assets"
entry_point = r"/Users/user/.gemini/antigravity/scratch/chalk/src/main.py"
icon_path = r"/Users/user/.gemini/antigravity/scratch/chalk/assets/app.icns"

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
]

a = Analysis(
    [entry_point],
    pathex=[project_root],
    binaries=[],
    datas=added_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

# macOS Application Bundle with Info.plist Permissions Manifest
if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='Chalk.app',
        icon=icon_path,
        bundle_identifier='com.chalk.lectureengine',
        info_plist={
            'CFBundleName': 'Chalk',
            'CFBundleDisplayName': 'Chalk',
            'CFBundleIdentifier': 'com.chalk.lectureengine',
            'CFBundleVersion': '1.0.0',
            'CFBundleShortVersionString': '1.0.0',
            'NSHighResolutionCapable': True,
            'NSScreenCaptureUsageDescription': 'Chalk requires screen recording permission to synchronize slide transitions and support the screen snip tool during lectures.',
            'NSMicrophoneUsageDescription': 'Chalk requires microphone access to record professor lectures, in-room discussions, and student questions.',
            'NSAppleEventsUsageDescription': 'Chalk requires accessibility permissions for global hotkeys (Alt+Space, Alt+S, F9, F10) and zero-token presentation text extraction.',
        },
    )

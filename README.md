# Chalk

**Local-first multimodal lecture and meeting companion with live LaTeX synthesis.**

Chalk runs quietly in the background on macOS and Windows. It captures dual-channel audio and slide transitions, accepts whiteboard photos via a zero-install local QR link, and synthesizes structured Markdown notes with mathematically verified LaTeX in real time.

Built on a strict **Direct Bring-Your-Own-Key (BYOK) • Local-First** architecture. Raw audio, visual keyframes, and disk journals remain exclusively on your local workstation. Synthesis requests connect directly over TLS 1.3 to official AI endpoints (Google AI Studio, Anthropic, or OpenAI). Zero telemetry, zero tracking cookies, and zero intermediary proxy servers.

- **Website:** [getchalk.github.io](https://getchalk.github.io)
- **Downloads:** [macOS (Apple Silicon)](https://github.com/getchalk/chalk/releases/latest/download/Chalk-macOS.zip) · [Windows (x64)](https://github.com/getchalk/chalk/releases/latest/download/Chalk-Setup.exe)
- **Source:** [github.com/getchalk/chalk](https://github.com/getchalk/chalk)

---

## Architecture

```
                                  +-------------------------------------+
                                  |         Chalk Tray & Hotkeys        |
                                  |   (Cmd+Shift+Space / Ctrl+Shift+Sp) |
                                  +------------------+------------------+
                                                     |
               +-------------------------------------+-------------------------------------+
               |                                     |                                     |
               v                                     v                                     v
  +-------------------------+           +-------------------------+           +-------------------------+
  |    Dual-Channel Audio   |           |    Visual & Slide Sync  |           |   Companion QR Daemon   |
  | (Mic L / Loopback WASAPI|           |  (Zero-Token AX Tree +  |           |  (Pure-Python HTTP LAN  |
  |  CoreAudio BlackHole R) |           |  pHash Deduplication)   |           |   Whiteboard Camera)    |
  +------------+------------+           +------------+------------+           +------------+------------+
               |                                     |                                     |
               v                                     v                                     v
  +-------------------------+                        |                        +-------------------------+
  |    Local Silero VAD     |                        |                        |  Image Optimization &   |
  | (Speech Filter & Break) |                        |                        |  Priority Blackboard Q  |
  +------------+------------+                        |                        +------------+------------+
               |                                     |                                     |
               v                                     |                                     |
  +-------------------------+                        |                                     |
  | 30s Disk Journal Engine |                        |                                     |
  | (~/.chalk/sessions/<id>)|                        |                                     |
  +------------+------------+                        |                                     |
               |                                     |                                     |
               +------------------+------------------+-------------------------------------+
                                  |
                                  v
                     +-------------------------+
                     | Elastic Chunker & Quota |
                     | (12-45m Window, 429 WF) |
                     +------------+------------+
                                  |
               +------------------+------------------+
               |                                     |
               v                                     v
  +-------------------------+           +-------------------------+
  | Flash Operational Model |           |  Pro Synthesis Engine   |
  | (Low-Latency Chunking,  |           | (Executive Summaries,   |
  |  LaTeX JSON Validation) |           |  Anki Decks, Deep Q&A)  |
  +------------+------------+           +------------+------------+
               |                                     |
               +------------------+------------------+
                                  |
                                  v
                     +-------------------------+
                     |    Obsidian Markdown    |
                     | (~/Documents/Notes/...) |
                     +-------------------------+
```

---

## Core Capabilities

### 1. Dual-Channel Hardware Audio
- **Channel Isolation:** Left channel captures local ambient acoustics (student questions, in-room speech via `sounddevice` at 16 kHz mono). Right channel captures system loopback (Zoom, Teams, Keynote, video playback via Windows WASAPI loopback or macOS CoreAudio BlackHole).
- **Local Silero VAD:** Evaluates speech probabilities on CPU via PyTorch. Automatically strips silent gaps $>1.5\text{s}$ to conserve tokens by ~40%.
- **Autonomous Break Detection:** If vocal presence drops below threshold for $>180\text{s}$, Chalk automatically flushes the open chunk, switches to Standby, and resumes only when speech restarts.

### 2. Persistent Disk Journaling & Crash Recovery
- **O(1) Memory Footprint:** Audio buffers are flushed to disk every 30 seconds into `~/.chalk/sessions/<SESSION_ID>/seg_XXXX.wav`. Memory usage stays flat ($\le 30\text{ MB}$) during 7+ hour lectures.
- **Atomic Manifest:** Every segment write atomically updates `manifest.json`. If the laptop lid closes or a system crash occurs, Chalk detects incomplete sessions on next launch and resumes processing seamlessly.
- **Audio Compression:** On macOS, audio is pre-compressed to 32 kbps AAC via `/usr/bin/afconvert` (a 45-minute chunk is $\sim 10.8\text{ MB}$, well within the 20 MB cloud inline limit).

### 3. Coupled Dual-Stage Model Selection
Chalk pairs a high-throughput, low-latency operational model for rolling chunks with a frontier reasoning model for the final session synthesis:

| Preset ID | Category | Operational Model (Live Chunks) | Synthesis Model (End of Lecture) | Daily Quota Profile |
|---|---|---|---|---|
| `gemini-max` | Gemini Free (Direct BYOK) | Gemini 3.5 Flash | Gemini 3.1 Pro | 50 RPD / 1M Context |
| `gemini-medium` | Gemini Free (Direct BYOK) | Gemini 3.5 Flash-Lite | Gemini 3.5 Flash | 500 RPD / 1M Context |
| `gemini-min` | Gemini Free (Direct BYOK) | Gemini 3.1 Flash-Lite | Gemini 3.5 Flash-Lite | 1500 RPD / 1M Context |
| `paid-gemini` | Paid Model (Direct BYOK) | Gemini 3.8 Flash | Gemini 3.8 Flash | 10,000+ RPD (Pay-as-you-go) |
| `paid-claude` | Paid Model (Direct BYOK) | Claude 5.5 Sonnet | Claude 5.5 Sonnet | BYOK Anthropic API Key |
| `paid-openai` | Paid Model (Direct BYOK) | GPT-6.1 Sol | GPT-6.1 Sol | BYOK OpenAI API Key |

### 4. Zero-Install Whiteboard QR Camera
- **Zero App Required:** Scanning the QR code on the floating HUD opens a lightweight, responsive web camera interface served directly by Chalk's local daemon on port `18950`.
- **Direct LAN / Hotspot:** Phone uploads stream directly across your local network or mobile hotspot in $<850\text{ ms}$ without passing through cloud services.
- **Synthesis Priority:** Whiteboard snapshots receive top priority during chunk synthesis to ensure handwritten mathematical steps are transcribed into typed LaTeX formulas alongside the lecture speech.

### 5. Typed LaTeX JSON & KaTeX Verification
- **Anti-Hallucination:** Prompts enforce strict mathematical derivation rules. Gaps or omitted intermediate steps are explicitly marked as `[Lücke]` rather than fabricated.
- **Syntax Validation:** All LaTeX output is validated locally for balanced braces and valid KaTeX control sequences before rendering. Proof blocks cleanly terminate with the QED symbol `∎`.
- **Obsidian Callouts:** Formatted as standard Obsidian callouts (`> [!theorem]`, `> [!definition]`, `> [!proof]`, `> [!question]`).

### 6. Zero-Token Presentation Sync
- **Accessibility Tree:** Queries slide titles and text from PowerPoint, Keynote, Adobe Acrobat, or browser tabs in $<2\text{ ms}$ via macOS `AXUIElement` or Windows UI Automation without burning image tokens.
- **pHash Deduplication:** Screen captures are taken on slide transitions and filtered using perceptual hashing (`imagehash.phash`, Hamming distance $\ge 8$) to discard identical or jittery frames.
- **In-Person PDF Import:** Drag-and-drop lecture slides (`.pdf`) onto the HUD before class; Chalk automatically aligns spoken audio to corresponding slide pages.

---

## Global Hotkeys

Hotkeys use native operating system APIs (Carbon `RegisterEventHotKey` on macOS and Win32 `RegisterHotKey` on Windows). They require **zero input monitoring or keylogger permissions**.

| Action | macOS | Windows | Description |
|---|---|---|---|
| **Toggle HUD** | <kbd>Cmd</kbd> + <kbd>Shift</kbd> + <kbd>Space</kbd> | <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>Space</kbd> | Shows or hides the translucent floating Copilot HUD. |
| **Screen Snip** | <kbd>Cmd</kbd> + <kbd>Shift</kbd> + <kbd>S</kbd> | <kbd>Ctrl</kbd> + <kbd>Shift</kbd> + <kbd>S</kbd> | Freezes the screen and opens crop marquee to feed visual context to AI. |
| **Toggle Session** | <kbd>F9</kbd> | <kbd>F9</kbd> | Starts or pauses session; triggers final synthesis when finishing. |
| **Flush Chunk** | <kbd>F10</kbd> | <kbd>F10</kbd> | Manually triggers immediate synthesis of the current buffer. |

---

## Installation

### Pre-built Binaries

Pre-built binaries are available on the [releases page](https://github.com/getchalk/chalk/releases).

#### macOS (Apple Silicon M1/M2/M3/M4)
```bash
curl -L -O https://github.com/getchalk/chalk/releases/latest/download/Chalk-macOS.zip
unzip Chalk-macOS.zip
open Chalk.app
```

#### Windows (x64)
```powershell
curl -L -O https://github.com/getchalk/chalk/releases/latest/download/Chalk-Setup.exe
.\Chalk-Setup.exe
```

---

### Running from Source

#### Prerequisites
- Python 3.9+ (Python 3.10 or 3.11 recommended)
- A Google AI Studio API key (free at [aistudio.google.com](https://aistudio.google.com/app/apikey)) or BYOK key for Anthropic/OpenAI

#### Setup
```bash
# Clone the repository
git clone https://github.com/getchalk/chalk.git
cd chalk

# Set up virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run Chalk
python src/main.py
```

On first launch, Chalk prompts for your API key in the settings dialog. The key is validated via a zero-token ping (`client.models.list(config={"page_size": 1})`) and stored securely in your operating system's native encrypted credential store (macOS Keychain or Windows DPAPI).

---

## Testing & Verification

Chalk includes a comprehensive automated test suite covering audio ingestion, VAD offset mapping, 7-hour soak recovery, LaTeX validation, and the companion QR server:

```bash
# Run the core pipeline test suite
python -m unittest tests/test_chalk_pipeline.py

# Run companion bridge and UI smoke tests
python -m unittest tests/test_companion_pipeline.py tests/test_smoke_coordinator_and_hud.py tests/test_forensic_fixes.py

# Validate web portal integrity (monochrome check, node syntax, i18n completeness)
./scripts/deploy_web.sh test
```

---

## Standalone Compilation

To compile a standalone, self-contained desktop binary with bundled icons and zero console popups:

```bash
# macOS (.app bundle)
python build_standalone.py

# Windows (.exe installer)
scripts/build_windows.bat
```

Compiled outputs are written to `dist/`.

---

## Repository Structure

```
chalk/
├── src/
│   ├── main.py                     # Application lifecycle, coordination & tray
│   ├── api/
│   │   ├── gemini_client.py        # Google GenAI SDK client & lifecycle deletion
│   │   ├── multi_provider.py       # Anthropic & OpenAI provider adapters
│   │   ├── synthesis_pipeline.py   # Typed LaTeX JSON blocks & KaTeX verification
│   │   └── tools.py                # Desktop function calling sandbox
│   ├── audio/
│   │   ├── capture.py              # SoundDevice & system loopback capture
│   │   ├── recorder.py             # Stereo ring buffer & rolling rewind
│   │   └── vad_detector.py         # Silero VAD speech filter & offset mapper
│   ├── companion/
│   │   ├── bridge.py               # Phone image ingestion & priority queue
│   │   ├── qr_generator.py         # Pure-Python dependency-free SVG QR encoder
│   │   └── server.py               # Local LAN/Hotspot HTTP companion daemon
│   ├── engine/
│   │   ├── config.py               # Coupled dual-stage preset registry
│   │   ├── elastic_chunker.py      # Dynamic quota-aware time chunker
│   │   ├── journal.py              # Persistent 30s disk journal & crash recovery
│   │   ├── quota_manager.py        # Daily token & RPD tracker
│   │   └── session_state.py        # Incremental note assembler
│   ├── export/
│   │   └── pdf_exporter.py         # Formatted PDF note exporter
│   ├── security/
│   │   ├── hotkeys.py              # Native Carbon / Win32 hotkeys (zero keylogger)
│   │   └── key_manager.py          # Native OS Keychain / DPAPI vault
│   ├── ui/
│   │   ├── hud_window.py           # Translucent floating Copilot HUD
│   │   ├── i18n.py                 # 5-language desktop localization dictionary
│   │   ├── search_dialog.py        # Full-text lecture transcript search
│   │   ├── settings_dialog.py      # BYOK preferences & model preset picker
│   │   ├── snip_overlay.py         # Screen crop marquee overlay
│   │   └── tray.py                 # Native system tray indicator & menu
│   └── vision/
│       ├── accessibility.py        # Zero-token AXUIElement / UIA text extractor
│       ├── screen_grabber.py       # High-DPI screen grabber
│       └── slide_filter.py         # Perceptual hash deduplication
├── web/
│   ├── index.html                  # Purist titanium landing page & interactive preview
│   └── assets/                     # Optimized web logos and atmosphere visuals
├── scripts/
│   ├── deploy_web.sh               # Web validation & GitHub Pages deployment
│   ├── build_windows.bat           # Windows PyInstaller build script
│   └── notarize_macos.sh           # macOS Apple notarization script
├── tests/                          # 74+ automated unit & integration tests
├── build_standalone.py             # Cross-platform binary builder
└── requirements.txt                # Production dependencies
```

---

## Security & Privacy Model

1. **Direct BYOK Only:** Chalk provides no intermediary servers. Your machine communicates directly with official Google, Anthropic, or OpenAI endpoints over TLS 1.3.
2. **Encrypted Credentials:** API keys are never stored in plaintext config files. They are saved strictly in macOS Keychain Access or Windows DPAPI.
3. **Local Storage:** Audio recordings and visual keyframes live exclusively under `~/.chalk/sessions/` on your local hard drive.
4. **Google Files API Hygiene:** Any media uploaded to Google's Files API is tracked and deleted in a `finally` block immediately after synthesis finishes.
5. **Zero Telemetry:** The app and website contain zero tracking scripts, zero Google Analytics, and zero third-party cookies (§ 165 TKG / GDPR compliant).

---

## License

MIT License. See [LICENSE](LICENSE) for details.

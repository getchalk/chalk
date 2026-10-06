# Chalk — Autonomous Desktop Lecture Engine & Web Portal

> **"Let them talk. Chalk does the work."**

Chalk is a silent, background cross-platform desktop daemon designed to capture 3.5-hour to 7-hour university lectures, synchronize spoken audio with slide transitions, and synthesize structured LaTeX Markdown notes in real time.

Operating under a **True Zero-Knowledge Bring-Your-Own-Key (BYOK)** architecture, Chalk connects directly from the client to Google AI Studio via the official `google-genai` SDK (`from google import genai`). It uses zero intermediary proxy servers, performs no cloud telemetry, and stores credentials exclusively in the operating system's native encrypted vault (Windows Credential Locker via DPAPI or Apple Keychain Access on macOS).

---

## ⚡ Core Architecture

```
                                      ┌─────────────────────────────────────┐
                                      │           Chalk Tray Daemon         │
                                      │   (🟢 Recording / 🟡 Break / 🔵 API) │
                                      └──────────────────┬──────────────────┘
                                                         │
                   ┌─────────────────────────────────────┼─────────────────────────────────────┐
                   ▼                                     ▼                                     ▼
      ┌─────────────────────────┐           ┌─────────────────────────┐           ┌─────────────────────────┐
      │   Dual-Channel Audio    │           │    Visual & Slides      │           │    Floating Agent HUD   │
      │  (Mic L / Loopback R)   │           │   (pHash & Zero-Token)  │           │      (Alt + Space)      │
      └────────────┬────────────┘           └────────────┬────────────┘           └────────────┬────────────┘
                   │                                     │                                     │
                   ▼                                     ▼                                     │
      ┌─────────────────────────┐           ┌─────────────────────────┐                        │
      │    Silero VAD Engine    │           │ Accessibility Tree / AX │                        │
      │  (>180s Break Detector) │           │ (Zero-Token Slide OCR)  │                        │
      └────────────┬────────────┘           └────────────┬────────────┘                        │
                   │                                     │                                     │
                   └──────────────────┬──────────────────┘                                     │
                                      ▼                                                        │
                         ┌─────────────────────────┐                                           │
                         │ Elastic Chunker & Quota │ ◄─────────────────────────────────────────┘
                         │ (12-45m Window, 429 WF) │
                         └────────────┬────────────┘
                                      │
                   ┌──────────────────┴──────────────────┐
                   ▼                                     ▼
      ┌─────────────────────────┐           ┌─────────────────────────┐
      │  Gemini Flash Chunking  │           │   Gemini Pro Synthesis  │
      │   (Live Mathematical    │           │   (Executive Summary,   │
      │     LaTeX Markdown)     │           │   Anki Deck, Exam Prep) │
      └────────────┬────────────┘           └────────────┬────────────┘
                   │                                     │
                   └──────────────────┬──────────────────┘
                                      ▼
                         ┌─────────────────────────┐
                         │ ./Notes/Lecture_Date.md │
                         │ (<!-- CHUNK_STATE -->)  │
                         └─────────────────────────┘
```

---

## 🌟 Key Features

1. **Dual-Channel Audio & Hardware Diarization:**
   - **Left Channel:** In-person lecturer & student acoustics via `sounddevice` (16kHz mono).
   - **Right Channel:** Remote lecturer, Zoom/Teams, or slide media audio via native OS loopback (Windows WASAPI loopback via `soundcard.all_microphones(include_loopback=True)` / macOS ScreenCaptureKit).
   - Synchronizes into a stereo stream for hardware diarization without heavy local ML models.

2. **Local Silero VAD & Autonomous Break Detection:**
   - Evaluates speech probability locally on CPU via PyTorch.
   - Strips silent gaps $>1.5\text{ seconds}$ from recording payloads to reduce payload tokens by ~40%.
   - Detects sustained lecture breaks: if speech probability remains $<0.3$ for $>180\text{ seconds}$, fires `EVENT_BREAK_DETECTED`, flushes the active chunk immediately, switches state to Yellow (Standby), sends a native OS notification, and rests until vocal formants resume.

3. **Accessibility Tree Bypass (Zero-Token OCR) & pHash Slide Deduplication:**
   - Queries active presentation windows (PowerPoint, Keynote, Adobe Acrobat, Zoom, or browser) via macOS `AXUIElement` or Windows UI Automation in $<2\text{ ms}$, bypassing image token consumption.
   - Samples visual presentation keyframes using `mss` gated by presentation keys (Right Arrow, Page Down, Space, Mouse Scroll).
   - Filters redundant frames using perceptual hashing (`imagehash.phash`) with configurable Hamming distance thresholds (default: 8; throttled: 14).

4. **Dynamic Quota Manager & Elastic Chunker:**
   - Ledger at `~/.chalk/quota_state.json` tracks requests and tokens used today, resetting automatically at 00:00 UTC.
   - Calculates dynamic window: $\text{Target Window} = \text{clamp}\left(\frac{\text{Est. Remaining Time}}{\text{Safe Remaining RPD}}, 12\text{ min}, 45\text{ min}\right)$.
   - Flushes chunks within target window upon conversational pauses ($>3.5\text{s}$ silence) or slide advancements.
   - Handles network dropouts and HTTP 429 rate limits by re-inserting audio and slides back into the active recording queue with a 5-minute backoff.

5. **Hybrid Gemini Pipeline & Context Chaining:**
   - **Live Chunks (Gemini Flash):** Synthesizes notes using student scratchpad shorthand as the primary outline anchor, routes student interruptions into `> ❓ Student Question [MM:SS]` callouts, formats math into clean LaTeX display blocks ($$...$$), and terminates with `<!-- CHUNK_STATE -->` blocks to ensure continuous mathematical continuity without drift.
   - **Master Synthesis (Gemini Pro):** Generates executive session summaries, standardized derivations, high-stakes exam warnings, and Anki study decks with Cloze deletion syntax (`{{c1::answer}}`).

6. **Interactive Copilot HUD & Local Desktop Tools:**
   - Translucent dark-mode floating HUD (`Alt + Space`).
   - Marquee Screen Snip tool (`Alt + S`).
   - Trailing 90-second audio rewind with instant verbatim transcription.
   - Local tool execution (`read_local_file`, `capture_active_screen`, `rewind_audio_transcript`, `append_to_notes`) running in background `QThread` workers.

---

## ⌨️ Global Hotkeys

| Shortcut | Action | Description |
|---|---|---|
| <kbd>Alt</kbd> + <kbd>Space</kbd> | **Toggle Floating HUD** | Toggles the translucent floating Copilot HUD without stealing focus from slides. |
| <kbd>Alt</kbd> + <kbd>S</kbd> | **Screen Snip Marquee** | Freezes screen, darkens display, lets you drag a crop box, and attaches image to prompt. |
| <kbd>F9</kbd> | **Toggle Recording / End** | Starts or pauses session; or triggers Master Synthesis when concluding. |
| <kbd>F10</kbd> | **Force Chunk Flush** | Forces the active audio and slide buffer to immediately synthesize via Gemini Flash. |

---

## 🚦 System Tray Status Indicators

- 🟢 **Green:** Actively recording (Mic + System Loopback + Slides).
- 🟡 **Yellow:** Paused (Autonomous Break detected via Silero VAD or manual standby).
- 🔵 **Blue:** Processing chunk or running Master Synthesis via Gemini API worker.

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- Python 3.9+
- A free Google AI Studio API Key from [aistudio.google.com](https://aistudio.google.com/app/apikey)

### 2. Installation
```bash
# Clone and enter the repository
cd /Users/user/.gemini/antigravity/scratch/chalk

# Activate virtual environment
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Launching Chalk
```bash
python src/main.py
```
On first launch, if no API key is detected in your OS native encrypted vault, Chalk displays the dark-mode BYOK configuration modal. Enter your key, click **"Validate & Save to Vault"**, and Chalk will verify the key via a zero-token ping (`client.models.list(config={"page_size": 1})`) before saving it to your OS Keychain / Credential Locker.

---

## 📦 Standalone Binary Compilation

To package Chalk into a standalone single-file executable with no console window and bundled multi-resolution application icons:

```bash
python build_standalone.py
```

The resulting standalone executable will be located in `dist/Chalk` (or `dist/Chalk.exe` on Windows).

---

## 🌐 Regulatory-Compliant Landing Page

The static web landing page is located at `web/index.html`. It contains:
- Zero cookies, zero trackers, and zero external analytics.
- Animated CSS audio waveforms and live app preview.
- Full legal compliance with Austrian **§ 25 MedienG** (Impressum) and EU **GDPR/DSGVO** (Datenschutzerklärung).
- Classroom recording consent disclaimer notice compliant with Austrian Criminal Code (**§ 120 StGB**).

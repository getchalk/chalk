"""
src/api/tools.py - Local Desktop Tools for Gemini Agent Function Calling.
Exposes local executable tools to Gemini:
- read_local_file(path): Ingests text, PDF (pypdf), PPTX (python-pptx), or source code.
- capture_active_screen(): Takes an instant screen snapshot.
- rewind_audio_transcript(seconds): Fetches trailing audio buffer for instant transcription.
- append_to_notes(heading, markdown_content): Writes directly to the active session notes.
"""

import os
import time
import logging
from typing import Optional, Callable, Tuple, List, Dict, Any
from PIL import Image

logger = logging.getLogger("chalk.api.tools")

# Context references registered at runtime by main / engine
_RECORDER_REF = None
_SCREEN_GRABBER_REF = None
_NOTES_MANAGER_REF = None
_GEMINI_CLIENT_REF = None


def register_tool_context(
    recorder=None,
    screen_grabber=None,
    notes_manager=None,
    gemini_client=None,
):
    """Registers application subsystem instances for tool execution."""
    global _RECORDER_REF, _SCREEN_GRABBER_REF, _NOTES_MANAGER_REF, _GEMINI_CLIENT_REF
    if recorder is not None:
        _RECORDER_REF = recorder
    if screen_grabber is not None:
        _SCREEN_GRABBER_REF = screen_grabber
    if notes_manager is not None:
        _NOTES_MANAGER_REF = notes_manager
    if gemini_client is not None:
        _GEMINI_CLIENT_REF = gemini_client
    logger.info("Chalk desktop tools context registered.")


FORBIDDEN_SYSTEM_PREFIXES = (
    "/etc", "/var", "/bin", "/sbin", "/usr", "/System", "/Library",
    "/private", "C:\\Windows", "C:\\Program Files", "C:\\ProgramData",
)

SENSITIVE_FILENAME_PATTERNS = (
    ".env", ".ssh", ".aws", ".gnupg", ".git", ".config",
    "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
    "credentials", "secrets", "keychain", ".bash_history", ".zsh_history"
)


def _is_path_allowed(real_path: str) -> Tuple[bool, str]:
    """Validates realpath against sandbox restrictions."""
    for prefix in FORBIDDEN_SYSTEM_PREFIXES:
        if real_path == prefix or real_path.startswith(prefix + os.sep):
            return False, f"Access denied: system path '{prefix}' is protected."

    home = os.path.expanduser("~")
    home_real = os.path.realpath(home)
    root_real = os.path.realpath("/")
    cwd_real = os.path.realpath(os.getcwd())

    allowed_dirs = [
        os.path.realpath(os.path.join(home, "Documents")),
        os.path.realpath(os.path.join(home, "Desktop")),
        os.path.realpath(os.path.join(home, "Downloads")),
        os.path.realpath(os.path.join(home, ".chalk")),
    ]
    # Only permit cwd if it is a specific project subdirectory, not user home or root
    if cwd_real not in (home_real, root_real):
        allowed_dirs.append(cwd_real)

    if _NOTES_MANAGER_REF is not None and hasattr(_NOTES_MANAGER_REF, "notes_dir"):
        allowed_dirs.append(os.path.realpath(_NOTES_MANAGER_REF.notes_dir))

    matched_root = None
    for ad in allowed_dirs:
        if real_path == ad or real_path.startswith(ad + os.sep):
            matched_root = ad
            break

    if matched_root is None:
        return False, "Access denied: path is outside permitted student directories (Documents, Desktop, Downloads, Chalk notes)."

    # Check path components inside the allowed directory
    rel = os.path.relpath(real_path, matched_root)
    if rel != ".":
        parts = os.path.normpath(rel).split(os.sep)
        for part in parts:
            part_lower = part.lower()
            for sens in SENSITIVE_FILENAME_PATTERNS:
                if sens in part_lower:
                    return False, f"Access denied: sensitive path component '{part}' is protected."
            # Disallow hidden files or directories within permitted tree
            if part.startswith(".") and part != ".chalk":
                return False, f"Access denied: hidden directory or file '{part}' is protected."

    return True, ""


def read_local_file(path: str) -> str:
    """
    Reads and extracts text from a local file on the user's machine.
    Enforces realpath sandbox restrictions. Supports PDF documents (.pdf),
    PowerPoint slides (.pptx), Markdown (.md), plain text (.txt), and source code files.

    Args:
        path: Absolute or relative file path to read.
    """
    clean_path = os.path.expanduser(os.path.expandvars(path.strip()))
    real_path = os.path.realpath(clean_path)

    allowed, reason = _is_path_allowed(real_path)
    if not allowed:
        logger.warning("Security sandbox blocked file access to '%s': %s", real_path, reason)
        return f"Security Error: {reason}"

    if not os.path.exists(real_path):
        return f"Error: File not found at '{real_path}'."
    if os.path.isdir(real_path):
        return f"Error: '{real_path}' is a directory, not a file."

    try:
        lower = real_path.lower()

        # PDF extraction via pypdf
        if lower.endswith(".pdf"):
            import pypdf

            reader = pypdf.PdfReader(real_path)
            total_pages = len(reader.pages)
            extracted = []
            for idx, page in enumerate(reader.pages[:40]):  # cap at 40 pages
                text = page.extract_text()
                if text:
                    extracted.append(f"--- Page {idx + 1} ---\n{text.strip()}")
            return f"PDF Document: {os.path.basename(real_path)} ({total_pages} pages)\n" + "\n\n".join(extracted)

        # PPTX extraction via python-pptx
        elif lower.endswith((".pptx", ".ppt")):
            from pptx import Presentation

            prs = Presentation(real_path)
            slide_texts = []
            for idx, slide in enumerate(prs.slides[:60]):
                slide_content = []
                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        slide_content.append(shape.text.strip())
                if slide_content:
                    slide_texts.append(f"--- Slide {idx + 1} ---\n" + "\n".join(slide_content))
            return f"PowerPoint Presentation: {os.path.basename(real_path)}\n" + "\n\n".join(slide_texts)

        # Plain text / Markdown / Source files
        else:
            with open(real_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(150_000)  # Read up to 150k characters
                return f"File: {os.path.basename(real_path)}\n{content}"

    except Exception as e:
        logger.error("Failed reading file '%s': %s", real_path, e)
        return f"Error reading file '{real_path}': {str(e)}"


def capture_active_screen() -> str:
    """
    Takes an instant screenshot of the user's active presentation display
    and saves it to the Chalk temporary cache.
    """
    try:
        cache_dir = os.path.expanduser("~/.chalk/cache")
        os.makedirs(cache_dir, exist_ok=True)
        img_path = os.path.join(cache_dir, f"screen_{int(time.time())}.jpg")

        if _SCREEN_GRABBER_REF is not None:
            img = _SCREEN_GRABBER_REF.capture_screenshot()
        else:
            import mss

            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

        rgb_img = img.convert("RGB")
        rgb_img.save(img_path, "JPEG", quality=85)

        # Purge temporary screen snapshots older than 1h or exceeding 20 files
        try:
            cached_files = [
                os.path.join(cache_dir, f)
                for f in os.listdir(cache_dir)
                if f.startswith("screen_") and f.endswith(".jpg")
            ]
            cached_files.sort(key=lambda p: os.path.getmtime(p))
            now = time.time()
            if len(cached_files) > 20:
                for old_f in cached_files[:-20]:
                    try:
                        os.remove(old_f)
                    except OSError:
                        pass
        except Exception:
            pass

        return f"Successfully captured active screen snapshot saved to {img_path} (Dimensions: {img.size[0]}x{img.size[1]})."
    except Exception as e:
        logger.error("Screen capture tool error: %s", e)
        return f"Error capturing screen: {str(e)}"


def rewind_audio_transcript(seconds: int = 90) -> str:
    """
    Fetches the trailing audio buffer (default: 90 seconds) from the dual-channel
    recorder and generates a fast speech transcription.

    Args:
        seconds: Duration in seconds to rewind (between 10 and 120 seconds).
    """
    if _RECORDER_REF is None:
        return "Audio recorder is not currently active."

    try:
        sec = max(10, min(120, int(seconds)))
        audio_data = _RECORDER_REF.get_rewind_audio(seconds=sec)
        if len(audio_data) == 0:
            return f"No audio in the trailing {sec}-second buffer."

        # If Gemini client reference is registered, transcribe via fast flash model
        if _GEMINI_CLIENT_REF is not None:
            return _GEMINI_CLIENT_REF.transcribe_audio_buffer(audio_data, duration_sec=sec)
        else:
            return f"Extracted {len(audio_data)} audio samples ({sec}s trailing buffer). Transcriber ready."

    except Exception as e:
        logger.error("Rewind audio tool error: %s", e)
        return f"Error retrieving audio rewind: {str(e)}"


def append_to_notes(heading: str, markdown_content: str) -> str:
    """
    Appends a new formatted section or student question directly into the active
    lecture markdown notes file.

    Args:
        heading: Section header (e.g. 'Student Query: Convex Optimization')
        markdown_content: Formatted LaTeX markdown content to append.
    """
    if _NOTES_MANAGER_REF is None or not hasattr(_NOTES_MANAGER_REF, "session_file"):
        return "No active session notes manager initialized."

    session_file = _NOTES_MANAGER_REF.session_file
    if not session_file:
        return "No active session file specified in notes manager."

    clean_heading = " ".join(heading.split()).strip()[:150]
    if not clean_heading:
        clean_heading = "Lecture Note"

    try:
        timestamp_str = time.strftime("[%H:%M:%S]")
        entry = f"#### {clean_heading} {timestamp_str}\n\n{markdown_content.strip()}\n\n"

        with open(session_file, "a", encoding="utf-8") as f:
            f.write(entry)

        return f"Successfully appended '{clean_heading}' to session notes ({os.path.basename(session_file)})."
    except Exception as e:
        logger.error("Append to notes tool error: %s", e)
        return f"Error writing to notes: {str(e)}"


# Export list of callable tool functions for Gemini function calling
CHALK_DESKTOP_TOOLS = [
    read_local_file,
    capture_active_screen,
    rewind_audio_transcript,
    append_to_notes,
]

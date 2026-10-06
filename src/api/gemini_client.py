"""
src/api/gemini_client.py - Hybrid Gemini Pipeline for Chalk.
Integrates directly with Google AI Studio using the official google-genai SDK.
1. Live Chunks (Gemini Flash): High-frequency multimodal processing of VAD-trimmed stereo audio,
   perceptual slide keyframes, user scratchpad notes, reference PDFs, and <!-- CHUNK_STATE --> context chaining.
2. Master Synthesis (Gemini Pro): End-of-session synthesis producing executive summaries, unified LaTeX derivations,
   Anki Cloze study decks ({{c1::answer}}), and high-stakes exam warnings.
3. Interactive Copilot: Floating HUD assistant with local desktop function calling.
"""

import os
import io
import time
import logging
from typing import Optional, List, Tuple, Dict, Any
import numpy as np
from PIL import Image

from google import genai
from google.genai import types
from google.genai.errors import APIError

from src.security.key_manager import get_api_key
from src.engine.quota_manager import QuotaManager
from src.engine.session_state import ChunkState
from src.vision.slide_filter import SlideKeyframe
from src.audio.recorder import DualChannelAudioRecorder
from src.api.tools import CHALK_DESKTOP_TOOLS

logger = logging.getLogger("chalk.api.gemini")

DEFAULT_FLASH_MODEL = "gemini-2.5-flash"
DEFAULT_PRO_MODEL = "gemini-2.5-pro"
FALLBACK_FLASH_MODEL = "gemini-3.8-flash"
FALLBACK_PRO_MODEL = "gemini-3.1-pro-preview"


class GeminiLecturePipeline:
    """
    Direct client pipeline communicating with Google AI Studio without proxy servers.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        flash_model: str = DEFAULT_FLASH_MODEL,
        pro_model: str = DEFAULT_PRO_MODEL,
        quota_manager: Optional[QuotaManager] = None,
    ):
        self.api_key = api_key or get_api_key()
        self.flash_model = flash_model
        self.pro_model = pro_model
        self.quota_manager = quota_manager or QuotaManager()
        self._client: Optional[genai.Client] = None
        self._init_client()

    def _init_client(self):
        key = self.api_key or get_api_key()
        if key:
            self.api_key = key
            self._client = genai.Client(api_key=key)
            logger.info("Gemini pipeline initialized with BYOK key.")
        else:
            self._client = None
            logger.warning("Gemini pipeline initialized without API key (Standby).")

    def reload_key(self):
        """Reloads API key from OS keyring."""
        self._init_client()

    def _get_active_client(self) -> genai.Client:
        if self._client is None:
            self.reload_key()
        if self._client is None:
            raise ValueError("No Google AI Studio API key found in OS credential vault.")
        return self._client

    def process_live_chunk(
        self,
        stereo_audio: np.ndarray,
        keyframes: List[SlideKeyframe],
        user_scratchpad: str = "",
        reference_doc_text: Optional[str] = None,
        previous_chunk_state: Optional[ChunkState] = None,
        start_time_str: str = "[00:00]",
        end_time_str: str = "[15:00]",
    ) -> Tuple[str, ChunkState]:
        """
        Synthesizes a live lecture chunk using Gemini Flash:
        Ingests stereo audio (Left=Mic, Right=Loopback), slide keyframes, user notes,
        and context chaining state.
        """
        client = self._get_active_client()
        parts = []

        # 1. System Prompt & Instructions
        system_instruction = (
            "You are Chalk, an elite autonomous academic lecture engine and transcription mathematician. "
            "You are transcribing and structuring a university lecture in real time.\n\n"
            "INPUT CHANNELS:\n"
            "- Stereo Audio: Left Channel = Classroom/Microphone (professor voice & student acoustics). "
            "Right Channel = Computer System Audio (slides, video clips, remote Zoom/Teams audio).\n"
            "- Visual Slides: Unique keyframes extracted from the presentation with timestamp tags.\n"
            "- Student Scratchpad Notes: Real-time student notes to serve as the primary outline anchor.\n\n"
            "STRICT STRUCTURAL RULES:\n"
            "1. Use student scratchpad shorthand as the primary outline anchor and section hierarchy.\n"
            "2. Route in-room or remote student interruptions into structured callout blocks:\n"
            "   > ❓ **Student Question [MM:SS]:** <exact question or confusion>\n"
            "   > 💡 **Instructor Clarification:** <professor's explanation and resolution>\n"
            "3. Extract all mathematical formulas into clean LaTeX display blocks ($$...$$) or inline ($...$). "
            "   Defer variable subscripts and notation conventions strictly to the slide text to ensure zero drift.\n"
            "4. Provide rigorous, publication-grade academic prose with clear bullet points and derivations.\n"
            "5. You MUST terminate your response with the following exact metadata block:\n"
            "<!-- CHUNK_STATE\n"
            "Topic: <current topic name>\n"
            "Active_Variables: [<comma-separated defined mathematical variables>]\n"
            "Unresolved_Proofs: [<open questions or derivations left unfinished in this segment>]\n"
            "Primary_Speaker: <tone / speaker observations>\n"
            "-->\n"
        )

        # 2. Add Audio Part (WAV)
        if len(stereo_audio) > 0:
            wav_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(stereo_audio, sample_rate=16000)
            if wav_bytes:
                audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
                parts.append(audio_part)
                logger.info("Attached stereo audio payload (%d bytes, %.1fs)", len(wav_bytes), len(stereo_audio) / 16000)

        # 3. Add Slide Keyframes (JPEG)
        for idx, kf in enumerate(keyframes[:12]):  # Limit to 12 keyframes per chunk
            try:
                jpg_bytes = kf.to_jpeg_bytes()
                img_part = types.Part.from_bytes(data=jpg_bytes, mime_type="image/jpeg")
                parts.append(img_part)

                label_text = f"Slide Keyframe #{idx + 1} at timestamp {kf.timestamp_str}"
                if kf.ocr_text:
                    label_text += f"\n[Extracted Slide OCR Text]:\n{kf.ocr_text}"
                parts.append(label_text)
            except Exception as e:
                logger.warning("Error encoding slide keyframe %d: %s", idx, e)

        # 4. Context Chaining from previous chunk
        context_prompt = ""
        if previous_chunk_state:
            context_prompt = (
                f"PREVIOUS SEGMENT CONTEXT:\n"
                f"{previous_chunk_state.to_markdown_block()}\n\n"
            )

        # 5. User Scratchpad Notes
        scratchpad_prompt = ""
        if user_scratchpad and user_scratchpad.strip():
            scratchpad_prompt = (
                f"STUDENT SCRATCHPAD SHORTHAND (Primary Outline Anchor):\n"
                f"'''\n{user_scratchpad.strip()}\n'''\n\n"
            )

        # 6. Reference Document grounding
        reference_prompt = ""
        if reference_doc_text and reference_doc_text.strip():
            reference_prompt = (
                f"REFERENCE SLIDE DECK / SYLLABUS GROUNDING:\n"
                f"'''\n{reference_doc_text[:20000]}\n'''\n\n"
            )

        task_prompt = (
            f"{context_prompt}"
            f"{scratchpad_prompt}"
            f"{reference_prompt}"
            f"Segment Time Window: {start_time_str} to {end_time_str}.\n"
            f"Please transcribe and synthesize this lecture segment into rigorous LaTeX Markdown now."
        )
        parts.append(task_prompt)

        # 7. Model Execution with Fallback
        model_to_use = self.flash_model
        try:
            response = self._call_generate_content(
                client=client,
                model=model_to_use,
                contents=parts,
                system_instruction=system_instruction,
            )
        except Exception as e:
            err_str = str(e)
            if "not found" in err_str.lower() or "deprecated" in err_str.lower() or "404" in err_str:
                logger.warning("Model %s unavailable, falling back to %s", model_to_use, FALLBACK_FLASH_MODEL)
                model_to_use = FALLBACK_FLASH_MODEL
                response = self._call_generate_content(
                    client=client,
                    model=model_to_use,
                    contents=parts,
                    system_instruction=system_instruction,
                )
            else:
                raise

        output_text = response.text or ""

        # Track usage in Quota Manager
        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        self.quota_manager.record_usage(input_tokens=in_tokens, output_tokens=out_tokens)

        # Parse chunk state
        chunk_state = ChunkState.from_model_output(output_text, default_topic="Lecture Content")
        chunk_state.timestamp_range = f"[{start_time_str} - {end_time_str}]"

        return output_text, chunk_state

    def synthesize_master_lecture(
        self,
        full_notes_markdown: str,
        user_instructions: str = "",
    ) -> str:
        """
        Fires Gemini Pro master synthesis across the full concatenated markdown file.
        Produces:
        a) Executive summary of the entire session.
        b) Standardized formula proof derivations with unified LaTeX variables.
        c) Anki Study Deck formatted with Cloze deletion syntax ({{c1::answer}}).
        d) High-stakes exam warnings based on spoken instructor emphasis markers.
        """
        client = self._get_active_client()

        system_instruction = (
            "You are Chalk Master Synthesizer, an elite academic exam preparation AI. "
            "You take raw chunked lecture notes and synthesize a comprehensive, rigorous final study document.\n\n"
            "REQUIREMENTS:\n"
            "1. EXECUTIVE SUMMARY: High-level academic synthesis of the core principles taught.\n"
            "2. STANDARDIZED PROOF DERIVATIONS: Complete, rigorous mathematical derivations with unified LaTeX variables "
            "   resolving all open proofs.\n"
            "3. ANKI STUDY DECK: A dedicated section formatted for direct Anki import using Cloze deletion syntax ({{c1::answer}}). "
            "   Create at least 8-15 high-yield cloze cards covering formulas, definitions, and key distinctions.\n"
            "4. HIGH-STAKES EXAM WARNINGS: Explicitly flag concepts that the instructor emphasized as testable or common pitfalls.\n"
        )

        prompt = (
            f"FULL LECTURE NOTES TO DATE:\n\n"
            f"{full_notes_markdown}\n\n"
        )
        if user_instructions:
            prompt += f"ADDITIONAL STUDENT INSTRUCTIONS: {user_instructions}\n\n"
        prompt += "Synthesize the master study guide now."

        model_to_use = self.pro_model
        try:
            response = self._call_generate_content(
                client=client,
                model=model_to_use,
                contents=[prompt],
                system_instruction=system_instruction,
            )
        except Exception as e:
            err_str = str(e)
            if "not found" in err_str.lower() or "deprecated" in err_str.lower() or "404" in err_str:
                logger.warning("Model %s unavailable, falling back to %s", model_to_use, FALLBACK_PRO_MODEL)
                model_to_use = FALLBACK_PRO_MODEL
                response = self._call_generate_content(
                    client=client,
                    model=model_to_use,
                    contents=[prompt],
                    system_instruction=system_instruction,
                )
            else:
                raise

        output_text = response.text or ""

        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        self.quota_manager.record_usage(input_tokens=in_tokens, output_tokens=out_tokens)

        return output_text

    def transcribe_audio_buffer(self, audio_data: np.ndarray, duration_sec: int = 90) -> str:
        """Transcribes trailing audio buffer for the Rewind tool."""
        client = self._get_active_client()
        wav_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(audio_data, sample_rate=16000)
        if not wav_bytes:
            return "No audio data to transcribe."

        audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
        prompt = (
            f"Provide an exact, highly accurate verbatim transcript and brief summary of what was spoken in this "
            f"trailing {duration_sec}-second lecture audio buffer. Indicate whether it was professor speech or student questions."
        )

        try:
            response = self._call_generate_content(
                client=client,
                model=self.flash_model,
                contents=[audio_part, prompt],
            )
            return response.text or "No transcription produced."
        except Exception as e:
            logger.error("Audio rewind transcription failed: %s", e)
            return f"Transcription error: {str(e)}"

    def execute_copilot_query(
        self,
        prompt: str,
        attached_image: Optional[Image.Image] = None,
        attached_file_text: Optional[str] = None,
    ) -> str:
        """
        Executes an interactive query from the HUD Copilot with function calling.
        """
        client = self._get_active_client()
        parts = []

        if attached_image:
            bio = io.BytesIO()
            attached_image.convert("RGB").save(bio, format="JPEG", quality=85)
            parts.append(types.Part.from_bytes(data=bio.getvalue(), mime_type="image/jpeg"))

        if attached_file_text:
            parts.append(f"ATTACHED DOCUMENT CONTENT:\n{attached_file_text[:30000]}\n")

        parts.append(prompt)

        system_instruction = (
            "You are the Chalk Desktop Copilot assistant. You assist university students during lectures. "
            "You have access to local desktop tools: reading files, capturing the active screen, rewinding audio, "
            "and appending to notes. Use LaTeX for math ($...$). Be concise, sharp, and academically rigorous."
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=CHALK_DESKTOP_TOOLS,
        )

        response = client.models.generate_content(
            model=self.flash_model,
            contents=parts,
            config=config,
        )

        # Check for function calls
        if response.function_calls:
            for call in response.function_calls:
                fn_name = call.name
                fn_args = call.args or {}
                logger.info("Executing Copilot tool call: %s(%s)", fn_name, fn_args)

                # Match local tool function
                tool_fn = next((f for f in CHALK_DESKTOP_TOOLS if f.__name__ == fn_name), None)
                if tool_fn:
                    try:
                        tool_result = tool_fn(**fn_args)
                    except Exception as err:
                        tool_result = f"Tool execution failed: {err}"
                else:
                    tool_result = f"Unknown tool '{fn_name}'"

                # Feed function result back
                tool_content = [
                    types.Part.from_function_response(
                        name=fn_name,
                        response={"result": tool_result},
                    )
                ]
                followup = client.models.generate_content(
                    model=self.flash_model,
                    contents=tool_content,
                    config=config,
                )
                return followup.text or str(tool_result)

        return response.text or "Ready."

    def _call_generate_content(
        self,
        client: genai.Client,
        model: str,
        contents: list,
        system_instruction: Optional[str] = None,
    ):
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.2,
        )
        return client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

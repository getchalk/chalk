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
import re
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
from src.api.synthesis_pipeline import (
    LectureNoteBlock,
    LectureSynthesisResponse,
    validate_latex_syntax,
    render_blocks_to_markdown,
    render_synthesis_to_markdown,
    STRICT_MATH_SYNTHESIS_INSTRUCTION,
    SynthesisPipeline,
)

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
        self._tracked_files: List[Any] = []
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

    def upload_file(self, file: Any, mime_type: Optional[str] = None) -> Any:
        """
        Uploads media (e.g. large audio/video) to Google Files API and tracks it for lifecycle cleanup.
        """
        client = self._get_active_client()
        uploaded = client.files.upload(file=file, mime_type=mime_type)
        self._tracked_files.append(uploaded)
        file_name = getattr(uploaded, "name", str(uploaded))
        logger.info("Uploaded file to Google Files API: %s", file_name)
        return uploaded

    def delete_file(self, file_name_or_obj: Any) -> bool:
        """
        Deletes a file from Google Files API and removes it from the tracking list.
        """
        client = self._get_active_client()
        file_name = getattr(file_name_or_obj, "name", str(file_name_or_obj))
        try:
            client.files.delete(name=file_name)
            self._tracked_files = [f for f in self._tracked_files if getattr(f, "name", None) != file_name]
            logger.info("Deleted Google Files API resource: %s", file_name)
            return True
        except Exception as e:
            logger.warning("Failed to delete Google Files API resource %s: %s", file_name, e)
            return False

    def cleanup_tracked_files(self) -> None:
        """
        Deletes all currently tracked Google Files API resources to guarantee zero permanent cloud retention.
        """
        client = self._client
        if not client:
            return
        for f in list(self._tracked_files):
            file_name = getattr(f, "name", str(f))
            try:
                client.files.delete(name=file_name)
                logger.info("Cleaned up tracked file: %s", file_name)
            except Exception as e:
                logger.warning("Failed to clean up tracked file %s: %s", file_name, e)
        self._tracked_files.clear()

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
        use_structured_output: bool = False,
        tracked_files: Optional[List[Any]] = None,
    ) -> Tuple[str, ChunkState]:
        """
        Synthesizes a live lecture chunk using Gemini Flash:
        Ingests stereo audio (Left=Mic, Right=Loopback), slide keyframes, user notes,
        and context chaining state.
        """
        if use_structured_output:
            md, state, _ = self.process_live_chunk_structured(
                stereo_audio=stereo_audio,
                keyframes=keyframes,
                user_scratchpad=user_scratchpad,
                reference_doc_text=reference_doc_text,
                previous_chunk_state=previous_chunk_state,
                start_time_str=start_time_str,
                end_time_str=end_time_str,
                tracked_files=tracked_files,
            )
            return md, state

        client = self._get_active_client()
        parts = []

        # 1. System Prompt & Instructions (Granola-Style Augmented Shorthand & Interactive Audio Scrub)
        system_instruction = (
            "You are Chalk, an ambient cognitive presence engine and rigorous note synthesis partner. "
            "You capture and synthesize university lectures, technical architecture reviews, and high-velocity strategy meetings in real time.\n\n"
            "STRICT MATHEMATICAL INTEGRITY RULE:\n"
            f"{STRICT_MATH_SYNTHESIS_INSTRUCTION}\n\n"
            "INPUT CHANNELS:\n"
            "- Stereo Audio: Left Channel = Physical Microphone (presenter voice, in-room discussion). "
            "Right Channel = Computer System Audio (slides, video clips, remote attendee audio).\n"
            "- Visual Slides: Unique keyframes extracted from the presentation with timestamp tags.\n"
            "- User Scratchpad Shorthand: The user's real-time shorthand bullets and notes.\n\n"
            "GRANOLA-STYLE AUGMENTED SHORTHAND PRIORITY:\n"
            "1. Treat the user's manual scratchpad notes as the authoritative outline anchor. "
            "If the user jots a quick thought or shorthand bullet (e.g. '- prof emphasized risk models' or '- team agreed on Q3 rollout'), "
            "you MUST prioritize, flesh out, and weave that specific thought into the final synthesis using the surrounding audio transcript and slide content.\n"
            "2. Route audience or attendee interruptions into structured callout blocks:\n"
            "   > ❓ **Question [MM:SS]:** <exact question or confusion>\n"
            "   > 💡 **Clarification:** <speaker explanation and resolution>\n"
            "3. Format all spoken moments, topic shifts, and clarifications with interactive audio timestamp markers: "
            "[HH:MM:SS](chalk-audio://HH:MM:SS) (or [MM:SS](chalk-audio://MM:SS)) so the user can click to scrub audio later.\n"
            "4. Extract all mathematical formulas into clean LaTeX display blocks ($$...$$) or inline ($...$). "
            "   Defer notation strictly to the presentation slides to prevent variable drift.\n"
            "5. Provide calm, publication-grade prose with clear bullet points and derivations, matching the elegance of Notion and Apple Notes.\n"
            "6. You MUST terminate your response with the following exact metadata block:\n"
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
                tracked_files=tracked_files,
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
                    tracked_files=tracked_files,
                )
            else:
                raise

        output_text = response.text or ""

        # Track usage in Quota Manager
        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        self.quota_manager.record_usage(input_tokens=in_tokens, output_tokens=out_tokens)

        # Local KaTeX validation on display math blocks ($$...$$)
        def _sanitize_math_match(match):
            formula = match.group(1).strip()
            _, valid_lat = validate_latex_syntax(formula)
            return f"$$\n{valid_lat}\n$$"

        output_text = re.sub(r"\$\$(.*?)\$\$", _sanitize_math_match, output_text, flags=re.DOTALL)

        # Parse chunk state
        chunk_state = ChunkState.from_model_output(output_text, default_topic="Lecture Content")
        chunk_state.timestamp_range = f"[{start_time_str} - {end_time_str}]"

        return output_text, chunk_state

    def process_live_chunk_structured(
        self,
        stereo_audio: np.ndarray,
        keyframes: List[SlideKeyframe],
        user_scratchpad: str = "",
        reference_doc_text: Optional[str] = None,
        previous_chunk_state: Optional[ChunkState] = None,
        start_time_str: str = "[00:00]",
        end_time_str: str = "[15:00]",
        tracked_files: Optional[List[Any]] = None,
    ) -> Tuple[str, ChunkState, LectureSynthesisResponse]:
        """
        Synthesizes a live lecture chunk with typed JSON Structured Outputs (Pydantic schema).
        Enforces:
        - Structured JSON output conforming to LectureSynthesisResponse
        - Strict prompt instruction against hallucinated derivation steps
        - Local KaTeX syntax validation and repairing on all LaTeX formulas
        - Deterministic Obsidian/GitHub callout rendering
        - Google Files API lifecycle deletion in finally block
        """
        client = self._get_active_client()
        parts = []

        system_instruction = (
            "You are Chalk, an ambient cognitive presence engine and rigorous mathematical synthesis partner.\n\n"
            "STRICT MATHEMATICAL INTEGRITY RULE:\n"
            f"{STRICT_MATH_SYNTHESIS_INSTRUCTION}\n\n"
            "Synthesize this lecture segment into structured note blocks. "
            "For any theorem, definition, proof, remark, or example, populate the schema. "
            "Defer notation strictly to the presentation slides to prevent variable drift. "
            "Proofs must be step-by-step; unverified steps must be explicitly flagged as '[Lücke]'."
        )

        if len(stereo_audio) > 0:
            wav_bytes = DualChannelAudioRecorder.audio_to_wav_bytes(stereo_audio, sample_rate=16000)
            if wav_bytes:
                audio_part = types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
                parts.append(audio_part)

        for idx, kf in enumerate(keyframes[:12]):
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

        if previous_chunk_state:
            parts.append(f"PREVIOUS SEGMENT CONTEXT:\n{previous_chunk_state.to_markdown_block()}\n\n")
        if user_scratchpad and user_scratchpad.strip():
            parts.append(f"STUDENT SCRATCHPAD SHORTHAND:\n'''\n{user_scratchpad.strip()}\n'''\n\n")
        if reference_doc_text and reference_doc_text.strip():
            parts.append(f"REFERENCE SLIDES / SYLLABUS:\n'''\n{reference_doc_text[:20000]}\n'''\n\n")

        task_prompt = (
            f"Segment Time Window: {start_time_str} to {end_time_str}.\n"
            "Synthesize this lecture segment into typed JSON blocks now."
        )
        parts.append(task_prompt)

        model_to_use = self.flash_model
        try:
            response = self._call_generate_content(
                client=client,
                model=model_to_use,
                contents=parts,
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=LectureSynthesisResponse,
                tracked_files=tracked_files,
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
                    response_mime_type="application/json",
                    response_schema=LectureSynthesisResponse,
                    tracked_files=tracked_files,
                )
            else:
                raise

        output_text = response.text or "{}"

        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        self.quota_manager.record_usage(input_tokens=in_tokens, output_tokens=out_tokens)

        pipeline = SynthesisPipeline()
        rendered_md, chunk_state, response_obj = pipeline.process_and_render_synthesis(
            raw_output=output_text,
            timestamp_range=f"[{start_time_str} - {end_time_str}]",
        )

        return rendered_md, chunk_state, response_obj

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
            "STRICT MATHEMATICAL INTEGRITY RULE:\n"
            f"{STRICT_MATH_SYNTHESIS_INSTRUCTION}\n\n"
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

        # Validate display math blocks with local KaTeX validator
        def _sanitize_math_match(match):
            formula = match.group(1).strip()
            _, valid_lat = validate_latex_syntax(formula)
            return f"$$\n{valid_lat}\n$$"

        output_text = re.sub(r"\$\$(.*?)\$\$", _sanitize_math_match, output_text, flags=re.DOTALL)

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

    def synthesize_master_lecture_structured(
        self,
        full_notes_markdown: str,
        user_instructions: str = "",
        tracked_files: Optional[List[Any]] = None,
    ) -> Tuple[str, ChunkState, LectureSynthesisResponse]:
        """
        Synthesizes the complete session into typed JSON structured blocks (Pydantic schema).
        Enforces strict mathematical accuracy, local KaTeX validation, and zero cloud retention.
        """
        client = self._get_active_client()

        system_instruction = (
            "You are Chalk Master Synthesizer, an elite academic exam preparation AI. "
            "You synthesize full lecture notes into structured academic blocks.\n\n"
            "STRICT MATHEMATICAL INTEGRITY RULE:\n"
            f"{STRICT_MATH_SYNTHESIS_INSTRUCTION}\n\n"
            "Produce comprehensive theorems, definitions, proofs, remarks, and examples. "
            "Proofs must be step-by-step; unverified steps must be explicitly flagged as '[Lücke]'."
        )

        prompt = f"FULL LECTURE NOTES TO DATE:\n\n{full_notes_markdown}\n\n"
        if user_instructions:
            prompt += f"ADDITIONAL STUDENT INSTRUCTIONS: {user_instructions}\n\n"
        prompt += "Synthesize the master study guide into typed JSON blocks now."

        model_to_use = self.pro_model
        try:
            response = self._call_generate_content(
                client=client,
                model=model_to_use,
                contents=[prompt],
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=LectureSynthesisResponse,
                tracked_files=tracked_files,
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
                    response_mime_type="application/json",
                    response_schema=LectureSynthesisResponse,
                    tracked_files=tracked_files,
                )
            else:
                raise

        output_text = response.text or "{}"

        usage = getattr(response, "usage_metadata", None)
        in_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
        out_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
        self.quota_manager.record_usage(input_tokens=in_tokens, output_tokens=out_tokens)

        pipeline = SynthesisPipeline()
        rendered_md, chunk_state, response_obj = pipeline.process_and_render_synthesis(
            raw_output=output_text,
            timestamp_range="[Master Synthesis]",
        )

        return rendered_md, chunk_state, response_obj

    def _call_generate_content(
        self,
        client: genai.Client,
        model: str,
        contents: list,
        system_instruction: Optional[str] = None,
        response_mime_type: Optional[str] = None,
        response_schema: Optional[Any] = None,
        tracked_files: Optional[List[Any]] = None,
    ):
        config_kwargs: Dict[str, Any] = {
            "system_instruction": system_instruction,
            "temperature": 0.2,
        }
        if response_mime_type:
            config_kwargs["response_mime_type"] = response_mime_type
        if response_schema:
            config_kwargs["response_schema"] = response_schema

        config = types.GenerateContentConfig(**config_kwargs)

        files_to_cleanup = list(tracked_files) if tracked_files else []
        for item in contents:
            if hasattr(item, "name") and (hasattr(item, "uri") or hasattr(item, "mime_type")):
                if item not in files_to_cleanup:
                    files_to_cleanup.append(item)

        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        finally:
            # Lifecycle Cleanup: Zero permanent cloud retention
            for f in files_to_cleanup:
                fname = getattr(f, "name", str(f))
                try:
                    client.files.delete(name=fname)
                    logger.info("Deleted Google Files API resource in finally block: %s", fname)
                except Exception as e:
                    logger.warning("Failed to delete Google Files API resource %s: %s", fname, e)
                if f in self._tracked_files:
                    self._tracked_files.remove(f)

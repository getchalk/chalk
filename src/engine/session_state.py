"""
src/engine/session_state.py - Context Chaining & Notes Storage.
Manages the <!-- CHUNK_STATE --> context chain between consecutive lecture segments,
incremental appending to ./Notes/Lecture_{YYYY-MM-DD}.md, and offline staging queues.
"""

import os
import re
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

logger = logging.getLogger("chalk.engine.state")


@dataclass
class ChunkState:
    """Carries forward context across elastic chunk boundaries."""
    topic: str = "Introductory Material"
    active_variables: List[str] = field(default_factory=list)
    unresolved_proofs: List[str] = field(default_factory=list)
    primary_speaker: str = "Instructor"
    chunk_index: int = 0
    timestamp_range: str = "[00:00 - 00:00]"

    def to_markdown_block(self) -> str:
        """Formats the state into standard Chalk markdown comment block."""
        vars_str = ", ".join(self.active_variables) if self.active_variables else "none"
        proofs_str = ", ".join(self.unresolved_proofs) if self.unresolved_proofs else "none"
        return (
            f"<!-- CHUNK_STATE\n"
            f"Topic: {self.topic}\n"
            f"Active_Variables: [{vars_str}]\n"
            f"Unresolved_Proofs: [{proofs_str}]\n"
            f"Primary_Speaker: {self.primary_speaker}\n"
            f"-->"
        )

    @classmethod
    def from_model_output(cls, text: str, chunk_index: int = 0, default_topic: str = "General") -> "ChunkState":
        """Parses the <!-- CHUNK_STATE ... --> block from Gemini output."""
        pattern = r"<!--\s*CHUNK_STATE\s*(.*?)\s*-->"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)

        if not match:
            return cls(topic=default_topic, chunk_index=chunk_index)

        block_content = match.group(1)
        topic = default_topic
        active_vars = []
        unresolved = []
        speaker = "Instructor"

        for line in block_content.splitlines():
            line = line.strip()
            if line.startswith("Topic:"):
                topic = line.replace("Topic:", "").strip()
            elif line.startswith("Active_Variables:"):
                raw = line.replace("Active_Variables:", "").strip().strip("[]")
                active_vars = [v.strip() for v in raw.split(",") if v.strip() and v.strip() != "none"]
            elif line.startswith("Unresolved_Proofs:"):
                raw = line.replace("Unresolved_Proofs:", "").strip().strip("[]")
                unresolved = [p.strip() for p in raw.split(",") if p.strip() and p.strip() != "none"]
            elif line.startswith("Primary_Speaker:"):
                speaker = line.replace("Primary_Speaker:", "").strip()

        return cls(
            topic=topic,
            active_variables=active_vars,
            unresolved_proofs=unresolved,
            primary_speaker=speaker,
            chunk_index=chunk_index,
        )


def slugify_topic(topic: str) -> str:
    """Converts a topic string into a clean lowercase filename slug."""
    if not topic:
        return "lecture_notes"
    clean = topic.strip().lower()
    clean = re.sub(r"[^\w\s-]", "", clean)
    clean = re.sub(r"[\s_-]+", "_", clean).strip("_")
    return clean or "lecture_notes"


class SessionNotesManager:
    """
    Handles file I/O for lecture markdown notes and context chaining.
    Supports standard ./Notes/Lecture_{YYYY-MM-DD}.md fallback
    and smart Obsidian Vault auto-organization (<Vault>/Chalk/<YYYY-MM-DD>_<slug>.md)
    with YAML frontmatter.
    """

    def __init__(
        self,
        notes_dir: Optional[str] = None,
        session_id: Optional[str] = None,
        topic: Optional[str] = None,
        is_obsidian: Optional[bool] = None,
    ):
        from src.engine.config import get_obsidian_vault_path

        now = datetime.now()
        self.session_id = session_id or "default"
        self.session_date_str = now.strftime("%Y-%m-%d")
        self.session_time_str = now.strftime("%H%M")
        self.topic = topic or "Lecture Notes"

        vault_path = get_obsidian_vault_path()

        # Resolve robust default notes directory (~/Documents/Chalk instead of CWD)
        docs_dir = os.path.expanduser("~/Documents/Chalk")
        fallback_dir = os.path.expanduser("~/.chalk/notes")

        if is_obsidian is not None:
            self.is_obsidian = is_obsidian
            if notes_dir is not None:
                self.notes_dir = os.path.abspath(notes_dir)
            elif vault_path and os.path.isdir(vault_path):
                self.notes_dir = os.path.join(vault_path, "Chalk")
            else:
                self.notes_dir = docs_dir
        elif notes_dir is not None:
            self.notes_dir = os.path.abspath(notes_dir)
            self.is_obsidian = bool(vault_path and (os.path.abspath(vault_path) in self.notes_dir))
        elif vault_path and os.path.isdir(vault_path):
            self.notes_dir = os.path.join(vault_path, "Chalk")
            self.is_obsidian = True
        else:
            self.notes_dir = docs_dir
            self.is_obsidian = False

        try:
            os.makedirs(self.notes_dir, exist_ok=True)
        except Exception as dir_err:
            logger.warning("Could not create notes directory %s (%s). Using fallback %s", self.notes_dir, dir_err, fallback_dir)
            self.notes_dir = fallback_dir
            os.makedirs(self.notes_dir, exist_ok=True)

        if self.is_obsidian:
            slug = slugify_topic(self.topic)
            self.session_file = os.path.join(self.notes_dir, f"{self.session_date_str}_{slug}.md")
        else:
            if self.session_id and self.session_id != "default":
                short_id = self.session_id[-8:] if len(self.session_id) > 8 else self.session_id
                self.session_file = os.path.join(self.notes_dir, f"Lecture_{self.session_date_str}_{self.session_time_str}_{short_id}.md")
            else:
                self.session_file = os.path.join(self.notes_dir, f"Lecture_{self.session_date_str}_{self.session_time_str}.md")

        self.last_state = ChunkState()
        self.chunk_count = 0
        self._init_session_file()

    def _init_session_file(self):
        """Initializes the markdown notes file with header if new."""
        if not os.path.exists(self.session_file):
            now_iso = datetime.now().astimezone().isoformat()
            safe_topic = self.topic.replace('\\', '\\\\').replace('"', '\\"')
            safe_sid = self.session_id.replace('\\', '\\\\').replace('"', '\\"')
            if self.is_obsidian:
                header = (
                    f"---\n"
                    f"tags: [chalk, lecture, study]\n"
                    f"date: {self.session_date_str}\n"
                    f"created: {now_iso}\n"
                    f'topic: "{safe_topic}"\n'
                    f'audio_session: "{safe_sid}"\n'
                    f"---\n\n"
                    f"# Chalk Lecture Notes — {self.session_date_str}\n\n"
                    f"*Generated autonomously by Chalk Desktop Lecture Engine*\n\n"
                    f"---\n\n"
                )
            else:
                header = (
                    f"# Chalk Lecture Notes — {self.session_date_str}\n\n"
                    f"*Generated autonomously by Chalk Desktop Lecture Engine*\n\n"
                    f"---\n\n"
                )
            try:
                with open(self.session_file, "w", encoding="utf-8") as f:
                    f.write(header)
                logger.info("Initialized session notes file: %s", self.session_file)
            except Exception as e:
                logger.error("Failed to initialize session notes: %s", e)


    def append_chunk_notes(self, markdown_text: str, start_time_str: str, end_time_str: str) -> ChunkState:
        """
        Appends a newly synthesized chunk to the session markdown notes file
        and updates context chain state.
        """
        self.chunk_count += 1
        time_tag = f"### [Segment {self.chunk_count:02d}]: {start_time_str} – {end_time_str}\n\n"

        # Parse model's emitted chunk state
        new_state = ChunkState.from_model_output(markdown_text, chunk_index=self.chunk_count)
        new_state.timestamp_range = f"[{start_time_str} - {end_time_str}]"
        self.last_state = new_state

        full_entry = f"{time_tag}{markdown_text}\n\n---\n\n"

        try:
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(full_entry)
            logger.info("Appended chunk %d to %s", self.chunk_count, self.session_file)
        except Exception as e:
            logger.error("Failed to append chunk to notes file: %s", e)

        return new_state

    def append_master_synthesis(self, master_markdown: str):
        """Appends the final Gemini Pro master synthesis to the session file."""
        heading = (
            "\n\n# Master Synthesis & Exam Preparation\n\n"
            "*Synthesized across all lecture segments via Gemini Pro*\n\n"
            "---\n\n"
        )
        try:
            with open(self.session_file, "a", encoding="utf-8") as f:
                f.write(heading + master_markdown + "\n")
            logger.info("Appended master synthesis to %s", self.session_file)
        except Exception as e:
            logger.error("Failed to append master synthesis: %s", e)

    def read_full_notes(self) -> str:
        """Reads the full session notes markdown for master synthesis ingestion."""
        if not os.path.exists(self.session_file):
            return ""
        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error("Failed to read session notes: %s", e)
            return ""


class OfflineStagingQueue:
    """
    Buffers uncommitted lecture segments when network dropouts or HTTP 429
    errors occur, preventing data loss.
    """

    def __init__(self, staging_dir: str = os.path.expanduser("~/.chalk/staging")):
        self.staging_dir = staging_dir
        os.makedirs(self.staging_dir, exist_ok=True)
        self.queue: List[Dict[str, Any]] = []

    def stage_chunk(self, audio_data, keyframes, meta: dict):
        self.queue.append({
            "audio": audio_data,
            "keyframes": keyframes,
            "meta": meta,
            "staged_at": time.time(),
        })
        logger.warning("Chunk staged in offline queue (depth: %d)", len(self.queue))

    def pop_staged_chunk(self) -> Optional[Dict[str, Any]]:
        if self.queue:
            return self.queue.pop(0)
        return None

    def has_staged_items(self) -> bool:
        return len(self.queue) > 0

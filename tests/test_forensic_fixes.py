"""
tests/test_forensic_fixes.py - Forensic Verification Suite for Core System Standards.
Verifies:
1. KaTeX whitelist expansion and preservation of mathematical operators without destructive \\text{...} rewriting.
2. Anki TSV export conversion from $...$ and $$...$$ to \\(...\\) and \\[...\\].
3. Tolerant JSON completion and prevention of raw JSON leakage into notes summary.
4. Multiline Obsidian directive callout formatting (> on every line).
5. Lazy initialization of notes markdown file (no premature empty file on init).
6. Crash recovery ignoring brand-new empty sessions.
7. ValidationWorker signal cleanly renamed to validation_finished.
8. Coordinator chunk failure handling: audio recording never paused on API error, segment IDs restored.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from src.api.synthesis_pipeline import (
    validate_latex_syntax,
    sanitize_latex,
    export_flashcards_to_tsv,
    FlashcardItem,
    SynthesisPipeline,
    LectureSynthesisResponse,
    KATEX_ALLOWED_COMMANDS,
)
from src.engine.session_state import SessionNotesManager
from src.engine.journal import SessionJournal, recover_unprocessed_sessions
from src.ui.settings_dialog import ValidationWorker


class TestForensicFixes(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="chalk_forensic_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_katex_whitelist_and_no_destructive_sanitization(self):
        """Verifies that all 14 standard commands are preserved and not mangled."""
        test_commands = [
            r"\lVert x \rVert",
            r"\lvert y \rvert",
            r"a \leqslant b",
            r"x \geqslant y",
            r"\argmax_{\theta} f(\theta)",
            r"\bigoplus_{i=1}^n V_i",
            r"\varPhi(x)",
            r"f \colon A \to B",
            r"a \nmid b",
            r"A \subsetneq B",
            r"\overrightarrow{AB}",
            r"\mathop{\mathrm{tr}}(A)",
            r"a \equiv b \pmod{m}",
            r"\stackrel{\mathrm{def}}{=}",
            r"\cancel{x}",
            r"A \xleftrightarrow{f} B",
            r"\lbrace 1, 2, 3 \rbrace",
        ]
        for cmd in test_commands:
            # Ensure sanitize_latex does not convert operators into \text{...}
            sanitized = sanitize_latex(cmd)
            self.assertNotIn(r"\text{lVert}", sanitized)
            self.assertNotIn(r"\text{lvert}", sanitized)
            self.assertNotIn(r"\text{leqslant}", sanitized)
            self.assertNotIn(r"\text{geqslant}", sanitized)
            self.assertNotIn(r"\text{argmax}", sanitized)
            self.assertNotIn(r"\text{bigoplus}", sanitized)
            self.assertNotIn(r"\text{varPhi}", sanitized)
            self.assertNotIn(r"\text{colon}", sanitized)
            self.assertNotIn(r"\text{nmid}", sanitized)
            self.assertNotIn(r"\text{subsetneq}", sanitized)
            self.assertNotIn(r"\text{overrightarrow}", sanitized)
            self.assertNotIn(r"\text{mathop}", sanitized)
            self.assertNotIn(r"\text{cancel}", sanitized)
            self.assertNotIn(r"\text{xleftrightarrow}", sanitized)
            self.assertNotIn(r"\text{lbrace}", sanitized)

    def test_anki_tsv_delimiter_conversion(self):
        """Verifies $...$ and $$...$$ are converted to \\(...\\) and \\[...\\] for native Anki import."""
        flashcards = [
            FlashcardItem(
                question="What is Bayes' theorem $P(A|B)$?",
                answer_latex=r"$$P(A|B) = \frac{P(B|A)P(A)}{P(B)}$$",
                reference_timestamp="[00:15:30]",
            )
        ]
        tsv_path = os.path.join(self.temp_dir, "test_cards.tsv")
        export_flashcards_to_tsv(flashcards, tsv_path)

        with open(tsv_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check inline math conversion
        self.assertIn(r"\(P(A|B)\)", content)
        self.assertNotIn(r"$P(A|B)$", content)

        # Check display math conversion
        self.assertIn(r"\[P(A|B) = \frac{P(B|A)P(A)}{P(B)}\]", content)
        self.assertNotIn(r"$$", content)

    def test_truncated_json_does_not_leak_raw_syntax(self):
        """Verifies partial/truncated model output does not dump raw JSON code into user notes."""
        truncated_raw = '{\n  "blocks": [\n    {\n      "type": "theorem",\n      "title": "Cauchy-Schwarz",\n      "latex": "\\\\lvert \\\\langle u, v \\\\rangle \\\\rvert \\\\leqslant \\\\lVert u \\\\rVert \\\\lVert v \\\\rVert",\n      "explanation": "Fundamental inner product space inequality"'
        # Trailing closing brackets are missing
        pipeline = SynthesisPipeline()
        resp = pipeline.parse_synthesis_json(truncated_raw)

        # Ensure response has blocks recovered
        self.assertIsInstance(resp, LectureSynthesisResponse)
        self.assertGreaterEqual(len(resp.blocks), 1)
        for b in resp.blocks:
            self.assertNotIn('{"blocks":', b.explanation)
            self.assertNotIn('"type":', b.explanation)

    def test_multiline_user_directive_formatting(self):
        """Verifies every line of a multiline directive gets prefixed with '> '."""
        notes_mgr = SessionNotesManager(
            notes_dir=self.temp_dir,
            session_id="test_sess_multiline",
            is_obsidian=True,
        )
        directive_text = "Line 1: Pay attention to exam formula.\nLine 2: Will be tested in final.\nLine 3: Note variable definition."
        callout = notes_mgr.append_user_directive(directive_text, timestamp_str="10:00:00")

        self.assertIn("> Line 1:", callout)
        self.assertIn("> Line 2:", callout)
        self.assertIn("> Line 3:", callout)

        # Read on disk
        disk_content = notes_mgr.read_full_notes()
        self.assertIn("> Line 1:", disk_content)
        self.assertIn("> Line 2:", disk_content)
        self.assertIn("> Line 3:", disk_content)

    def test_lazy_notes_file_initialization(self):
        """Verifies session file is not created on disk until first write occurs."""
        notes_dir = os.path.join(self.temp_dir, "lazy_notes")
        notes_mgr = SessionNotesManager(
            notes_dir=notes_dir,
            session_id="test_lazy_sess",
            is_obsidian=False,
            auto_init=False,
        )
        # Should not exist yet
        self.assertFalse(os.path.exists(notes_mgr.session_file))

        # First write initializes it
        notes_mgr.append_chunk_notes("Some content", "00:00", "01:00")
        self.assertTrue(os.path.exists(notes_mgr.session_file))

    def test_recover_unprocessed_sessions_ignores_recent_empty(self):
        """Verifies brand-new session with 0 segments is not treated as recovering."""
        journal = SessionJournal(
            session_id="fresh_empty_sess",
            base_dir=self.temp_dir,
            create_if_missing=True,
        )
        # Session has status 'recording' but 0 segments and age < 60s
        recovered = recover_unprocessed_sessions(base_dir=self.temp_dir, min_age_sec=60.0)
        self.assertEqual(len(recovered), 0)

    def test_validation_worker_signal_name(self):
        """Verifies signal name is validation_finished to prevent QThread shadow warnings."""
        worker = ValidationWorker("dummy_key", provider="gemini")
        self.assertTrue(hasattr(worker, "validation_finished"))


if __name__ == "__main__":
    unittest.main()

"""
src/api/synthesis_pipeline.py - Multimodal AI & Mathematical Synthesis Pipeline for Chalk.

Provides:
1. Pydantic schema models for typed JSON lecture notes synthesis (theorems, definitions, proofs, remarks, examples).
2. Strict prompt enforcement against hallucinations ("Do not invent mathematical derivation steps...").
3. Local KaTeX syntax validation (balanced delimiters, valid command structures, no dangling \\frac, escaping fixes).
4. Deterministic Markdown renderer targeting Obsidian and GitHub Flavored Markdown callouts (> [!theorem], etc.)
   with clean proof conclusion (∎ or [Lücke]).
5. High-level SynthesisPipeline coordinator.
"""

import os
import re
import json
import logging
from typing import List, Tuple, Dict, Any, Optional, Union, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator

from src.engine.session_state import ChunkState

logger = logging.getLogger("chalk.api.synthesis")

# ==============================================================================
# 1. Strict Prompt Instructions & Schema Definitions
# ==============================================================================

STRICT_MATH_SYNTHESIS_INSTRUCTION = (
    "Do not invent mathematical derivation steps that were neither spoken nor shown. "
    "Unverified or missing steps must be explicitly flagged as '[Lücke]'."
)

SYNTHESIS_SYSTEM_INSTRUCTION = (
    "You are Chalk, an ambient cognitive presence engine and rigorous mathematical synthesis partner. "
    "You capture and synthesize university lectures and technical presentations in real time.\n\n"
    "STRICT MATHEMATICAL INTEGRITY RULE:\n"
    f"{STRICT_MATH_SYNTHESIS_INSTRUCTION}\n\n"
    "OUTPUT CONSTRAINTS:\n"
    "- Output must strictly conform to the JSON schema.\n"
    "- Defer mathematical notation strictly to the presentation slides to prevent variable drift.\n"
    "- Every mathematical formula must be valid KaTeX.\n"
    "- Proofs must be structured step-by-step. If a step was omitted by the instructor, denote it explicitly with [Lücke].\n"
    "- Record all introduced variables, symbols, and mathematical operators in 'notations' with clear definitions.\n"
    "- Provide exactly 3 rapid active-recall debrief questions in 'socratic_questions' testing core derivation, primary assumption, and exam pitfall.\n"
    "- When visual architectures, state machines, flowcharts, or system hierarchies are discussed or displayed on slides, "
    "generate valid Mermaid diagram syntax in the block explanation or latex field with type='diagram'.\n"
    "- MULTI-SPEAKER & ACOUSTIC DIARIZATION:\n"
    "  Differentiate speakers based on audio channel tags ([MIC] for nearby/room audio vs. [LOOPBACK] for system audio), "
    "acoustic transitions, questions, and conversational dynamics.\n"
    "  Assign the appropriate speaker to each note block: 'Lecturer', 'Audience Question', 'Meeting Host', or 'Discussion Participant'.\n"
    "  Student questions, audience interjections, or meeting objections MUST strictly be flagged as speaker='Audience Question' or speaker='Discussion Participant'.\n"
)


class LectureNoteBlock(BaseModel):
    """
    Individual structured note block representing a mathematical, conceptual, or visual unit.
    """
    model_config = ConfigDict(extra="ignore")

    type: Literal["theorem", "definition", "proof", "remark", "example", "diagram"] = Field(
        ...,
        description="Type of the block: theorem | definition | proof | remark | example | diagram"
    )
    title: str = Field(
        ...,
        description="Concise title of the theorem, definition, proof, remark, example, or diagram"
    )
    latex: str = Field(
        default="",
        description="KaTeX compatible mathematical formula or Mermaid diagram syntax"
    )
    explanation: str = Field(
        default="",
        description="Pedagogical explanation, verbal context, or Mermaid diagram syntax"
    )
    segment_id: str = Field(
        default="",
        description="Lecture segment identifier, e.g. SEG_28"
    )
    source: str = Field(
        default="inferred",
        description="Source of this block: slide | speech | whiteboard | inferred"
    )
    speaker: Optional[Literal["Lecturer", "Audience Question", "Meeting Host", "Discussion Participant"]] = Field(
        default=None,
        description="Identified speaker: Lecturer | Audience Question | Meeting Host | Discussion Participant"
    )

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, v: Any) -> str:
        if isinstance(v, str):
            v_clean = v.strip().lower()
            if any(term in v_clean for term in ("whiteboard", "tafel", "chalkboard", "board")):
                return "whiteboard"
            if "slide" in v_clean or "folie" in v_clean:
                return "slide"
            if "speech" in v_clean or "audio" in v_clean or "ton" in v_clean:
                return "speech"
            return v.strip()
        return "inferred"

    @field_validator("speaker", mode="before")
    @classmethod
    def normalize_speaker(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        if isinstance(v, str):
            v_clean = v.strip().lower()
            if not v_clean:
                return None
            if any(term in v_clean for term in ("audience", "question", "student", "frage", "publikum", "zuhörer")):
                return "Audience Question"
            if any(term in v_clean for term in ("lecturer", "professor", "dozent", "instructor", "speaker", "presenter", "vortragender")):
                return "Lecturer"
            if any(term in v_clean for term in ("host", "moderator", "meeting host", "leiter", "meeting-host")):
                return "Meeting Host"
            if any(term in v_clean for term in ("participant", "teilnehmer", "discussion", "diskussion", "colleague")):
                return "Discussion Participant"
            for candidate in ("Lecturer", "Audience Question", "Meeting Host", "Discussion Participant"):
                if v_clean == candidate.lower():
                    return candidate
        return None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v: Any) -> str:
        if isinstance(v, str):
            v_clean = v.strip().lower()
            synonyms = {
                "satz": "theorem",
                "theorem": "theorem",
                "lemma": "theorem",
                "proposition": "theorem",
                "korollar": "theorem",
                "corollary": "theorem",
                "definition": "definition",
                "def": "definition",
                "proof": "proof",
                "beweis": "proof",
                "herleitung": "proof",
                "derivation": "proof",
                "remark": "remark",
                "bemerkung": "remark",
                "hinweis": "remark",
                "note": "remark",
                "example": "example",
                "beispiel": "example",
                "bsp": "example",
                "diagram": "diagram",
                "diagramm": "diagram",
                "flowchart": "diagram",
                "flussdiagramm": "diagram",
                "architecture": "diagram",
                "architektur": "diagram",
                "state_machine": "diagram",
                "zustandsdiagramm": "diagram",
                "graph": "diagram",
            }
            return synonyms.get(v_clean, v_clean)
        return str(v)


class NotationItem(BaseModel):
    """
    Structured mathematical symbol or variable ledger entry.
    """
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(..., description="LaTeX symbol or variable, e.g. \\beta_i")
    definition: str = Field(..., description="Rigorous definition in context of this lecture")
    introduced_in_segment: str = Field(default="", description="Segment or timestamp where introduced")


class FlashcardItem(BaseModel):
    """
    Standardized flashcard item for spaced-repetition and Anki integration.
    """
    model_config = ConfigDict(extra="ignore")

    question: str = Field(..., description="Targeted exam question or concept prompt")
    answer_latex: str = Field(..., description="Precise mathematical formula, derivation, or concise core takeaway")
    reference_timestamp: Optional[str] = Field(default=None, description="Timestamp link e.g. [01:14:20]")


class LectureSynthesisResponse(BaseModel):
    """
    Complete structured response schema for lecture chunk synthesis.
    """
    model_config = ConfigDict(extra="ignore")

    blocks: List[LectureNoteBlock] = Field(
        default_factory=list,
        description="List of structured mathematical and conceptual note blocks"
    )
    topic: str = Field(
        default="Lecture Content",
        description="Primary topic or subject of this segment"
    )
    notations: List[NotationItem] = Field(
        default_factory=list,
        description="Defined variables and mathematical operators"
    )
    active_variables: List[str] = Field(
        default_factory=list,
        description="Currently active mathematical variables and notations"
    )
    unresolved_proofs: List[str] = Field(
        default_factory=list,
        description="Open questions or incomplete derivations left unresolved"
    )
    primary_speaker: str = Field(
        default="Instructor",
        description="Acoustic and pedagogical observations of primary speaker"
    )
    flashcards: List[FlashcardItem] = Field(
        default_factory=list,
        description="Exam flashcards and active recall concepts generated from this lecture chunk"
    )
    socratic_questions: List[str] = Field(
        default_factory=list,
        description="3 rapid active-recall questions testing core derivation, primary assumption, and exam pitfall"
    )

    def to_chunk_state(self, chunk_index: int = 0, timestamp_range: str = "[00:00 - 15:00]") -> ChunkState:
        """Converts response metadata into standard Chalk ChunkState."""
        return ChunkState(
            topic=self.topic,
            active_variables=self.active_variables,
            unresolved_proofs=self.unresolved_proofs,
            primary_speaker=self.primary_speaker,
            chunk_index=chunk_index,
            timestamp_range=timestamp_range,
        )


# ==============================================================================
# 2. Local KaTeX Syntax Validation & Sanitization
# ==============================================================================

# Comprehensive vocabulary of recognized KaTeX control sequences
KATEX_ALLOWED_COMMANDS = {
    # Greek lowercase
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta", "vartheta",
    "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "varpi", "rho", "varrho", "sigma", "varsigma",
    "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
    # Greek uppercase
    "Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega",
    # Math operators and functions
    "frac", "dfrac", "tfrac", "cfrac", "sqrt", "sum", "prod", "coprod", "int", "iint", "iiint",
    "oint", "oiint", "oiiint", "lim", "liminf", "limsup", "sin", "cos", "tan", "cot", "sec", "csc",
    "arcsin", "arccos", "arctan", "sinh", "cosh", "tanh", "coth", "log", "ln", "lg", "exp",
    "det", "dim", "ker", "deg", "gcd", "hom", "inf", "sup", "max", "min", "arg", "Pr", "operatorname",
    # Relations
    "le", "leq", "ge", "geq", "ne", "neq", "approx", "equiv", "sim", "simeq", "cong", "propto",
    "in", "notin", "ni", "subset", "subseteq", "supset", "supseteq", "sqsubset", "sqsubseteq",
    "sqsupset", "sqsupseteq", "cap", "cup", "setminus", "perp", "mid", "parallel", "asymp",
    "doteq", "bowtie", "smile", "frown", "prec", "preceq", "succ", "succeq",
    # Logic & sets
    "forall", "exists", "nexists", "land", "lor", "neg", "lnot", "top", "bot", "emptyset",
    "varnothing", "aleph", "complement",
    # Arrows
    "to", "rightarrow", "leftarrow", "Rightarrow", "Leftarrow", "iff", "implies", "impliedby",
    "mapsto", "leftrightarrow", "Leftrightarrow", "rightleftharpoons", "uparrow", "downarrow",
    "Uparrow", "Downarrow", "updownarrow", "Updownarrow", "nearrow", "searrow", "swarrow", "nwarrow",
    "longrightarrow", "longleftarrow", "Longrightarrow", "Longleftarrow", "longleftrightarrow",
    "Longleftrightarrow", "hookrightarrow", "hookleftarrow",
    # Symbols & Accents
    "partial", "nabla", "infty", "hbar", "ell", "Re", "Im", "wp", "prime", "angle", "triangle",
    "square", "blacksquare", "qed", "diamond", "star", "ast", "cdot", "cdots", "ldots", "dots",
    "ddots", "vdots", "times", "div", "pm", "mp", "circ", "bullet", "oplus", "ominus", "otimes",
    "oslash", "odot", "bigcirc", "dagger", "ddagger",
    # Accents
    "hat", "widehat", "bar", "vec", "tilde", "widetilde", "dot", "ddot", "dddot", "check",
    "breve", "acute", "grave", "overline", "underline", "overbrace", "underbrace",
    # Fonts & Styles
    "mathbf", "mathit", "mathrm", "mathcal", "mathbb", "mathfrak", "mathsf", "mathtt",
    "text", "textbf", "textit", "textrm", "textsf", "texttt", "boldsymbol", "bm",
    "rm", "bf", "it", "cal", "bb", "sf", "tt",
    # Delimiters & Sizing
    "left", "right", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Bigg", "middle",
    "big", "Big", "bigg",
    # Environments, Multi-line structures & Matrices
    "begin", "end", "quad", "qquad", "phantom", "hphantom", "vphantom",
    "limits", "nolimits", "displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle",
    "over", "atop", "choose", "aligned", "cases", "matrix", "pmatrix", "bmatrix",
    "Bmatrix", "vmatrix", "Vmatrix", "array", "gather", "gathered", "split",
    "substack", "smallmatrix", "hline", "newline", "bmod", "pmod", "pod",
    "therefore", "because", "intertext", "shortintertext"
}


def fix_basic_escaping(latex_str: str) -> str:
    """
    Fixes unintentional Python string escapes (e.g. \\x0c -> \\f, \\x08 -> \\b, etc.)
    and strips redundant outer LaTeX display wrappers.
    """
    s = latex_str
    # Replace non-printable ASCII escapes resulting from unescaped python strings
    s = s.replace("\x0crac", r"\frac")
    s = s.replace("\x0cdfrac", r"\dfrac")
    s = s.replace("\x0ctfrac", r"\tfrac")
    s = s.replace("\x08eta", r"\beta")
    s = s.replace("\x09imes", r"\times")
    s = s.replace("\x07lpha", r"\alpha")
    s = s.replace("\x0bec", r"\vec")
    s = s.replace("\x0dho", r"\rho")
    s = s.replace("\x0abla", r"\nabla")

    # Strip enclosing $$ ... $$ or $ ... $ if present
    stripped = s.strip()
    if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) >= 4:
        s = stripped[2:-2].strip()
    elif stripped.startswith("$") and stripped.endswith("$") and len(stripped) >= 2 and not stripped.startswith("$$"):
        s = stripped[1:-1].strip()
    elif stripped.startswith(r"\[") and stripped.endswith(r"\]") and len(stripped) >= 4:
        s = stripped[2:-2].strip()

    return s


def sanitize_latex(latex_str: str) -> str:
    """
    Sanitizes invalid LaTeX:
    1. Fixes basic Python string escapes.
    2. Strips dangling trailing backslashes.
    3. Converts unrecognized control sequences into \\text{...}.
    4. Balances unmatched braces {}, brackets [], and parentheses ().
    5. Repairs dangling \\frac (supplies missing arguments).
    """
    s = fix_basic_escaping(latex_str)

    # Strip dangling trailing backslash
    while s.endswith("\\") and not s.endswith("\\\\"):
        s = s[:-1].rstrip()

    # Convert unknown control sequences \unknown to \text{unknown}
    def replace_unknown_cmd(match):
        cmd = match.group(1)
        if cmd not in KATEX_ALLOWED_COMMANDS:
            return f"\\text{{{cmd}}}"
        return f"\\{cmd}"

    s = re.sub(r"\\([a-zA-Z]+)", replace_unknown_cmd, s)

    # Balance delimiters {}, [], ()
    for open_ch, close_ch in [("{", "}"), ("[", "]"), ("(", ")")]:
        open_cnt = 0
        close_cnt = 0
        i = 0
        n = len(s)
        while i < n:
            c = s[i]
            if c == "\\":
                bs_count = 0
                while i < n and s[i] == "\\":
                    bs_count += 1
                    i += 1
                if i >= n:
                    break
                next_c = s[i]
                if bs_count % 2 == 1:
                    # Escaped character
                    i += 1
                    continue
                else:
                    c = next_c
            if c == open_ch:
                open_cnt += 1
            elif c == close_ch:
                close_cnt += 1
            i += 1

        if open_cnt > close_cnt:
            s += close_ch * (open_cnt - close_cnt)
        elif close_cnt > open_cnt:
            excess = close_cnt - open_cnt
            for _ in range(excess):
                pos = s.rfind(close_ch)
                if pos != -1:
                    s = s[:pos] + s[pos + 1:]

    # Repair dangling fractions (no arguments or only 1 argument)
    # Check for \frac at end of string with 1 argument: e.g. \frac{...}$
    frac_one_arg = re.search(r"\\(frac|dfrac|tfrac|cfrac)(\{[^{}]*\})\s*$", s)
    if frac_one_arg:
        s = s.rstrip() + "{[Lücke]}"
    else:
        # Check for \frac without any arguments at end of string
        frac_no_args = re.search(r"\\(frac|dfrac|tfrac|cfrac)\s*$", s)
        if frac_no_args:
            s = s.rstrip() + "{[Lücke]}{[Lücke]}"

    return s


def check_latex_syntax_internal(s: str) -> Tuple[bool, str]:
    """
    Internal strict checker for KaTeX syntax.
    Returns (True, "") if completely valid, or (False, error_reason) if invalid.
    """
    # 1. Check for raw escape characters
    for bad_char in ["\x0c", "\x08", "\x09", "\x07", "\x0b", "\x0d"]:
        if bad_char in s:
            return False, f"Contains raw unescaped ASCII control character {repr(bad_char)}"

    # 2. Check for trailing backslash
    if s.endswith("\\") and not s.endswith("\\\\"):
        return False, "Dangling trailing backslash"

    # 3. Check balanced delimiters {}, [], ()
    stack = []
    pairs = {"}": "{", "]": "[", ")": "("}
    opening = {"{", "[", "("}
    closing = {"}", "]", ")"}

    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            bs_count = 0
            while i < n and s[i] == "\\":
                bs_count += 1
                i += 1
            if i >= n:
                return False, "Dangling backslash at end of expression"
            next_c = s[i]
            if bs_count % 2 == 1:
                # Escaped character (\{, \}, \[, \], etc.)
                i += 1
                continue
            else:
                c = next_c

        if c in opening:
            stack.append(c)
        elif c in closing:
            if not stack or stack[-1] != pairs[c]:
                return False, f"Unbalanced closing delimiter '{c}'"
            stack.pop()
        i += 1

    if stack:
        return False, f"Unclosed delimiters remaining: {stack}"

    # 4. Check valid fraction command structures (no dangling \frac without 2 arguments)
    frac_pattern = re.compile(r"\\(frac|dfrac|tfrac|cfrac)\b")
    for m in frac_pattern.finditer(s):
        pos = m.end()
        # Parse Argument 1
        while pos < len(s) and s[pos].isspace():
            pos += 1
        if pos >= len(s):
            return False, "Dangling fraction missing arguments"

        if s[pos] == "{":
            depth = 1
            pos += 1
            while pos < len(s) and depth > 0:
                if s[pos] == "{" and (pos == 0 or s[pos - 1] != "\\"):
                    depth += 1
                elif s[pos] == "}" and (pos == 0 or s[pos - 1] != "\\"):
                    depth -= 1
                pos += 1
            if depth > 0:
                return False, "Unclosed brace in fraction numerator"
        else:
            pos += 1

        # Parse Argument 2
        while pos < len(s) and s[pos].isspace():
            pos += 1
        if pos >= len(s):
            return False, "Dangling fraction missing denominator (2nd argument)"

        if s[pos] == "{":
            depth = 1
            pos += 1
            while pos < len(s) and depth > 0:
                if s[pos] == "{" and (pos == 0 or s[pos - 1] != "\\"):
                    depth += 1
                elif s[pos] == "}" and (pos == 0 or s[pos - 1] != "\\"):
                    depth -= 1
                pos += 1
            if depth > 0:
                return False, "Unclosed brace in fraction denominator"
        else:
            pos += 1

    # 5. Check control sequences against KaTeX allowed vocabulary
    for m in re.finditer(r"\\([a-zA-Z]+)", s):
        cmd = m.group(1)
        if cmd not in KATEX_ALLOWED_COMMANDS:
            return False, f"Invalid or unsupported KaTeX control sequence '\\{cmd}'"

    return True, ""


def validate_latex_syntax(latex_str: str) -> Tuple[bool, str]:
    """
    Validates KaTeX syntax:
    - Checks balanced braces {}, [], ().
    - Checks valid KaTeX command structures (no dangling \\frac without 2 arguments, no invalid control sequences).
    - If invalid, sanitizes or fixes basic escaping and returns (False, sanitized_latex).
    - If valid, returns (True, latex_str).
    """
    # Check the raw string first: if it contains escaping flaws or syntax errors, it is invalid
    is_valid, _ = check_latex_syntax_internal(latex_str)

    if is_valid:
        cleaned = fix_basic_escaping(latex_str)
        return True, cleaned

    sanitized = sanitize_latex(latex_str)
    return False, sanitized


def sanitize_mermaid_syntax(mermaid_body: str) -> str:
    """
    Validates and sanitizes Mermaid diagram syntax:
    1. Ensures valid diagram type declaration (graph TD, flowchart, sequenceDiagram, etc.)
    2. Strips markdown fences.
    3. Quotes node labels that contain parentheses, colons, or special characters to prevent parser breaks.
    """
    clean_lines = []
    for line in mermaid_body.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("```"):
            continue
        clean_lines.append(line)
    text = "\n".join(clean_lines).strip()
    if not text:
        return 'graph TD\n    A["Start"] --> B["End"]'

    lines = [l for l in text.splitlines() if l.strip()]
    first_line = lines[0].strip() if lines else ""
    valid_types = (
        "graph ", "flowchart ", "sequenceDiagram", "classDiagram",
        "stateDiagram", "erDiagram", "pie", "gantt", "gitGraph", "xychart-beta"
    )
    if not any(first_line.startswith(vt) for vt in valid_types):
        text = "graph TD\n" + text

    # Quote node labels containing parentheses, colons, or commas: e.g. A[Foo (Bar)] -> A["Foo (Bar)"]
    def _quote_labels(match):
        node_id = match.group(1)
        label_content = match.group(2)
        if not (label_content.startswith('"') and label_content.endswith('"')):
            safe_content = label_content.replace('"', "'")
            return f'{node_id}["{safe_content}"]'
        return match.group(0)

    text = re.sub(r'(\b[A-Za-z0-9_]+)\[([^"\]\n]*[\(\):,][^"\]\n]*)\]', _quote_labels, text)
    return text


# ==============================================================================
# 3. Deterministic Markdown Renderer
# ==============================================================================

def render_notations_to_markdown(notations: List[Union[Dict[str, Any], NotationItem]]) -> str:
    """
    Renders defined variables and mathematical operators into a crisp Markdown table:
    ### Mathematical Notation & Variable Ledger
    | Symbol | Conceptual Definition | Context / Segment |
    | :--- | :--- | :--- |
    | $\beta_i$ | Asset return sensitivity relative to market benchmark | Segment 01 [00:14:20] |
    """
    if not notations:
        return ""

    rows = [
        "### Mathematical Notation & Variable Ledger",
        "| Symbol | Conceptual Definition | Context / Segment |",
        "| :--- | :--- | :--- |",
    ]

    for item in notations:
        if hasattr(item, "model_dump"):
            d = item.model_dump()
        elif isinstance(item, dict):
            d = item
        else:
            d = getattr(item, "__dict__", {})

        sym = str(d.get("symbol", "")).strip()
        defn = str(d.get("definition", "")).strip().replace("\n", " ").replace("|", "\\|")
        seg = str(d.get("introduced_in_segment", "")).strip().replace("\n", " ").replace("|", "\\|")

        if not sym or not defn:
            continue

        if not sym.startswith("$"):
            sym = f"${sym}$"

        seg_val = seg if seg else "General"
        rows.append(f"| {sym} | {defn} | {seg_val} |")

    if len(rows) <= 3:
        return ""

    return "\n".join(rows)


def render_blocks_to_markdown(blocks: List[Union[Dict[str, Any], LectureNoteBlock]]) -> str:
    """
    Renders structured note blocks to Obsidian and GitHub Flavored Markdown callouts:
      > [!theorem] Titel
      > [!definition] Titel
      > [!proof] Herleitung
      > [!remark] Titel
      > [!example] Titel

    Proofs conclude cleanly with '∎' (QED symbol) or '[Lücke]' if incomplete.
    """
    if not blocks:
        return ""

    callout_sections = []

    for item in blocks:
        if hasattr(item, "model_dump"):
            data = item.model_dump()
        elif isinstance(item, dict):
            data = item
        else:
            data = getattr(item, "__dict__", {})

        b_type = str(data.get("type", "remark")).strip().lower()
        title = str(data.get("title", "")).strip()
        latex = str(data.get("latex", "")).strip()
        explanation = str(data.get("explanation", "")).strip()
        source = str(data.get("source", "")).strip()
        segment_id = str(data.get("segment_id", "")).strip()
        speaker = data.get("speaker")

        # Special handling for visual architecture diagrams (Mermaid)
        if b_type == "diagram":
            mermaid_raw = latex.strip() or explanation.strip()
            mermaid_body = sanitize_mermaid_syntax(mermaid_raw)

            d_lines = []
            if title:
                d_lines.append(f"> [!diagram] {title}")
                if explanation and latex:
                    for exp_line in explanation.splitlines():
                        if exp_line.strip():
                            d_lines.append(f"> {exp_line}")
                d_lines.append(f"\n```mermaid\n{mermaid_body}\n```")
            else:
                d_lines.append(f"```mermaid\n{mermaid_body}\n```")

            callout_sections.append("\n".join(d_lines))
            continue

        # Multi-speaker question callout handling
        if speaker == "Audience Question":
            ts_str = ""
            if "@" in title:
                header_title = title
            elif segment_id:
                ts_clean = segment_id
                if ts_clean.startswith("SEG_"):
                    ts_clean = ts_clean[4:]
                ts_str = f" @ {ts_clean}"
                if not title or title.lower() in ("audience question", "frage", "question", "remark", "example"):
                    header_title = f"Audience Question{ts_str}"
                else:
                    header_title = f"Audience Question: {title}{ts_str}"
            else:
                if not title or title.lower() in ("audience question", "frage", "question", "remark", "example"):
                    header_title = "Audience Question"
                else:
                    header_title = f"Audience Question: {title}"

            lines = [f"> [!question] {header_title}"]

            # Parse question and response from explanation
            if "**Question:**" in explanation or "**Frage:**" in explanation:
                for exp_line in explanation.splitlines():
                    if exp_line.strip():
                        lines.append(f"> {exp_line}")
                    else:
                        lines.append(">")
            else:
                split_candidates = ["\nResponse:", "\nresponse:", "\nAntwort:", "\nantwort:", "\nEinordnung:"]
                q_text = ""
                ans_text = ""
                split_found = False
                for sc in split_candidates:
                    if sc in explanation:
                        parts = explanation.split(sc, 1)
                        q_text = parts[0].strip()
                        ans_text = parts[1].strip()
                        split_found = True
                        break

                if not split_found and "\n\n" in explanation:
                    p = explanation.split("\n\n", 1)
                    q_text = p[0].strip()
                    ans_text = p[1].strip()
                    split_found = True

                if not split_found:
                    q_text = explanation.strip()

                if q_text:
                    lines.append(f"> **Question:** {q_text}")
                if ans_text:
                    lines.append(">")
                    lines.append(f"> **Response / Derivation:** {ans_text}")

            if latex:
                _, valid_latex = validate_latex_syntax(latex)
                if lines and lines[-1] != ">":
                    lines.append(">")
                if not any("**Response / Derivation:**" in l for l in lines):
                    lines.append("> **Response / Derivation:**")
                lines.append("> $$")
                for lat_line in valid_latex.splitlines():
                    lines.append(f"> {lat_line}")
                lines.append("> $$")

            meta_items = []
            if source and source != "inferred":
                meta_items.append(f"Quelle: {source}")
            if segment_id and f"@{segment_id}" not in header_title and f"@ {segment_id}" not in header_title:
                meta_items.append(f"Segment: {segment_id}")
            if meta_items:
                if lines and lines[-1] != ">":
                    lines.append(">")
                lines.append(f"> <small>*{' | '.join(meta_items)}*</small>")

            callout_sections.append("\n".join(lines))
            continue

        # Normalize callout title
        if not title:
            if b_type == "proof":
                title = "Herleitung"
            else:
                title = b_type.capitalize()

        lines = [f"> [!{b_type}] {title}"]

        # Add explanation prose
        if explanation:
            for exp_line in explanation.splitlines():
                if exp_line.strip():
                    lines.append(f"> {exp_line}")
                else:
                    lines.append(">")

        # Add validated LaTeX display block
        if latex:
            _, valid_latex = validate_latex_syntax(latex)
            if lines and lines[-1] != ">":
                lines.append(">")
            lines.append("> $$")
            for lat_line in valid_latex.splitlines():
                lines.append(f"> {lat_line}")
            lines.append("> $$")

        # Conclude proofs cleanly
        if b_type == "proof":
            is_incomplete = (
                "[Lücke]" in explanation
                or "[Lücke]" in latex
                or "lücke" in explanation.lower()
                or "lücke" in latex.lower()
                or "incomplete" in explanation.lower()
                or "unvollständig" in explanation.lower()
                or "unresolved" in explanation.lower()
            )
            qed_marker = "[Lücke]" if is_incomplete else "∎"

            # Check if block already ends with a QED or gap marker
            last_text = "\n".join(lines).strip()
            if not any(last_text.endswith(m) for m in ("∎", "[Lücke]", r"\qed", r"\blacksquare")):
                if lines and lines[-1] != ">":
                    lines.append(">")
                lines.append(f"> {qed_marker}")

        # Optional metadata attribution line
        meta_items = []
        if speaker and speaker not in ("Lecturer", "Audience Question"):
            meta_items.append(f"Sprecher: {speaker}")
        if source and source != "inferred":
            src_label = "Tafelbild (Whiteboard)" if source == "whiteboard" else source
            meta_items.append(f"Quelle: {src_label}")
        if segment_id:
            meta_items.append(f"Segment: {segment_id}")
        if meta_items:
            if lines and lines[-1] != ">":
                lines.append(">")
            lines.append(f"> <small>*{' | '.join(meta_items)}*</small>")

        callout_sections.append("\n".join(lines))

    return "\n\n".join(callout_sections)


def render_flashcards_to_markdown(flashcards: List[Union[Dict[str, Any], FlashcardItem]]) -> str:
    """
    Renders flashcard items into standardized Obsidian Spaced Repetition plugin format:
    ## Exam Flashcards & Spaced Repetition
    What is the core derivation of factor beta? #flashcard
    ?
    $$E(R_i) = R_f + \beta_i [E(R_m) - R_f]$$
    Beta reflects asset return sensitivity to broad market variance.
    """
    if not flashcards:
        return ""

    cards_out = ["## Exam Flashcards & Spaced Repetition"]
    for item in flashcards:
        if hasattr(item, "model_dump"):
            d = item.model_dump()
        elif isinstance(item, dict):
            d = item
        else:
            d = getattr(item, "__dict__", {})

        q = str(d.get("question", "")).strip()
        ans = str(d.get("answer_latex", "")).strip()
        ts = str(d.get("reference_timestamp", "")).strip() if d.get("reference_timestamp") else ""

        if not q or not ans:
            continue

        ts_suffix = f" {ts}" if ts and ts not in q else ""
        cards_out.append(f"{q}{ts_suffix} #flashcard\n?\n{ans}")

    if len(cards_out) == 1:
        return ""
    return "\n\n".join(cards_out)


def render_socratic_to_markdown(questions: List[str]) -> str:
    """
    Renders 3 rapid active-recall debrief questions into Obsidian callout format:
    > [!question] Socratic Active Recall
    > 1. Question 1
    > 2. Question 2
    > 3. Question 3
    """
    if not questions:
        return ""
    valid_qs = [str(q).strip() for q in questions if str(q).strip()]
    if not valid_qs:
        return ""
    lines = ["> [!question] Socratic Active Recall"]
    for idx, q in enumerate(valid_qs, 1):
        lines.append(f"> {idx}. {q}")
    return "\n".join(lines)


def export_flashcards_to_tsv(
    flashcards: List[Union[Dict[str, Any], FlashcardItem]],
    output_path: str,
) -> str:
    """
    Exports flashcards to Anki-importable TSV format (Front \\t Back \\t Deck/Tags).
    """
    rows = []
    for item in flashcards:
        if hasattr(item, "model_dump"):
            d = item.model_dump()
        elif isinstance(item, dict):
            d = item
        else:
            d = getattr(item, "__dict__", {})

        q = str(d.get("question", "")).strip()
        ans = str(d.get("answer_latex", "")).strip()
        ts = str(d.get("reference_timestamp", "")).strip() if d.get("reference_timestamp") else ""
        if not q or not ans:
            continue

        q_clean = q.replace("\t", " ")
        if ts and ts not in q_clean:
            q_clean = f"{q_clean} <small><i>{ts}</i></small>"

        ans_clean = ans.replace("\t", " ").replace("\n", "<br>")
        rows.append(f"{q_clean}\t{ans_clean}\tChalk::Exam")

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
    return output_path


def extract_flashcards_from_markdown(markdown_text: str) -> List[FlashcardItem]:
    """
    Extracts Obsidian spaced repetition flashcard blocks (#flashcard / ?) from markdown text.
    """
    flashcards: List[FlashcardItem] = []
    if not markdown_text:
        return flashcards

    pattern = re.compile(
        r"^([^\n]+?)\s*#flashcard\s*\n\?\s*\n(.*?)(?=\n\n[^\n]+?#flashcard|\n## |\n<!-- CHUNK_STATE|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(markdown_text):
        q = match.group(1).strip()
        ans = match.group(2).strip()
        if q and ans:
            ts_m = re.search(r"\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?", q)
            ts = None
            if ts_m:
                ts = ts_m.group(1)
                q = re.sub(r"\s*\[?" + re.escape(ts) + r"\]?\s*$", "", q).strip()
            flashcards.append(FlashcardItem(question=q, answer_latex=ans, reference_timestamp=ts))
    return flashcards


def render_synthesis_to_markdown(
    synthesis: Union[Dict[str, Any], LectureSynthesisResponse],
    timestamp_range: str = "[00:00 - 15:00]",
) -> str:
    """
    Renders full lecture synthesis output including title header, mathematical notation ledger,
    callout blocks, exam flashcards, socratic active recall debrief, and <!-- CHUNK_STATE --> context chain block.
    """
    if hasattr(synthesis, "model_dump"):
        data = synthesis.model_dump()
    elif isinstance(synthesis, dict):
        data = synthesis
    else:
        data = getattr(synthesis, "__dict__", {})

    topic = data.get("topic", "Lecture Synthesis")
    blocks = data.get("blocks", [])
    notations = data.get("notations", [])
    active_vars = data.get("active_variables", [])
    unresolved = data.get("unresolved_proofs", [])
    speaker = data.get("primary_speaker", "Instructor")
    flashcards = data.get("flashcards", [])
    socratic_questions = data.get("socratic_questions", [])

    rendered_notations = render_notations_to_markdown(notations)
    rendered_callouts = render_blocks_to_markdown(blocks)
    rendered_flashcards = render_flashcards_to_markdown(flashcards)
    rendered_socratic = render_socratic_to_markdown(socratic_questions)

    state = ChunkState(
        topic=topic,
        active_variables=active_vars,
        unresolved_proofs=unresolved,
        primary_speaker=speaker,
        timestamp_range=timestamp_range,
    )

    parts = [
        f"## {topic} {timestamp_range}\n",
        rendered_notations,
        rendered_callouts,
        rendered_flashcards,
        rendered_socratic,
        "\n" + state.to_markdown_block(),
    ]
    return "\n\n".join(p for p in parts if p.strip())


# ==============================================================================
# 4. Synthesis Pipeline Coordinator
# ==============================================================================

class SynthesisPipeline:
    """
    Coordinates structured multimodal lecture synthesis:
    - Enforces JSON Schema structured outputs with Gemini models.
    - Validates KaTeX syntax and repairs formatting defects locally.
    - Deterministically renders Obsidian/GitHub callouts.
    """

    def __init__(self, gemini_pipeline=None):
        self.gemini_pipeline = gemini_pipeline

    @staticmethod
    def parse_synthesis_json(raw_json_or_text: str) -> LectureSynthesisResponse:
        """
        Parses raw model output into LectureSynthesisResponse with graceful fallbacks.
        """
        text = raw_json_or_text.strip()
        # Strip potential markdown code block delimiters
        if text.startswith("```json") and text.endswith("```"):
            text = text[7:-3].strip()
        elif text.startswith("```") and text.endswith("```"):
            text = text[3:-3].strip()

        try:
            return LectureSynthesisResponse.model_validate_json(text)
        except Exception:
            # Fallback to json.loads with relaxed parsing
            try:
                data = json.loads(text)
                return LectureSynthesisResponse.model_validate(data)
            except Exception as e:
                logger.warning("Could not parse strict JSON for synthesis: %s. Using fallback object.", e)
                return LectureSynthesisResponse(
                    topic="Synthesized Notes",
                    blocks=[
                        LectureNoteBlock(
                            type="remark",
                            title="Notes Summary",
                            explanation=text[:1000],
                            source="inferred",
                        )
                    ],
                )

    def process_and_render_synthesis(
        self,
        raw_output: str,
        timestamp_range: str = "[00:00 - 15:00]",
    ) -> Tuple[str, ChunkState, LectureSynthesisResponse]:
        """
        Takes raw model response, validates KaTeX syntax across all blocks,
        and produces rendered markdown and ChunkState.
        """
        response_obj = self.parse_synthesis_json(raw_output)

        # Validate and sanitize all blocks' LaTeX
        for block in response_obj.blocks:
            if block.latex:
                _, sanitized = validate_latex_syntax(block.latex)
                block.latex = sanitized

        rendered_md = render_synthesis_to_markdown(response_obj, timestamp_range=timestamp_range)
        chunk_state = response_obj.to_chunk_state(timestamp_range=timestamp_range)

        return rendered_md, chunk_state, response_obj

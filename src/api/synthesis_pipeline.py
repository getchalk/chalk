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

import re
import json
import logging
from typing import List, Tuple, Dict, Any, Optional, Union
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
)


class LectureNoteBlock(BaseModel):
    """
    Individual structured note block representing a mathematical or conceptual unit.
    """
    model_config = ConfigDict(extra="ignore")

    type: str = Field(
        ...,
        description="Type of the block: theorem | definition | proof | remark | example"
    )
    title: str = Field(
        ...,
        description="Concise title of the theorem, definition, proof, remark, or example"
    )
    latex: str = Field(
        default="",
        description="KaTeX compatible mathematical formula or derivation (without outer $$)"
    )
    explanation: str = Field(
        default="",
        description="Pedagogical explanation or verbal context from the lecture"
    )
    segment_id: str = Field(
        default="",
        description="Lecture segment identifier, e.g. SEG_28"
    )
    source: str = Field(
        default="inferred",
        description="Source of this block: slide | speech | inferred"
    )

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
            }
            return synonyms.get(v_clean, v_clean)
        return str(v)

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, v: Any) -> str:
        if isinstance(v, str):
            v_clean = v.strip().lower()
            if v_clean in ("slide", "speech", "inferred"):
                return v_clean
            return "inferred"
        return "inferred"


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
    # Environments & Spacing
    "begin", "end", "quad", "qquad", "phantom", "hphantom", "vphantom",
    "limits", "nolimits", "displaystyle", "textstyle", "scriptstyle", "scriptscriptstyle",
    "over", "atop", "choose"
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


# ==============================================================================
# 3. Deterministic Markdown Renderer
# ==============================================================================

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
        if source and source != "inferred":
            meta_items.append(f"Quelle: {source}")
        if segment_id:
            meta_items.append(f"Segment: {segment_id}")
        if meta_items:
            if lines and lines[-1] != ">":
                lines.append(">")
            lines.append(f"> <small>*{' | '.join(meta_items)}*</small>")

        callout_sections.append("\n".join(lines))

    return "\n\n".join(callout_sections)


def render_synthesis_to_markdown(
    synthesis: Union[Dict[str, Any], LectureSynthesisResponse],
    timestamp_range: str = "[00:00 - 15:00]",
) -> str:
    """
    Renders full lecture synthesis output including title header, callout blocks,
    and <!-- CHUNK_STATE --> context chain block.
    """
    if hasattr(synthesis, "model_dump"):
        data = synthesis.model_dump()
    elif isinstance(synthesis, dict):
        data = synthesis
    else:
        data = getattr(synthesis, "__dict__", {})

    topic = data.get("topic", "Lecture Synthesis")
    blocks = data.get("blocks", [])
    active_vars = data.get("active_variables", [])
    unresolved = data.get("unresolved_proofs", [])
    speaker = data.get("primary_speaker", "Instructor")

    rendered_callouts = render_blocks_to_markdown(blocks)

    state = ChunkState(
        topic=topic,
        active_variables=active_vars,
        unresolved_proofs=unresolved,
        primary_speaker=speaker,
        timestamp_range=timestamp_range,
    )

    parts = [
        f"## {topic} {timestamp_range}\n",
        rendered_callouts,
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

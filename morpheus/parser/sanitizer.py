"""Input sanitization layer — sits between user input and the LLM parser.

Detects and neutralizes prompt injection, SQL injection, XSS, and
encoding attacks before the input reaches the LLM.

Four levels of protection:
  1. Pattern detection — prompt injection, SQL injection, XSS
  2. Structural analysis — JSON blocks, code fences, HTML tags
  3. Unicode security — zero-width chars, control chars, encoding tricks
  4. Length and size — prevents oversized or multi-line injection
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


# ── Unicode normalization ────────────────────────────────────────────────────

def _normalize_unicode(text: str) -> str:
    """Normalize Unicode to defeat homoglyph and obfuscation attacks.

    1. NFKC normalization: maps compatibility characters to their canonical
       forms (e.g. fullwidth 'A' → 'A', ligature 'fi' → 'fi')
    2. Strip format characters (category "Cf"): zero-width joiners, RTL marks,
       invisible separators that bypass pattern matching
    3. Map common Cyrillic/Greek lookalikes to ASCII — NFKC doesn't catch
       these because they are canonical characters in their own scripts
    """
    text = unicodedata.normalize("NFKC", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = text.translate(_HOMOGLYPH_MAP)
    return text


# Cyrillic and Greek characters visually identical to Latin ASCII.
# NFKC treats these as canonical (not compatibility) so they survive
# normalization. This table maps the most common lookalikes.
_HOMOGLYPH_TABLE: dict[str, str] = {
    # Cyrillic → ASCII
    "\u0410": "A", "\u0430": "a",  # А а
    "\u0412": "B", "\u0432": "v",  # В в (uppercase is B-like)
    "\u0421": "C", "\u0441": "c",  # С с
    "\u0435": "e", "\u0415": "E",  # е Е
    "\u041D": "H", "\u043D": "h",  # Н н
    "\u0456": "i",                  # і (Ukrainian i)
    "\u0406": "I",                  # І (Ukrainian I)
    "\u041A": "K", "\u043A": "k",  # К к
    "\u041C": "M", "\u043C": "m",  # М м
    "\u041E": "O", "\u043E": "o",  # О о
    "\u0440": "p", "\u0420": "P",  # р Р
    "\u0455": "s", "\u0405": "S",  # ѕ Ѕ (Macedonian)
    "\u0422": "T", "\u0442": "t",  # Т т
    "\u0443": "y", "\u0423": "Y",  # у У
    "\u0445": "x", "\u0425": "X",  # х Х
    # Greek → ASCII
    "\u0391": "A", "\u03B1": "a",  # Α α
    "\u0392": "B", "\u03B2": "b",  # Β β
    "\u0395": "E", "\u03B5": "e",  # Ε ε
    "\u0397": "H", "\u03B7": "h",  # Η η
    "\u0399": "I", "\u03B9": "i",  # Ι ι
    "\u039A": "K", "\u03BA": "k",  # Κ κ
    "\u039C": "M",                  # Μ
    "\u039D": "N",                  # Ν
    "\u039F": "O", "\u03BF": "o",  # Ο ο
    "\u03A1": "P", "\u03C1": "p",  # Ρ ρ
    "\u03A4": "T", "\u03C4": "t",  # Τ τ
    "\u03A5": "Y", "\u03C5": "y",  # Υ υ
    "\u03A7": "X", "\u03C7": "x",  # Χ χ
    "\u0396": "Z", "\u03B6": "z",  # Ζ ζ
}
_HOMOGLYPH_MAP = str.maketrans(_HOMOGLYPH_TABLE)


# ── Prompt injection patterns ────────────────────────────────────────────────

PROMPT_INJECTION_PATTERNS: list[re.Pattern] = [
    # Direct instruction override
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?|prompts?)", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|above)", re.IGNORECASE),

    # Role hijacking — specific enough to avoid false positives on
    # legitimate BI queries like "act as of January" or "system: ERP"
    re.compile(r"you\s+are\s+now\s+(a|in)\b", re.IGNORECASE),
    re.compile(r"act\s+as\s+(a\s+)?(different|new|another)\s+\w+", re.IGNORECASE),
    re.compile(r"pretend\s+(to\s+be|you\s+are)", re.IGNORECASE),
    re.compile(r"new\s+instructions?:", re.IGNORECASE),
    re.compile(r"(?:^|[.!?])\s*system\s*:", re.IGNORECASE | re.MULTILINE),  # "SYSTEM:" at start of input or after sentence boundary
    re.compile(r"admin\s+mode", re.IGNORECASE),
    re.compile(r"(switch|change)\s+to\s+\w+\s+mode", re.IGNORECASE),

    # Output manipulation
    re.compile(r"output\s+only", re.IGNORECASE),
    re.compile(r"respond\s+with\s+only", re.IGNORECASE),
    re.compile(r"return\s+(only\s+)?the\s+following", re.IGNORECASE),

    # NOTE: confidence manipulation and JSON injection patterns removed.
    # - Confidence injection: the Coherence Check already neutralizes this
    #   downstream — if the parser outputs high confidence on a value not
    #   in the original input, it gets zeroed to 0.0.
    # - JSON injection: too many false positives when users paste filter
    #   examples or structured data in their queries.
]


# ── SQL injection patterns ───────────────────────────────────────────────────

SQL_INJECTION_PATTERNS: list[re.Pattern] = [
    # Destructive SQL
    re.compile(r"\bDROP\s+(ALL\s+)?(TABLE|DATABASE|INDEX|VIEW)S?\b", re.IGNORECASE),
    re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
    re.compile(r"\bTRUNCATE\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE),
    re.compile(r"\bUPDATE\s+\w+\s+SET\b", re.IGNORECASE),

    # SQL probing / exfiltration
    re.compile(r"\bUNION\s+(ALL\s+)?SELECT\b", re.IGNORECASE),
    re.compile(r"\bSELECT\s+.+\s+FROM\s+information_schema\b", re.IGNORECASE),
    re.compile(r"\bEXEC\s*\(", re.IGNORECASE),
    re.compile(r"\bxp_cmdshell\b", re.IGNORECASE),

    # SQL comment injection
    re.compile(r"--\s"),
    re.compile(r"/\*.*?\*/"),

    # Shell metacharacters (command injection via SQL)
    re.compile(r"[;|`]\s*\w"),
]


# ── XSS patterns ────────────────────────────────────────────────────────────

XSS_PATTERNS: list[re.Pattern] = [
    # Script injection
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"vbscript\s*:", re.IGNORECASE),
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),

    # Event handlers
    re.compile(r"\bon\w+\s*=", re.IGNORECASE),  # onclick=, onerror=, etc.

    # HTML injection
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"<\s*object", re.IGNORECASE),
    re.compile(r"<\s*embed", re.IGNORECASE),
    re.compile(r"<\s*form", re.IGNORECASE),
    re.compile(r"<\s*img\s+[^>]*src\s*=", re.IGNORECASE),
]


# ── Unicode / encoding tricks ────────────────────────────────────────────────

# Zero-width characters used to hide text or bypass pattern matching
ZERO_WIDTH_CHARS = re.compile(r'[\u200b\u200c\u200d\u200e\u200f\u2060\ufeff\u00ad]')

# Multi-level HTML entity encoding (&#x6A;&#x61;&#x76;&#x61; = "java")
HTML_ENTITY_PATTERN = re.compile(r'&#x?[0-9a-f]+;', re.IGNORECASE)


# ── Structural checks ────────────────────────────────────────────────────────

MAX_INPUT_LENGTH = 2000
MAX_LINE_COUNT = 20
MAX_SPECIAL_CHAR_RATIO = 0.3


@dataclass
class SanitizationResult:
    """Result of input sanitization."""

    clean_input: str
    is_suspicious: bool
    flags: list[str]

    @property
    def blocked(self) -> bool:
        """Input should be blocked (too many red flags)."""
        return len(self.flags) >= 3

    def to_dict(self) -> dict:
        return {
            "is_suspicious": self.is_suspicious,
            "blocked": self.blocked,
            "flags": self.flags,
            "flag_count": len(self.flags),
        }


def sanitize(raw_input: str) -> SanitizationResult:
    """Sanitize user input before it reaches the LLM parser.

    Returns a SanitizationResult with:
    - clean_input: the sanitized text (or original if clean)
    - is_suspicious: True if any red flags were detected
    - flags: list of specific issues found
    - blocked: True if input should not be sent to LLM at all
    """
    flags: list[str] = []
    text = raw_input.strip()

    # ── Unicode normalization (before all pattern checks) ─────────────
    # Defeats homoglyph attacks (Cyrillic 'а' → ASCII 'a'),
    # obfuscation (fullwidth chars, ligatures), and invisible
    # format characters — all before pattern matching runs.
    text = _normalize_unicode(text)

    # ── Length check ──────────────────────────────────────────────────
    if len(text) > MAX_INPUT_LENGTH:
        flags.append(f"input_too_long:{len(text)}")
        text = text[:MAX_INPUT_LENGTH]

    # ── Line count check ─────────────────────────────────────────────
    lines = text.split("\n")
    if len(lines) > MAX_LINE_COUNT:
        flags.append(f"too_many_lines:{len(lines)}")
        text = " ".join(line.strip() for line in lines[:MAX_LINE_COUNT])

    # ── Unicode security ─────────────────────────────────────────────
    # Remove zero-width characters (used to bypass pattern matching)
    if ZERO_WIDTH_CHARS.search(text):
        flags.append("zero_width_chars")
        text = ZERO_WIDTH_CHARS.sub("", text)

    # Detect HTML entity encoding tricks
    entity_count = len(HTML_ENTITY_PATTERN.findall(text))
    if entity_count >= 3:
        flags.append(f"html_entity_encoding:{entity_count}")

    # ── Special character ratio ──────────────────────────────────────
    if text:
        alpha_count = sum(1 for c in text if c.isalnum() or c.isspace())
        ratio = 1.0 - (alpha_count / len(text)) if len(text) > 0 else 0
        if ratio > MAX_SPECIAL_CHAR_RATIO:
            flags.append(f"high_special_char_ratio:{ratio:.2f}")

    # ── Prompt injection patterns ────────────────────────────────────
    for pattern in PROMPT_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            flags.append(f"prompt_injection:{match.group()[:50]}")

    # ── SQL injection patterns ───────────────────────────────────────
    for pattern in SQL_INJECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            flags.append(f"sql_injection:{match.group()[:50]}")

    # ── XSS patterns ────────────────────────────────────────────────
    for pattern in XSS_PATTERNS:
        match = pattern.search(text)
        if match:
            flags.append(f"xss:{match.group()[:50]}")

    # ── Structural: code fences ──────────────────────────────────────
    if "```" in text:
        flags.append("code_fence_detected")

    # ── Build clean input ────────────────────────────────────────────
    # Collapse to single line, strip control characters
    clean = " ".join(text.split())
    clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', clean)

    return SanitizationResult(
        clean_input=clean,
        is_suspicious=len(flags) > 0,
        flags=flags,
    )

"""Deterministic preprocessor for agent training pipeline.

Architecture:
  User message → Preprocessor (rules, fast) → Fine-tuned LLM (judgment) → Structured output

The preprocessor handles the cheap, 100% deterministic work:
  - Strip filler words and hedging language
  - Detect domain (coding, orchestration, websites, debugging, social_media, education, video, security)
  - Extract hard constraints (deadlines, file references, tool names, numbers)
  - Count token budget (via tiktoken cl100k_base)
  - Preserve verbatim user wording in a "raw" field
  - Tag ambiguity level (clear / needs_clarification / vague)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    import tiktoken

    _enc = tiktoken.get_encoding("cl100k_base")
except Exception:
    _enc = None  # type: ignore[assignment]

# ── Filler / hedging patterns ────────────────────────────────────────

_FILLER_PHRASES: list[str] = [
    r"\bum+\b",
    r"\buh+\b",
    r"\blike\b(?=\s*,)",
    r"\byou know\b",
    r"\bi mean\b",
    r"\bbasically\b",
    r"\bactually\b",
    r"\bjust\b(?!\s+(?:in\s+time|ice))",
    r"\bkinda?\b",
    r"\bsort\s+of\b",
    r"\bmaybe\b",
    r"\bi guess\b",
    r"\bi think\b(?!\s+(?:that|it|we|this|the))",
    r"\bprobably\b",
    r"\banyway(?:s)?\b",
    r"\bso+\b(?=\s*,)",
    r"\bwell\b(?=\s*,)",
    r"\bright\b(?=\s*[,?])",
    r"\bliterally\b",
    r"\bhonestly\b",
]

_FILLER_RE = re.compile("|".join(_FILLER_PHRASES), re.IGNORECASE)

# ── Domain detection rules ───────────────────────────────────────────

_DOMAIN_RULES: list[tuple[str, list[str]]] = [
    (
        "coding",
        [
            "code",
            "function",
            "class",
            "import",
            "variable",
            "bug",
            "compile",
            "syntax",
            "refactor",
            "lint",
            "type error",
            "stack trace",
            "exception",
            "python",
            "rust",
            "javascript",
            "typescript",
            "api",
            "endpoint",
            "sdk",
        ],
    ),
    (
        "orchestration",
        [
            "agent",
            "orchestrat",
            "route",
            "dispatch",
            "tool call",
            "pipeline",
            "workflow",
            "handoff",
            "fan-out",
            "state machine",
            "langgraph",
        ],
    ),
    (
        "websites",
        [
            "website",
            "html",
            "css",
            "frontend",
            "react",
            "next.js",
            "tailwind",
            "seo",
            "aeo",
            "page",
            "layout",
            "responsive",
            "web",
            "dom",
            "component",
        ],
    ),
    (
        "debugging",
        [
            "debug",
            "error",
            "traceback",
            "crash",
            "fail",
            "broken",
            "fix",
            "not working",
            "wrong output",
            "unexpected",
            "regression",
            "flaky",
        ],
    ),
    (
        "social_media",
        [
            "social media",
            "post",
            "instagram",
            "twitter",
            "tiktok",
            "youtube",
            "content",
            "caption",
            "hashtag",
            "engagement",
            "schedule",
            "publish",
        ],
    ),
    (
        "education",
        [
            "curriculum",
            "studio",
            "student",
            "learn",
            "teach",
            "bloom",
            "scaffold",
            "pedagogy",
            "assessment",
            "spell book",
            "human edge",
            "accreditation",
            "abet",
            "demo day",
            "vocabulary",
        ],
    ),
    (
        "video",
        [
            "video",
            "higgsfield",
            "animation",
            "character",
            "soul id",
            "mochi",
            "diffusion",
            "scene",
            "camera",
            "shot",
            "render",
            "duration",
        ],
    ),
    (
        "security",
        [
            "security",
            "secret",
            "cve",
            "vulnerability",
            "scan",
            "audit",
            "firewall",
            "injection",
            "xss",
            "csrf",
            "auth",
            "token",
            "leak",
        ],
    ),
]

# ── Constraint extraction patterns ───────────────────────────────────

_FILE_REF = re.compile(r"(?:[\w./\\-]+\.(?:py|rs|ts|js|json|yaml|yml|md|toml|sql|sh|txt|csv|jsonl))", re.IGNORECASE)
_TOOL_NAMES = re.compile(
    r"\b(?:safe_shell|file_reader|doc_updater|system_info|webhook_send|git_ops|"
    r"health_check|log_tail|alert_dispatch|secret_scanner|db_query|process_restart|"
    r"document_ocr)\b",
    re.IGNORECASE,
)
_NUMBERS = re.compile(r"\b\d+(?:\.\d+)?(?:\s*%|\s*(?:ms|sec|min|hour|MB|GB|KB|lines?|tokens?|examples?))?\b")
_DEADLINE = re.compile(r"\b(?:by|before|deadline|due|within|asap|urgent|eod|eow)\b", re.IGNORECASE)
_AGENT_NAMES = re.compile(
    r"\b(?:soul_core|devops_agent|monitor_agent|self_healer_agent|code_review_agent|"
    r"security_agent|data_agent|comms_agent|cs_agent|it_agent|knowledge_agent|"
    r"prompt_engineer|education_agent|higgsfield_agent)\b",
    re.IGNORECASE,
)


@dataclass
class PreprocessResult:
    """Output of the deterministic preprocessor."""

    raw: str
    cleaned: str
    domains: list[str]
    primary_domain: str
    constraints: dict[str, Any]
    token_count: int
    ambiguity: str  # "clear" | "needs_clarification" | "vague"
    word_count: int
    mentioned_agents: list[str] = field(default_factory=list)
    mentioned_tools: list[str] = field(default_factory=list)
    mentioned_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "cleaned": self.cleaned,
            "domains": self.domains,
            "primary_domain": self.primary_domain,
            "constraints": self.constraints,
            "token_count": self.token_count,
            "ambiguity": self.ambiguity,
            "word_count": self.word_count,
            "mentioned_agents": self.mentioned_agents,
            "mentioned_tools": self.mentioned_tools,
            "mentioned_files": self.mentioned_files,
        }


def _count_tokens(text: str) -> int:
    if _enc is not None:
        return len(_enc.encode(text))
    return len(text.split())


def _strip_filler(text: str) -> str:
    cleaned = _FILLER_RE.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s*,\s*,", ",", cleaned)
    return cleaned.strip()


def _detect_domains(text: str) -> list[str]:
    text_lower = text.lower()
    scores: dict[str, int] = {}
    for domain, keywords in _DOMAIN_RULES:
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[domain] = score
    if not scores:
        return ["general"]
    return sorted(scores, key=scores.get, reverse=True)  # type: ignore[arg-type]


def _extract_constraints(text: str) -> dict[str, Any]:
    constraints: dict[str, Any] = {}

    files = _FILE_REF.findall(text)
    if files:
        constraints["files"] = files

    tools = _TOOL_NAMES.findall(text)
    if tools:
        constraints["tools"] = [t.lower() for t in tools]

    numbers = _NUMBERS.findall(text)
    if numbers:
        constraints["numbers"] = numbers

    if _DEADLINE.search(text):
        constraints["has_deadline"] = True

    agents = _AGENT_NAMES.findall(text)
    if agents:
        constraints["agents"] = [a.lower() for a in agents]

    return constraints


def _assess_ambiguity(text: str, domains: list[str], constraints: dict[str, Any]) -> str:
    words = text.split()
    if len(words) < 3:
        return "vague"
    if len(domains) > 2 and not constraints.get("tools") and not constraints.get("agents"):
        return "needs_clarification"
    if len(words) < 8 and domains == ["general"]:
        return "needs_clarification"
    if constraints.get("tools") or constraints.get("agents") or constraints.get("files"):
        return "clear"
    if len(domains) == 1 and domains[0] != "general" and len(words) >= 8:
        return "clear"
    return "needs_clarification"


def preprocess(message: str) -> PreprocessResult:
    """Run the deterministic preprocessor on a user message.

    Returns a PreprocessResult with cleaned text, detected domains,
    extracted constraints, token count, and ambiguity assessment.
    """
    raw = message.strip()
    cleaned = _strip_filler(raw)

    domains = _detect_domains(cleaned)
    primary = domains[0] if domains else "general"
    constraints = _extract_constraints(raw)

    ambiguity = _assess_ambiguity(cleaned, domains, constraints)

    return PreprocessResult(
        raw=raw,
        cleaned=cleaned,
        domains=domains,
        primary_domain=primary,
        constraints=constraints,
        token_count=_count_tokens(cleaned),
        ambiguity=ambiguity,
        word_count=len(cleaned.split()),
        mentioned_agents=constraints.get("agents", []),
        mentioned_tools=constraints.get("tools", []),
        mentioned_files=constraints.get("files", []),
    )

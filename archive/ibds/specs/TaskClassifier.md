TaskClassifier – standalone spec  
Language: Python 3.10+  
Interface only; no implementation or imports beyond type hints.

-------------------------------------------------
1. Python interface
-------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Final

class TaskType(str, Enum):
    STRATEGIC_PLANNING = "strategic_planning"
    UI_REFINEMENT     = "ui_refinement"
    ITERATION         = "iteration"
    DEBUG             = "debug"
    REVISION          = "revision"
    SCOPE_CHANGE      = "scope_change"

@dataclass(frozen=True, slots=True)
class TaskClassification:
    task_type: TaskType
    confidence: float                 # 0.0–1.0, deterministic given identical text
    reason: str                       # one-sentence summary of why this type
    canonical_prompt: str | None      # cleaned canonical prompt to feed downstream LLM

class TaskClassifier:
    ACCEPTED_LANGUAGES: Final[tuple[str, ...]] = ("en",)

    def classify(self, raw_input: str) -> TaskClassification:
        """
        Deterministically map arbitrary user text to exactly one TaskType.
        Thread-safe, stateless, no I/O, no LLM calls, <5 ms CPU.
        Raises ValueError on empty or >10k-char input.
        """
        ...  # implementation hidden

-------------------------------------------------
2. Core logic (algorithm sketch – non-normative)
-------------------------------------------------
Step 1 – normalise  
   lower-case, strip punctuation, collapse whitespace, drop emojis, detect language (reject non-EN).

Step 2 – token scan (non-regex, Aho-Corasick)  
   Loaded dicts:  
   STRATEGIC ← {roadmap, vision, goal, kpI, OKR, quarter, year, market, competitor}  
   UI ← {button, color, style, css, layout, font, modal, screen, UX, look, feel}  
   ITERATION ← {next version, improve, enhance, polish, iterate, increment, optimize}  
   DEBUG ← {error, exception, stacktrace, bug, crash, 500, traceback, fail, broken}  
   REVISION ← {change request, amend, update, typo, wording, rephrase, tweak}  
   SCOPE_CHANGE ← {add feature, new page, scope creep, requirement, out of scope, extra}

   Longest-match counts per category.

Step 3 – rule cascade  
   a) If “debug” tokens ≥ 2 → DEBUG  
   b) If “scope” AND (“new” or “add”) → SCOPE_CHANGE  
   c) If STRATEGIC count ≥ 2 or explicit “plan” → STRATEGIC_PLANNING  
   d) If UI count ≥ 2 → UI_REFINEMENT  
   e) If ITERATION count ≥ 2 → ITERATION  
   f) If REVISION count ≥ 2 → REVISION  
   g) Else → largest count; ties broken by fixed precedence:  
      DEBUG > SCOPE_CHANGE > STRATEGIC_PLANNING > UI_REFINEMENT > ITERATION > REVISION

Step 4 – build output  
   confidence = 1.0 (deterministic),  
   reason = “Matched keywords: …”,  
   canonical_prompt = collapse repeated whitespace, truncate 512 chars.

-------------------------------------------------
3. Edge cases & guarantees
-------------------------------------------------
- Empty string or only whitespace → raise ValueError  
- >10 000 characters → raise ValueError  
- Non-English detected (langdetect) → raise ValueError  
- No keyword hits at all → fall back to REVISION (safest human-loop type)  
- Multiple competing high counts → tie-breaker precedence list above  
- Emoji, unicodequotes, urls: stripped, never interpreted  
- Must return same TaskType for same text on any CPU/OS/Python patch (deterministic)  
- No external network, no disk reads after construction, thread-safe, import-time dicts frozen

-------------------------------------------------
4. Explicitly out of scope (what TaskClassifier must NOT do)
-------------------------------------------------
- No LLM calls, no embeddings, no probability sampling  
- No memory of past requests, no personalization  
- No validation of business rules, parameters, or payload shape  
- No classification outside the six enum values  
- No reordering, filtering, or ranking of downstream tasks  
- No user identity, RBAC, or rate-limit logic  
- No persistence, logging, or metrics emission (caller may wrap)
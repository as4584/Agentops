"""
Tool Validator — Hallucination-resistant tool name validation.
==============================================================
Prevents LLMs from invoking tools that don't exist by:
1. Strict membership check against the registered canonical tool set.
2. Fuzzy matching (Levenshtein distance ≤ 2) to suggest corrections.
3. Structured error responses listing available tools.

This module is intentionally free of LangGraph / agent imports so it can
be cheaply imported from any layer of the stack.

Usage::

    from backend.utils.tool_validator import ToolValidator

    validator = ToolValidator(allowed_tools=["safe_shell", "file_reader"])
    result = validator.validate("file_raeder")   # typo
    # result.valid = False
    # result.suggestions = ["file_reader"]
    # result.error_message = "Tool 'file_raeder' not available. Did you mean: file_reader? ..."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """Result of a single tool name validation."""
    valid: bool
    tool_name: str
    canonical_name: Optional[str] = None      # Set when valid or fuzzy-matched
    suggestions: list[str] = field(default_factory=list)
    error_message: str = ""


# ---------------------------------------------------------------------------
# Levenshtein distance (pure Python, no dependencies)
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """
    Compute the Levenshtein edit distance between two strings.

    Uses the standard DP approach with O(min(len(a), len(b))) space.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # Ensure `a` is the shorter string for space optimisation.
    if len(a) > len(b):
        a, b = b, a

    prev = list(range(len(a) + 1))
    for j, cb in enumerate(b, 1):
        curr = [j] + [0] * len(a)
        for i, ca in enumerate(a, 1):
            cost = 0 if ca == cb else 1
            curr[i] = min(
                prev[i] + 1,        # deletion
                curr[i - 1] + 1,    # insertion
                prev[i - 1] + cost, # substitution
            )
        prev = curr

    return prev[len(a)]


# ---------------------------------------------------------------------------
# ToolValidator
# ---------------------------------------------------------------------------

class ToolValidator:
    """
    Validates tool names against an allowed set with fuzzy-match suggestions.

    Args:
        allowed_tools:     Iterable of canonical tool names that are permitted.
        fuzzy_threshold:   Maximum Levenshtein distance to consider a match a
                           "suggestion" (default 2 per spec).
        max_suggestions:   Maximum number of suggestions returned in error messages.
    """

    def __init__(
        self,
        allowed_tools: list[str],
        fuzzy_threshold: int = 2,
        max_suggestions: int = 3,
    ) -> None:
        self._allowed: set[str] = set(allowed_tools)
        self._sorted_allowed: list[str] = sorted(allowed_tools)
        self._threshold = fuzzy_threshold
        self._max_suggestions = max_suggestions

    # ── Public API ───────────────────────────────────────

    def validate(self, tool_name: str) -> ValidationResult:
        """
        Validate a single tool name.

        Returns a ValidationResult with:
        - ``valid=True, canonical_name=tool_name`` if the tool is in the allowed set.
        - ``valid=False, suggestions=[...]`` with fuzzy matches if the tool is unknown.
        - An ``error_message`` suitable for returning as an LLM response.
        """
        if tool_name in self._allowed:
            return ValidationResult(
                valid=True,
                tool_name=tool_name,
                canonical_name=tool_name,
            )

        suggestions = self._fuzzy_suggest(tool_name)
        available_str = ", ".join(self._sorted_allowed) or "none"

        if suggestions:
            did_you_mean = f"Did you mean: {', '.join(suggestions)}? "
        else:
            did_you_mean = ""

        error_message = (
            f"Tool '{tool_name}' is not available. "
            f"{did_you_mean}"
            f"Available tools: {available_str}"
        )

        return ValidationResult(
            valid=False,
            tool_name=tool_name,
            suggestions=suggestions,
            error_message=error_message,
        )

    def validate_batch(self, tool_names: list[str]) -> list[ValidationResult]:
        """Validate a list of tool names, returning one result per entry."""
        return [self.validate(name) for name in tool_names]

    def update_allowed(self, allowed_tools: list[str]) -> None:
        """Replace the allowed tool set (e.g., after agent re-registration)."""
        self._allowed = set(allowed_tools)
        self._sorted_allowed = sorted(allowed_tools)

    def add_tool(self, tool_name: str) -> None:
        """Register one additional allowed tool."""
        self._allowed.add(tool_name)
        if tool_name not in self._sorted_allowed:
            self._sorted_allowed = sorted(self._allowed)

    def is_allowed(self, tool_name: str) -> bool:
        """Quick membership test (no result object)."""
        return tool_name in self._allowed

    @property
    def allowed_tools(self) -> list[str]:
        """Sorted list of currently allowed tool names."""
        return list(self._sorted_allowed)

    # ── Internal ─────────────────────────────────────────

    def _fuzzy_suggest(self, tool_name: str) -> list[str]:
        """
        Return up to *max_suggestions* allowed tool names with
        Levenshtein distance ≤ *fuzzy_threshold* from *tool_name*,
        sorted by distance ascending.
        """
        candidates: list[tuple[int, str]] = []

        for allowed in self._allowed:
            dist = _levenshtein(tool_name.lower(), allowed.lower())
            if dist <= self._threshold:
                candidates.append((dist, allowed))

        candidates.sort(key=lambda t: (t[0], t[1]))
        return [name for _, name in candidates[: self._max_suggestions]]


# ---------------------------------------------------------------------------
# Convenience: build a validator from agent tool_permissions
# ---------------------------------------------------------------------------

def validator_for_agent(tool_permissions: list[str]) -> ToolValidator:
    """
    Convenience factory — creates a ToolValidator pre-loaded with the tools
    declared in an agent's ``tool_permissions`` list.

    Args:
        tool_permissions: The agent definition's ``tool_permissions`` list.

    Returns:
        A ToolValidator scoped to those tools.
    """
    return ToolValidator(allowed_tools=list(tool_permissions))

"""
Tool ID Sanitization — Boundary-layer enforcement for OpenAI/Copilot API compatibility.
========================================================================================
Converts internal tool IDs (which may contain dots, colons, slashes, spaces) into the
strict ``^[a-zA-Z0-9_-]{1,64}$`` pattern required by OpenAI-compatible APIs.

Design decisions:
- Deterministic transformation (same canonical → same sanitized, always).
- Human-readable output: dots/colons/slashes/spaces → underscore.
- Per-conversation ToolIdRegistry prevents cross-conversation collisions.
- Strict validation rejects unknown tools at all API entry points.

Usage::

    from backend.utils.tool_ids import sanitize_tool_id, ToolIdRegistry

    # One-shot sanitization
    clean = sanitize_tool_id("planner.step:1")   # → "planner_step_1"

    # Round-trip registry
    registry = ToolIdRegistry()
    sanitized = registry.register("agent_call/2")   # → "agent_call_2"
    canonical = registry.get_canonical("agent_call_2")  # → "agent_call/2"
"""

from __future__ import annotations

import hashlib
import re
from threading import Lock
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Pattern constants
# ---------------------------------------------------------------------------

# OpenAI/Copilot–compliant tool name pattern.
_VALID_PATTERN: re.Pattern[str] = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Characters not in [a-zA-Z0-9_-] are collapsed to a single underscore.
_INVALID_CHARS: re.Pattern[str] = re.compile(r"[^a-zA-Z0-9_-]+")

# Collapse runs of underscores that arise after sanitization.
_MULTI_UNDERSCORE: re.Pattern[str] = re.compile(r"_{2,}")

# Maximum allowed length per OpenAI spec.
_MAX_LEN: int = 64

# Suffix budget — reserved characters for collision disambiguation (_a3f7).
_SUFFIX_LEN: int = 5  # "_" + 4 hex chars


# ---------------------------------------------------------------------------
# Core sanitization function
# ---------------------------------------------------------------------------

def sanitize_tool_id(raw_id: str) -> str:
    """
    Convert an arbitrary string into an OpenAI-compliant tool ID.

    Transformation steps:
    1. Replace every character outside ``[a-zA-Z0-9_-]`` with ``_``.
    2. Collapse consecutive underscores into one.
    3. Strip leading / trailing underscores.
    4. If empty after stripping, fall back to a deterministic hash.
    5. Truncate to 64 characters (preserving trailing hash suffix when needed).

    Examples::

        sanitize_tool_id("planner.step:1")    → "planner_step_1"
        sanitize_tool_id("agent_call/2")      → "agent_call_2"
        sanitize_tool_id("model:ollama-qwen") → "model_ollama-qwen"
        sanitize_tool_id("tool-call-1.3")     → "tool-call-1_3"

    Args:
        raw_id: The raw, potentially invalid tool identifier.

    Returns:
        A string matching ``^[a-zA-Z0-9_-]{1,64}$``.
    """
    if not raw_id:
        return _fallback_id("empty")

    # Step 1: replace invalid chars
    result = _INVALID_CHARS.sub("_", raw_id)

    # Step 2: collapse multiple underscores
    result = _MULTI_UNDERSCORE.sub("_", result)

    # Step 3: strip leading / trailing underscores
    result = result.strip("_")

    # Step 4: guard against empty result
    if not result:
        return _fallback_id(raw_id)

    # Step 5: enforce max length
    if len(result) > _MAX_LEN:
        result = _truncate_with_hash(result, raw_id)

    return result


def is_valid_tool_id(tool_id: str) -> bool:
    """Return True if *tool_id* already satisfies the OpenAI pattern."""
    return bool(_VALID_PATTERN.match(tool_id))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fallback_id(raw_id: str) -> str:
    """Generate a deterministic, valid ID from a hash when sanitization yields nothing."""
    digest = hashlib.sha256(raw_id.encode()).hexdigest()[:8]
    return f"tool_{digest}"


def _truncate_with_hash(sanitized: str, original: str) -> str:
    """
    Truncate *sanitized* to fit within _MAX_LEN, appending a 4-char hash so
    that two different originals that truncate to the same prefix remain distinct.
    """
    digest = hashlib.sha256(original.encode()).hexdigest()[:4]
    suffix = f"_{digest}"                          # 5 chars total
    avail = _MAX_LEN - len(suffix)
    return sanitized[:avail] + suffix


# ---------------------------------------------------------------------------
# ToolIdRegistry — bidirectional canonical ↔ sanitized mapping
# ---------------------------------------------------------------------------

class ToolIdRegistry:
    """
    Per-conversation bidirectional mapping between canonical tool IDs
    and their sanitized OpenAI-compatible equivalents.

    Thread-safe via an internal lock (safe for async-adjacent usage where
    multiple coroutines may register IDs concurrently in a thread pool).

    Collision handling:
        When two distinct canonical IDs would produce the same sanitized
        form, a deterministic numeric suffix (``_2``, ``_3``, …) is appended
        until the name is unique within this registry instance.

    Example::

        reg = ToolIdRegistry()
        reg.register("planner.step:1")   # → "planner_step_1"
        reg.register("planner_step:1")   # → "planner_step_1_2"  (collision)
        reg.get_canonical("planner_step_1_2")  # → "planner_step:1"
    """

    def __init__(self) -> None:
        self._lock: Lock = Lock()
        # canonical → sanitized
        self._canon_to_sanitized: Dict[str, str] = {}
        # sanitized → canonical  (the first canonical that claimed this sanitized form)
        self._sanitized_to_canon: Dict[str, str] = {}

    # ── Public API ───────────────────────────────────────

    def register(self, canonical: str) -> str:
        """
        Register a canonical tool ID and return its sanitized form.

        Idempotent: registering the same canonical ID twice returns the same
        sanitized form without modifying the registry.

        Args:
            canonical: The raw/internal tool ID.

        Returns:
            The sanitized ID that should be used in API calls.
        """
        with self._lock:
            if canonical in self._canon_to_sanitized:
                return self._canon_to_sanitized[canonical]

            base = sanitize_tool_id(canonical)
            sanitized = self._resolve_collision(base, canonical)

            self._canon_to_sanitized[canonical] = sanitized
            self._sanitized_to_canon[sanitized] = canonical
            return sanitized

    def get_canonical(self, sanitized: str) -> Optional[str]:
        """
        Look up the canonical ID for a sanitized tool name.

        Returns None if *sanitized* has never been registered.
        """
        with self._lock:
            return self._sanitized_to_canon.get(sanitized)

    def get_sanitized(self, canonical: str) -> Optional[str]:
        """
        Look up the sanitized form for a canonical tool name.

        Returns None if *canonical* has never been registered.
        """
        with self._lock:
            return self._canon_to_sanitized.get(canonical)

    def sanitize_tool_definitions(
        self, tools: list[dict]
    ) -> tuple[list[dict], "ToolIdRegistry"]:
        """
        Sanitize a list of OpenAI-format tool definitions in-place.

        Registers every tool name and rewrites the ``function.name`` field.
        Returns the modified list and *self* (for chaining).

        Args:
            tools: List of OpenAI tool objects (``{"type": "function", "function": {...}}``).

        Returns:
            (sanitized_tools, self)
        """
        sanitized: list[dict] = []
        for tool in tools:
            tool_copy = _deep_copy_tool(tool)
            fn = tool_copy.get("function", {})
            original_name: str = fn.get("name", "")
            if original_name:
                fn["name"] = self.register(original_name)
            sanitized.append(tool_copy)
        return sanitized, self

    def desanitize_tool_calls(
        self, tool_calls: list[dict]
    ) -> list[dict]:
        """
        Map sanitized tool names in an LLM response back to canonical names.

        Operates on OpenAI-format tool_calls (``[{"function": {"name": ...}}]``).
        Unknown names are left unchanged (they will fail validation later).

        Args:
            tool_calls: Raw tool_calls block from an OpenAI API response.

        Returns:
            Tool calls with ``function.name`` rewritten to canonical form.
        """
        result: list[dict] = []
        for tc in tool_calls:
            tc_copy = _deep_copy_tool(tc)
            fn = tc_copy.get("function", {})
            sanitized_name: str = fn.get("name", "")
            canonical = self.get_canonical(sanitized_name)
            if canonical is not None:
                fn["name"] = canonical
            result.append(tc_copy)
        return result

    def all_canonical(self) -> list[str]:
        """Return all registered canonical tool IDs."""
        with self._lock:
            return list(self._canon_to_sanitized.keys())

    def all_sanitized(self) -> list[str]:
        """Return all registered sanitized tool IDs."""
        with self._lock:
            return list(self._sanitized_to_canon.keys())

    def clear(self) -> None:
        """Remove all registrations (useful between test cases)."""
        with self._lock:
            self._canon_to_sanitized.clear()
            self._sanitized_to_canon.clear()

    # ── Internal ─────────────────────────────────────────

    def _resolve_collision(self, base: str, canonical: str) -> str:
        """
        Return *base* if unclaimed, otherwise append ``_2``, ``_3``, …
        until an unclaimed name is found.

        The search is O(n) in the number of collisions, which is expected
        to be zero or one in normal operation.
        """
        # If this exact sanitized form was already claimed by a *different* canonical, suffix it.
        if base not in self._sanitized_to_canon:
            return base

        # Already claimed — find next free suffix.
        counter = 2
        while True:
            candidate = f"{base}_{counter}"
            # Shorten base if suffix would exceed max length.
            if len(candidate) > _MAX_LEN:
                allowable = _MAX_LEN - len(f"_{counter}")
                candidate = f"{base[:allowable]}_{counter}"
            if candidate not in self._sanitized_to_canon:
                return candidate
            counter += 1


# ---------------------------------------------------------------------------
# Deterministic tool call ID generator
# ---------------------------------------------------------------------------

def make_tool_call_id(
    agent_id: str,
    tool_name: str,
    sequence: int,
    context: str = "",
) -> str:
    """
    Generate a deterministic, unique tool call ID for a single invocation.

    Format: ``{agent}_{tool}_{context}_{sequence}`` → sanitized.

    Args:
        agent_id:  The calling agent's identifier (e.g. ``"it_agent"``).
        tool_name: The tool being invoked (before sanitization).
        sequence:  A monotonically increasing counter within the conversation.
        context:   Optional extra discriminator (e.g. ``"step3"``).

    Returns:
        A valid tool call ID matching ``^[a-zA-Z0-9_-]{1,64}$``.

    Examples::

        make_tool_call_id("planner", "step", 1)          → "planner_step_1"
        make_tool_call_id("agent", "call", 2, "ctx")     → "agent_call_ctx_2"
        make_tool_call_id("model", "ollama-qwen", 5)     → "model_ollama-qwen_5"
    """
    parts = [agent_id, tool_name]
    if context:
        parts.append(context)
    parts.append(str(sequence))

    raw = "_".join(parts)
    return sanitize_tool_id(raw)


# ---------------------------------------------------------------------------
# Utility: validate a batch of tool definitions
# ---------------------------------------------------------------------------

def validate_tool_definitions(tools: list[dict]) -> list[str]:
    """
    Check every ``function.name`` in a list of OpenAI tool definitions against
    the strict pattern. Returns a list of violation messages (empty = all valid).

    Args:
        tools: OpenAI-format tool objects.

    Returns:
        List of human-readable violation strings.
    """
    violations: list[str] = []
    for idx, tool in enumerate(tools):
        fn = tool.get("function", {})
        name = fn.get("name", "")
        if not name:
            violations.append(f"tools[{idx}]: missing function.name")
        elif not is_valid_tool_id(name):
            violations.append(
                f"tools[{idx}] name={name!r}: does not match ^[a-zA-Z0-9_-]{{1,64}}$"
            )
    return violations


# ---------------------------------------------------------------------------
# Local helper
# ---------------------------------------------------------------------------

def _deep_copy_tool(tool: dict) -> dict:
    """Shallow-copy a tool dict, deep-copying the nested 'function' sub-dict."""
    import copy
    result = dict(tool)
    if "function" in result:
        result["function"] = dict(result["function"])
    if "function" in tool and "parameters" in tool["function"]:
        result["function"]["parameters"] = copy.deepcopy(tool["function"]["parameters"])
    return result

"""
Action proposer — detect remediation intent in a user message and emit a
``ProposedAction`` instead of letting the LLM describe the action in prose.

Week 2 sprint A4. Used by the knowledge_agent path in the orchestrator so
small local models cannot "hallucinate" an execution: any remediation step
becomes a structured, operator-approvable proposal.

The detector is intentionally deterministic (regex over verbs + nouns) so
test outcomes are stable across LLM versions. It is also intentionally
permissive — it does NOT validate the target against the executor's
whitelist; that check lives in the executor at approval time and surfaces
as a ``failed`` audit row if rejected.
"""

from __future__ import annotations

import re

from backend.models.actions import ActionSource, ProposedAction

# Restart-style verbs the operator might use when describing a remediation.
_RESTART_VERBS = (
    "restart",
    "reboot",
    "bounce",
    "recycle",
    "reload",
    "kick",
)

# "<verb> [the] <name>"
_PATTERN_VERB_NOUN = re.compile(
    r"\b(?:" + "|".join(_RESTART_VERBS) + r")\s+(?:the\s+)?([a-z][a-z0-9_-]{1,40})\b",
    re.IGNORECASE,
)

# "<name> is down/crashed/... <restart|fix|bounce> ..."
_PATTERN_DOWN_VERB = re.compile(
    r"\b([a-z][a-z0-9_-]{1,40})\s+is\s+(?:down|crashed|broken|failing|stuck|hung|dead|unresponsive)\b"
    r"[^.?!]{0,80}?\b(?:" + "|".join(_RESTART_VERBS) + r"|fix|repair)\b",
    re.IGNORECASE,
)

# Words that follow a restart verb but are clearly NOT a process name.
_NOUN_STOPWORDS = frozenset(
    {
        "it",
        "them",
        "this",
        "that",
        "the",
        "a",
        "an",
        "everything",
        "all",
        "things",
        "stuff",
        "please",
        "now",
        "again",
        "service",
        "server",
        "process",
        "container",
        "pod",
    }
)


def detect_remediation_intent(
    message: str,
    agent_id: str = "knowledge_agent",
    source: ActionSource | str = ActionSource.WEB,
) -> ProposedAction | None:
    """Return a ``ProposedAction`` if *message* describes a restart-style remediation.

    Returns ``None`` for pure information queries (e.g. "is nginx running?",
    "what is nginx?"). When a remediation is detected, the returned action is
    NOT yet persisted — the caller is responsible for ``actions_store.insert``.
    """
    if not message or not isinstance(message, str):
        return None

    text = message.strip()
    process_name = _extract_process_name(text)
    if process_name is None:
        return None

    src = ActionSource(source) if isinstance(source, str) else source
    return ProposedAction(
        agent_id=agent_id,
        action_type="process_restart",
        parameters={"process_name": process_name},
        summary=f"Restart {process_name} (proposed from: {text[:120]})",
        source=src,
    )


def _extract_process_name(text: str) -> str | None:
    """Pull the first plausible process name out of *text*. Returns ``None`` if none found."""
    # Prefer the "X is down ... restart" framing — the subject is the target.
    m = _PATTERN_DOWN_VERB.search(text)
    if m:
        candidate = m.group(1).lower()
        if candidate not in _NOUN_STOPWORDS:
            return candidate

    # Otherwise look for "restart X" style.
    for match in _PATTERN_VERB_NOUN.finditer(text):
        candidate = match.group(1).lower()
        if candidate in _NOUN_STOPWORDS:
            continue
        return candidate

    return None

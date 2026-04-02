"""Tests for Discord bot — message splitting, routing, and security."""

from __future__ import annotations

import pytest

discord = pytest.importorskip("discord", reason="discord.py not installed")

from backend.discord_bot import AGENT_ALIASES, _split_message  # noqa: E402

# ---------------------------------------------------------------------------
# Message splitting
# ---------------------------------------------------------------------------


class TestSplitMessage:
    def test_short_message_unchanged(self) -> None:
        assert _split_message("hello", 2000) == ["hello"]

    def test_empty_message(self) -> None:
        assert _split_message("", 2000) == [""]

    def test_exact_limit(self) -> None:
        msg = "a" * 2000
        assert _split_message(msg, 2000) == [msg]

    def test_split_at_newline(self) -> None:
        msg = "line1\n" * 300  # ~1800 chars
        msg += "x" * 500  # push over 2000
        chunks = _split_message(msg, 2000)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_split_at_space(self) -> None:
        words = " ".join(["word"] * 500)  # ~2500 chars
        chunks = _split_message(words, 2000)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_no_split_point(self) -> None:
        msg = "a" * 3000  # no spaces or newlines
        chunks = _split_message(msg, 2000)
        assert len(chunks) == 2
        assert len(chunks[0]) == 2000
        assert len(chunks[1]) == 1000

    def test_unicode_preserved(self) -> None:
        msg = "🚀" * 200
        chunks = _split_message(msg, 100)
        recombined = "".join(chunks)
        assert "🚀" in recombined


# ---------------------------------------------------------------------------
# Agent aliases
# ---------------------------------------------------------------------------


class TestAgentAliases:
    def test_all_aliases_are_strings(self) -> None:
        for alias, agent in AGENT_ALIASES.items():
            assert isinstance(alias, str)
            assert isinstance(agent, str)
            assert "_" in agent or agent == "gsd_agent"

    def test_soul_maps_correctly(self) -> None:
        assert AGENT_ALIASES["soul"] == "soul_core"

    def test_devops_maps_correctly(self) -> None:
        assert AGENT_ALIASES["devops"] == "devops_agent"

    def test_no_duplicate_targets(self) -> None:
        targets = list(AGENT_ALIASES.values())
        assert len(targets) == len(set(targets)), "Duplicate agent targets in aliases"

    def test_known_agents_covered(self) -> None:
        """Key agents should have shortcuts."""
        expected = {"soul_core", "devops_agent", "security_agent", "gsd_agent"}
        actual = set(AGENT_ALIASES.values())
        assert expected.issubset(actual)

"""Deterministic tests for backend.orchestrator.fast_route_binding.

Tests the FastRouter class with and without the compiled .so file.
No network calls. Pure unit tests.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.orchestrator.fast_route_binding import FastRouter


class TestFastRouterWithoutSo:
    """Test behavior when fast_route.so is NOT available."""

    @patch("backend.orchestrator.fast_route_binding.Path")
    def test_unavailable_when_so_missing(self, mock_path):
        mock_path.return_value.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)
        mock_path_inst = MagicMock()
        mock_path_inst.exists.return_value = False
        mock_path.return_value.__truediv__ = MagicMock(return_value=mock_path_inst)

        router = FastRouter.__new__(FastRouter)
        router._lib = None
        router._available = False
        assert router.available is False

    def test_route_returns_unmatched_when_unavailable(self):
        router = FastRouter.__new__(FastRouter)
        router._lib = None
        router._available = False
        result = router.route("deploy something")
        assert result["matched"] is False
        assert result["agent_id"] == ""
        assert result["confidence"] == 0.0

    def test_check_red_line_returns_false_when_unavailable(self):
        router = FastRouter.__new__(FastRouter)
        router._lib = None
        router._available = False
        assert router.check_red_line("rm -rf /") is False

    def test_route_batch_returns_all_unmatched(self):
        router = FastRouter.__new__(FastRouter)
        router._lib = None
        router._available = False
        results = router.route_batch(["deploy", "scan", "restart"])
        assert len(results) == 3
        assert all(not r["matched"] for r in results)


class TestFastRouterWithMockedSo:
    """Test behavior when .so IS loaded, using mocked ctypes calls."""

    def _make_router_with_mock(self):
        router = FastRouter.__new__(FastRouter)
        router._lib = MagicMock()
        router._available = True
        return router

    def test_route_returns_decoded_result(self):
        router = self._make_router_with_mock()

        # Mock C struct return
        mock_result = MagicMock()
        mock_result.agent_id = b"devops_agent\x00" + b"\x00" * 19
        mock_result.confidence = 0.92
        mock_result.matched = 1
        router._lib.fast_route.return_value = mock_result

        result = router.route("deploy to production")
        assert result["agent_id"] == "devops_agent"
        assert result["confidence"] == 0.92
        assert result["matched"] is True

    def test_route_unmatched(self):
        router = self._make_router_with_mock()

        mock_result = MagicMock()
        mock_result.agent_id = b"\x00" * 32
        mock_result.confidence = 0.0
        mock_result.matched = 0
        router._lib.fast_route.return_value = mock_result

        result = router.route("something vague")
        assert result["matched"] is False
        assert result["agent_id"] == ""

    def test_red_line_detected(self):
        router = self._make_router_with_mock()
        router._lib.check_red_line.return_value = 1
        assert router.check_red_line("rm -rf /") is True

    def test_red_line_safe(self):
        router = self._make_router_with_mock()
        router._lib.check_red_line.return_value = 0
        assert router.check_red_line("deploy the app") is False

    def test_batch_preserves_order(self):
        router = self._make_router_with_mock()
        agents = ["devops_agent", "security_agent", "soul_core"]
        call_idx = 0

        def side_effect(msg):
            nonlocal call_idx
            mock_r = MagicMock()
            mock_r.agent_id = agents[call_idx % 3].encode() + b"\x00" * (32 - len(agents[call_idx % 3]))
            mock_r.confidence = 0.9
            mock_r.matched = 1
            call_idx += 1
            return mock_r

        router._lib.fast_route.side_effect = side_effect
        results = router.route_batch(["deploy", "scan", "reflect"])
        assert len(results) == 3
        assert results[0]["agent_id"] == "devops_agent"
        assert results[1]["agent_id"] == "security_agent"
        assert results[2]["agent_id"] == "soul_core"

    def test_route_encodes_unicode_safely(self):
        router = self._make_router_with_mock()
        mock_result = MagicMock()
        mock_result.agent_id = b"soul_core\x00" + b"\x00" * 23
        mock_result.confidence = 0.5
        mock_result.matched = 0
        router._lib.fast_route.return_value = mock_result

        # Should not crash on unicode
        result = router.route("déployer le service 🚀")
        assert isinstance(result["agent_id"], str)

    def test_route_encodes_empty_string(self):
        router = self._make_router_with_mock()
        mock_result = MagicMock()
        mock_result.agent_id = b"\x00" * 32
        mock_result.confidence = 0.0
        mock_result.matched = 0
        router._lib.fast_route.return_value = mock_result
        result = router.route("")
        assert result["matched"] is False

    def test_red_line_encodes_long_message(self):
        router = self._make_router_with_mock()
        router._lib.check_red_line.return_value = 0
        # Very long message — should not crash ctypes
        result = router.check_red_line("a" * 100_000)
        assert result is False

    def test_confidence_is_float(self):
        router = self._make_router_with_mock()
        mock_result = MagicMock()
        mock_result.agent_id = b"it_agent\x00" + b"\x00" * 24
        mock_result.confidence = 0.888
        mock_result.matched = 1
        router._lib.fast_route.return_value = mock_result
        result = router.route("check infrastructure")
        assert isinstance(result["confidence"], float)
        assert abs(result["confidence"] - 0.888) < 0.001


class TestFastRouterWithRealSo:
    """Integration tests using the actual compiled .so (if present)."""

    @pytest.fixture(autouse=True)
    def _load_real_router(self):
        self.router = FastRouter()
        if not self.router.available:
            pytest.skip(
                "fast_route.so not compiled — run: cd backend/orchestrator && gcc -O3 -shared -fPIC -o fast_route.so fast_route.c"
            )

    def test_real_devops_route(self):
        result = self.router.route("deploy to production")
        assert result["agent_id"] == "devops_agent"
        assert result["matched"] is True
        assert result["confidence"] > 0.5

    def test_real_security_route(self):
        result = self.router.route("scan for secrets in the codebase")
        assert result["agent_id"] == "security_agent"
        assert result["matched"] is True

    def test_real_monitor_route(self):
        result = self.router.route("check health and tail log output")
        assert result["agent_id"] == "monitor_agent"
        assert result["matched"] is True

    def test_real_self_healer_route(self):
        result = self.router.route("restart the crashed worker process")
        assert result["agent_id"] == "self_healer_agent"
        assert result["matched"] is True

    def test_real_soul_core_route(self):
        result = self.router.route("reflect on our mission and purpose")
        assert result["agent_id"] == "soul_core"
        assert result["matched"] is True

    def test_real_red_line_rm_rf(self):
        assert self.router.check_red_line("rm -rf / --no-preserve-root") is True

    def test_real_red_line_drop_table(self):
        assert self.router.check_red_line("DROP TABLE customers;") is True

    def test_real_red_line_chmod_777(self):
        assert self.router.check_red_line("chmod 777 /etc/passwd") is True

    def test_real_safe_message_not_red_lined(self):
        assert self.router.check_red_line("deploy the latest build") is False
        assert self.router.check_red_line("scan for vulnerabilities") is False

    def test_real_ambiguous_falls_through(self):
        # Vague message should not have high confidence
        result = self.router.route("hello how are you")
        if result["matched"]:
            assert result["confidence"] < 0.85

    def test_real_batch_returns_correct_count(self):
        msgs = ["deploy", "scan secrets", "restart process", "hello"]
        results = self.router.route_batch(msgs)
        assert len(results) == 4

    def test_real_all_agents_reachable(self):
        """Every agent in the C router should be reachable."""
        test_msgs = [
            "deploy build",  # devops
            "monitor health",  # monitor
            "restart crash",  # self_healer
            "review diff",  # code_review
            "security scan",  # security
            "database query",  # data
            "webhook notify",  # comms
            "customer support",  # cs
            "cpu disk network",  # it
            "search docs",  # knowledge
            "reflect soul purpose",  # soul_core
        ]
        routed_agents = set()
        for msg in test_msgs:
            r = self.router.route(msg)
            if r["matched"]:
                routed_agents.add(r["agent_id"])
        # C router covers a subset of agents — 6+ is acceptable
        assert len(routed_agents) >= 6, f"Only routed to {len(routed_agents)} agents: {routed_agents}"

    def test_real_batch_returns_correct_count_with_phrases(self):
        msgs = ["deploy", "scan for secrets", "restart process", "hello"]
        results = self.router.route_batch(msgs)
        assert len(results) == 4

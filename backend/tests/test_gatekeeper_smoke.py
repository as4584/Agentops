from backend.agents.gatekeeper_agent import GatekeeperAgent


def test_gatekeeper_rejects_runtime_without_tests():
    gatekeeper = GatekeeperAgent()
    result = gatekeeper.review_mutation(
        {
            "files_changed": ["frontend/src/app/page.tsx"],
            "syntax_ok": True,
            "secrets_ok": True,
            "lighthouse_ok": True,
        }
    )
    assert result.approved is False
    assert any("TDD violation" in item for item in result.violations)


def test_gatekeeper_rejects_local_without_sandbox_and_playbox():
    gatekeeper = GatekeeperAgent()
    result = gatekeeper.review_mutation(
        {
            "files_changed": ["backend/orchestrator/__init__.py", "backend/tests/test_orchestrator.py"],
            "source_model": "local",
            "tests_ok": True,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
            "syntax_ok": True,
            "secrets_ok": True,
            "lighthouse_ok": True,
        }
    )
    assert result.approved is False
    assert any("sandbox_session_id" in item for item in result.violations)
    assert any("playbox" in item for item in result.violations)


def test_gatekeeper_approves_local_when_all_checks_pass():
    gatekeeper = GatekeeperAgent()
    result = gatekeeper.review_mutation(
        {
            "files_changed": ["backend/orchestrator/__init__.py", "backend/tests/test_orchestrator.py"],
            "source_model": "local",
            "sandbox_session_id": "session-1234",
            "staged_in_playbox": True,
            "tests_ok": True,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
            "syntax_ok": True,
            "secrets_ok": True,
            "lighthouse_ok": True,
        }
    )
    assert result.approved is True
    assert result.violations == []

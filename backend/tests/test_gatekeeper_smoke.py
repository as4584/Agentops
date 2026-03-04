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

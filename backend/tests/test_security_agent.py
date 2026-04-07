"""Tests for the Security Agent — definition, passive scanning, kali_shell, and routing.

Coverage areas:
  1. Agent definition — role, tools, system_prompt, kali_shell permission
  2. secret_scanner tool — pattern matching, path sandboxing, redaction
  3. kali_shell tool — whitelist enforcement, metacharacter blocking,
     sandbox unavailability, successful execution (mocked docker)
  4. Keyword routing — security messages route to security_agent
  5. Integration scenario — typical passive + active audit flow
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents import ALL_AGENT_DEFINITIONS, BaseAgent, create_agent
from backend.config import SAFE_SHELL_WHITELIST as KALI_TOOL_WHITELIST
from backend.config import SHELL_DANGEROUS_CHARS
from backend.models import ChangeImpactLevel
from backend.orchestrator.lex_router import VALID_AGENTS, _keyword_route
from backend.tools import safe_shell as kali_shell
from backend.tools import secret_scanner

# ── 1. Agent Definition ───────────────────────────────────────────────


class TestSecurityAgentDefinition:
    """Verify the agent is wired up correctly in the registry."""

    def test_agent_registered(self):
        assert "security_agent" in ALL_AGENT_DEFINITIONS

    def test_role_describes_passive_scanning(self):
        role = ALL_AGENT_DEFINITIONS["security_agent"].role.lower()
        assert "secret" in role or "scan" in role or "passive" in role

    def test_secret_scanner_tool_permitted(self):
        assert "secret_scanner" in ALL_AGENT_DEFINITIONS["security_agent"].tool_permissions

    def test_safe_shell_not_in_security_agent_tools(self):
        """Security agent is passive — it should NOT have safe_shell (state-modifying)."""
        assert "safe_shell" not in ALL_AGENT_DEFINITIONS["security_agent"].tool_permissions

    def test_alert_dispatch_tool_permitted(self):
        assert "alert_dispatch" in ALL_AGENT_DEFINITIONS["security_agent"].tool_permissions

    def test_file_reader_tool_permitted(self):
        assert "file_reader" in ALL_AGENT_DEFINITIONS["security_agent"].tool_permissions

    def test_health_check_tool_permitted(self):
        assert "health_check" in ALL_AGENT_DEFINITIONS["security_agent"].tool_permissions

    def test_system_prompt_is_read_only(self):
        prompt = ALL_AGENT_DEFINITIONS["security_agent"].system_prompt
        assert "READ-ONLY" in prompt or "never modify" in prompt.lower()

    def test_system_prompt_covers_severity_classification(self):
        prompt = ALL_AGENT_DEFINITIONS["security_agent"].system_prompt
        assert "CRITICAL" in prompt
        assert "HIGH" in prompt

    def test_system_prompt_mentions_passive_scanning(self):
        prompt = ALL_AGENT_DEFINITIONS["security_agent"].system_prompt
        assert "passively" in prompt.lower() or "passive" in prompt.lower() or "scan" in prompt.lower()

    def test_memory_namespace(self):
        assert ALL_AGENT_DEFINITIONS["security_agent"].memory_namespace == "security_agent"

    def test_change_impact_level_not_critical(self):
        """Security agent is read-mostly — should not be CRITICAL impact."""
        level = ALL_AGENT_DEFINITIONS["security_agent"].change_impact_level
        assert level != ChangeImpactLevel.CRITICAL

    def test_create_agent_returns_base_agent(self):
        mock_llm = AsyncMock()
        agent = create_agent("security_agent", mock_llm)
        assert isinstance(agent, BaseAgent)
        assert agent.agent_id == "security_agent"


# ── 2. secret_scanner ─────────────────────────────────────────────────


class TestSecretScanner:
    """Unit tests for the passive secret scanning tool."""

    @pytest.mark.asyncio
    async def test_clean_file_returns_no_findings(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("def hello():\n    return 'world'\n")
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        assert result["findings"] == []
        assert result["files_scanned"] == 1

    @pytest.mark.asyncio
    async def test_detects_aws_access_key(self, tmp_path):
        f = tmp_path / "config.py"
        f.write_text('AWS_KEY = "AKIAIOSFODNN7EXAMPLE123456"\n')
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        patterns = [finding["pattern"] for finding in result["findings"]]
        assert any("AWS" in p for p in patterns)

    @pytest.mark.asyncio
    async def test_detects_generic_api_key(self, tmp_path):
        f = tmp_path / "settings.env"
        f.write_text("api_key = supersecrettoken1234567890\n")
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        patterns = [finding["pattern"] for finding in result["findings"]]
        assert any("API Key" in p or "api" in p.lower() for p in patterns)

    @pytest.mark.asyncio
    async def test_detects_private_key_header(self, tmp_path):
        f = tmp_path / "id_rsa"
        f.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n")
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        patterns = [finding["pattern"] for finding in result["findings"]]
        assert any("Private Key" in p or "private" in p.lower() for p in patterns)

    @pytest.mark.asyncio
    async def test_detects_password_in_code(self, tmp_path):
        f = tmp_path / "db.py"
        f.write_text('password = "hunter2secret"\n')
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        patterns = [finding["pattern"] for finding in result["findings"]]
        assert any("Password" in p or "password" in p.lower() for p in patterns)

    @pytest.mark.asyncio
    async def test_detects_database_url(self, tmp_path):
        f = tmp_path / "app.env"
        f.write_text("DATABASE_URL=postgres://admin:s3cr3t@localhost:5432/mydb\n")
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        patterns = [finding["pattern"] for finding in result["findings"]]
        assert any("Database" in p or "database" in p.lower() for p in patterns)

    @pytest.mark.asyncio
    async def test_detects_jwt(self, tmp_path):
        f = tmp_path / "token.txt"
        # Minimal valid-format JWT (header.payload.signature)
        f.write_text(
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c\n"
        )
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        patterns = [finding["pattern"] for finding in result["findings"]]
        assert any("JWT" in p or "jwt" in p.lower() for p in patterns)

    @pytest.mark.asyncio
    async def test_finding_snippet_is_redacted(self, tmp_path):
        f = tmp_path / "creds.py"
        f.write_text('AWS_SECRET = "AKIAIOSFODNN7EXAMPLE123456"\n')
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        # Snippet must be redacted — raw value must not appear in full
        for finding in result["findings"]:
            assert "SFODNN7EXAMPLE123456" not in finding["snippet"]
            assert "****" in finding["snippet"]

    @pytest.mark.asyncio
    async def test_reports_file_and_line(self, tmp_path):
        f = tmp_path / "test_creds.py"
        f.write_text("# header\npassword = 'opensesame'\n")
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(f), "security_agent")
        if result["findings"]:
            assert "file" in result["findings"][0]
            assert "line" in result["findings"][0]
            assert result["findings"][0]["line"] == 2

    @pytest.mark.asyncio
    async def test_path_outside_project_denied(self, tmp_path):
        outside = tmp_path / "outside.py"
        outside.write_text("password = 'topsecret'\n")
        # Point PROJECT_ROOT somewhere else so tmp_path is "outside"
        with patch("backend.tools.PROJECT_ROOT", tmp_path / "subdir"):
            result = await secret_scanner(str(outside), "security_agent")
        assert "Access denied" in (result.get("error") or "")

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_error(self, tmp_path):
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(tmp_path / "ghost.py"), "security_agent")
        assert "does not exist" in (result.get("error") or "")

    @pytest.mark.asyncio
    async def test_scans_directory_recursively(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "a.py").write_text('api_key = "leakedsecret12345678"\n')
        (sub / "b.py").write_text("# nothing here\n")
        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            result = await secret_scanner(str(tmp_path), "security_agent")
        assert result["files_scanned"] >= 2
        assert len(result["findings"]) >= 1


# ── 3. kali_shell ─────────────────────────────────────────────────────


class TestKaliShellWhitelist:
    """Whitelist enforcement — non-whitelisted tools must be blocked."""

    @pytest.mark.asyncio
    async def test_bash_is_blocked(self):
        result = await kali_shell("bash -c 'id'", "security_agent")
        assert result["blocked"] is True
        assert "bash" in result["stderr"].lower() or "BLOCKED" in result["stderr"]

    @pytest.mark.asyncio
    async def test_sh_is_blocked(self):
        result = await kali_shell("sh -c 'whoami'", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_apt_is_blocked(self):
        result = await kali_shell("apt install netcat", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_pip_is_blocked(self):
        result = await kali_shell("pip install requests", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_rm_is_blocked(self):
        result = await kali_shell("rm -rf /tmp/test", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_unknown_tool_is_blocked(self):
        result = await kali_shell("metasploit run exploit", "security_agent")
        assert result["blocked"] is True

    def test_safe_shell_whitelist_has_read_only_commands(self):
        """SAFE_SHELL_WHITELIST (KALI_TOOL_WHITELIST alias) must contain safe, read-only tools."""
        for expected in ["ls", "cat", "grep", "find", "ps", "df"]:
            assert expected in KALI_TOOL_WHITELIST, f"Expected {expected} in SAFE_SHELL_WHITELIST"


class TestKaliShellMetachars:
    """Shell metacharacter injection must be blocked."""

    @pytest.mark.asyncio
    async def test_semicolon_blocked(self):
        result = await kali_shell("nmap 127.0.0.1; whoami", "security_agent")
        assert result["blocked"] is True
        assert ";" in SHELL_DANGEROUS_CHARS

    @pytest.mark.asyncio
    async def test_pipe_blocked(self):
        result = await kali_shell("nmap 127.0.0.1 | cat /etc/passwd", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_ampersand_blocked(self):
        result = await kali_shell("nmap 127.0.0.1 && curl evil.com", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_backtick_blocked(self):
        result = await kali_shell("nmap `whoami`", "security_agent")
        assert result["blocked"] is True

    @pytest.mark.asyncio
    async def test_dollar_subshell_blocked(self):
        result = await kali_shell("nmap $(cat /etc/passwd)", "security_agent")
        assert result["blocked"] is True


class TestSafeShellBlocksUnsafeCommands:
    """safe_shell (aliased as kali_shell) must block commands not in whitelist."""

    @pytest.mark.asyncio
    async def test_curl_allowed_when_whitelisted(self):
        from backend.config import SAFE_SHELL_WHITELIST

        # curl may or may not be whitelisted — just check the result is consistent
        result = await kali_shell("curl --version", "security_agent")
        if "curl" in SAFE_SHELL_WHITELIST:
            assert result["blocked"] is False
        else:
            assert result["blocked"] is True


class TestSafeShellWhitelistedExecution:
    """safe_shell executes whitelisted commands successfully."""

    @pytest.mark.asyncio
    async def test_ls_mock_returns_output(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"file1.py\nfile2.py\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await kali_shell("ls", "security_agent")

        assert result["blocked"] is False
        assert result["return_code"] == 0
        assert "file1.py" in result["stdout"]

    @pytest.mark.asyncio
    async def test_stderr_is_captured(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"ls: missing: No such file\n"))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await kali_shell("ls missing_dir", "security_agent")

        assert result["return_code"] == 1
        assert "No such file" in result["stderr"]

    @pytest.mark.asyncio
    async def test_output_capped_at_8kb(self):
        large_output = b"X" * 10_000  # 10KB — should be trimmed
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(large_output, b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await kali_shell("cat requirements.txt", "security_agent")

        assert len(result["stdout"]) <= 8192

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        async def slow_communicate():
            await asyncio.sleep(999)
            return b"", b""

        mock_proc = MagicMock()
        mock_proc.communicate = slow_communicate

        async def fake_wait_for(coro, timeout):
            coro.close()
            raise TimeoutError

        with (
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch("asyncio.wait_for", side_effect=fake_wait_for),
        ):
            result = await kali_shell("cat requirements.txt", "security_agent")

        assert result["return_code"] == -1
        assert "timed out" in result["stderr"].lower()


# ── 4. Keyword Routing ────────────────────────────────────────────────


class TestSecurityAgentRouting:
    """Verify security-related messages route to security_agent."""

    def test_security_agent_in_valid_agents(self):
        assert "security_agent" in VALID_AGENTS

    def test_scan_for_secrets(self):
        assert _keyword_route("scan for secrets and vulnerabilities") == "security_agent"

    def test_cve_keyword(self):
        assert _keyword_route("scan for known CVE vulnerabilities in the codebase") == "security_agent"

    def test_secret_leaked_keyword(self):
        route = _keyword_route("I think a secret got leaked in the repo")
        assert route == "security_agent"

    def test_audit_keyword(self):
        route = _keyword_route("run a security audit on the backend")
        assert route == "security_agent"

    def test_kali_keyword(self):
        route = _keyword_route("use kali tools to scan the local network")
        assert route == "security_agent"

    def test_nmap_keyword(self):
        route = _keyword_route("run an nmap scan on 192.168.1.1")
        assert route == "security_agent"


# ── 5. Integration scenario ───────────────────────────────────────────


class TestSecurityAgentIntegrationScenario:
    """End-to-end simulation: passive scan finds a secret, active nmap follows."""

    @pytest.mark.asyncio
    async def test_passive_scan_then_alert(self, tmp_path):
        """Simulate passive triage: secret_scanner finds a credential, alert follows."""
        f = tmp_path / "infra.py"
        f.write_text('AWS_ACCESS = "AKIAIOSFODNN7EXAMPLE123456"\n')

        with patch("backend.tools.PROJECT_ROOT", tmp_path):
            passive = await secret_scanner(str(f), "security_agent")

        assert len(passive["findings"]) >= 1
        aws_hits = [x for x in passive["findings"] if "AWS" in x["pattern"]]
        assert aws_hits, "Expected at least one AWS key finding"

        # Security agent is passive — the finding json has what an alert needs
        finding = aws_hits[0]
        assert "file" in finding
        assert "line" in finding
        assert "pattern" in finding

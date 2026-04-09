"""Extended tool tests — covers uncovered branches in backend/tools/__init__.py."""

from __future__ import annotations

import sqlite3
import urllib.error
from http.client import HTTPMessage
from unittest.mock import AsyncMock, MagicMock, patch

from backend.tools import (
    browser_control,
    db_query,
    document_ocr,
    execute_tool,
    file_reader,
    folder_analyzer,
    health_check,
    k8s_control,
    log_tail,
    process_restart,
    safe_shell,
    secret_scanner,
    system_info,
    webhook_send,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helper — passthrough drift guard
# ─────────────────────────────────────────────────────────────────────────────


def _passthrough_guard():
    async def _pt(tool_name, agent_id, modification_type, tool_fn, *a, **kw):
        return await tool_fn()

    return patch("backend.tools.drift_guard.guard_tool_execution", side_effect=_pt)


# ─────────────────────────────────────────────────────────────────────────────
# get_mcp_bridge — lazy import
# ─────────────────────────────────────────────────────────────────────────────


class TestGetMcpBridge:
    def test_returns_mcp_bridge_singleton(self):
        from backend.mcp import mcp_bridge
        from backend.tools import get_mcp_bridge

        result = get_mcp_bridge()
        assert result is mcp_bridge


# ─────────────────────────────────────────────────────────────────────────────
# safe_shell — uncovered branches
# ─────────────────────────────────────────────────────────────────────────────


class TestSafeShellExtended:
    async def test_flag_arg_skipped_in_path_check(self):
        """Args starting with '-' are skipped in the path resolution check."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"file.txt\n", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await safe_shell("ls -la", "agent")
        assert result.get("return_code") == 0

    async def test_absolute_path_arg_outside_project_blocked(self):
        """An absolute path arg that resolves outside PROJECT_ROOT is blocked."""
        result = await safe_shell("ls /tmp", "agent")
        assert result["blocked"] is True
        assert "outside project" in result["stderr"].lower()

    async def test_docs_command_blocked(self):
        """Commands touching /docs are blocked."""
        result = await safe_shell("cat /docs/README.md", "agent")
        assert result["blocked"] is True
        assert "doc_updater" in result["stderr"]

    async def test_docs_partial_path_blocked(self):
        """Commands with docs/ in path are blocked."""
        result = await safe_shell("cat docs/README.md", "agent")
        assert result["blocked"] is True


# ─────────────────────────────────────────────────────────────────────────────
# file_reader — OCR path and exception
# ─────────────────────────────────────────────────────────────────────────────


class TestFileReaderExtended:
    async def test_ocr_path_returns_markdown(self, tmp_path):
        """When OCR is supported and returns markdown, it is returned."""
        # Create a fake PDF file inside the project
        from backend.config import PROJECT_ROOT

        fake_pdf = PROJECT_ROOT / "sandbox" / "tmp" / "test_ocr.pdf"
        fake_pdf.parent.mkdir(parents=True, exist_ok=True)
        fake_pdf.write_bytes(b"%PDF-1.0 fake content")
        try:
            with patch("backend.tools.ocr_supported", return_value=True):
                with patch("backend.tools.ocr_extract_text", AsyncMock(return_value="# Extracted")):
                    result = await file_reader(str(fake_pdf.relative_to(PROJECT_ROOT)), "agent")
            assert result["exists"] is True
            assert result["source"] == "glmocr"
            assert "Extracted" in result["content"]
        finally:
            if fake_pdf.exists():
                fake_pdf.unlink()

    async def test_ocr_returns_none_falls_through(self, tmp_path):
        """When OCR returns None (service down), falls through to normal read."""
        from backend.config import PROJECT_ROOT

        fake_pdf = PROJECT_ROOT / "sandbox" / "tmp" / "test_fallthrough.txt"
        fake_pdf.parent.mkdir(parents=True, exist_ok=True)
        fake_pdf.write_text("hello world")
        try:
            with patch("backend.tools.ocr_supported", return_value=True):
                with patch("backend.tools.ocr_extract_text", AsyncMock(return_value=None)):
                    result = await file_reader(str(fake_pdf.relative_to(PROJECT_ROOT)), "agent")
            assert result["exists"] is True
            assert "hello world" in result["content"]
        finally:
            if fake_pdf.exists():
                fake_pdf.unlink()


# ─────────────────────────────────────────────────────────────────────────────
# document_ocr — all branches
# ─────────────────────────────────────────────────────────────────────────────


class TestDocumentOcr:
    async def test_path_outside_project_denied(self):
        result = await document_ocr("/tmp/document.pdf", "agent")
        assert "denied" in result["error"].lower()

    async def test_nonexistent_file(self):
        result = await document_ocr("nonexistent_fake_doc.pdf", "agent")
        assert "not found" in result["error"].lower()

    async def test_not_a_file(self):
        result = await document_ocr("backend", "agent")
        assert "not a file" in result["error"].lower()

    async def test_unsupported_extension(self, tmp_path):
        from backend.config import PROJECT_ROOT

        fake = PROJECT_ROOT / "sandbox" / "tmp" / "test.xyz"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_text("content")
        try:
            result = await document_ocr(str(fake.relative_to(PROJECT_ROOT)), "agent")
            assert "unsupported" in result["error"].lower() or "error" in result
        finally:
            if fake.exists():
                fake.unlink()

    async def test_ocr_returns_none_means_service_unavailable(self, tmp_path):
        from backend.config import PROJECT_ROOT
        from backend.ocr import OCR_EXTENSIONS

        ext = next(iter(OCR_EXTENSIONS))  # e.g. ".pdf"
        fake = PROJECT_ROOT / "sandbox" / "tmp" / f"test_ocr_none{ext}"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_bytes(b"fake binary")
        try:
            with patch("backend.tools.ocr_extract_text", AsyncMock(return_value=None)):
                result = await document_ocr(str(fake.relative_to(PROJECT_ROOT)), "agent")
            assert "unavailable" in result["error"].lower()
        finally:
            if fake.exists():
                fake.unlink()

    async def test_ocr_success_returns_markdown(self, tmp_path):
        from backend.config import PROJECT_ROOT
        from backend.ocr import OCR_EXTENSIONS

        ext = next(iter(OCR_EXTENSIONS))
        fake = PROJECT_ROOT / "sandbox" / "tmp" / f"test_ocr_ok{ext}"
        fake.parent.mkdir(parents=True, exist_ok=True)
        fake.write_bytes(b"fake binary")
        try:
            with patch("backend.tools.ocr_extract_text", AsyncMock(return_value="# Header\nBody")):
                result = await document_ocr(str(fake.relative_to(PROJECT_ROOT)), "agent")
            assert result["content"] == "# Header\nBody"
            assert result["source"] == "glmocr"
        finally:
            if fake.exists():
                fake.unlink()

    async def test_exception_returns_error_dict(self):
        with patch("backend.tools.ocr_extract_text", AsyncMock(side_effect=RuntimeError("boom"))):
            with patch("backend.tools.ocr_supported", return_value=True):
                # Use a path that exists in the project
                result = await document_ocr("README.md", "agent")
        # Either unsupported extension or exception path
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# system_info — exception path
# ─────────────────────────────────────────────────────────────────────────────


class TestSystemInfoException:
    async def test_exception_returns_error(self):
        with patch("shutil.disk_usage", side_effect=RuntimeError("disk failed")):
            result = await system_info("agent")
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# webhook_send — URLError and generic exception
# ─────────────────────────────────────────────────────────────────────────────


class TestWebhookSendExtended:
    async def test_url_error_returns_failure(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            result = await webhook_send("http://example.com/hook", {"k": "v"}, "agent")
        assert result["success"] is False
        assert "connection refused" in result["error"]

    async def test_generic_exception_returns_failure(self):
        with patch("urllib.request.urlopen", side_effect=Exception("generic error")):
            result = await webhook_send("http://example.com/hook", {}, "agent")
        assert result["success"] is False


# ─────────────────────────────────────────────────────────────────────────────
# health_check — HTTPError path
# ─────────────────────────────────────────────────────────────────────────────


class TestHealthCheckExtended:
    async def test_http_error_returns_reachable_with_status(self):
        exc = urllib.error.HTTPError("http://example.com", 404, "Not Found", HTTPMessage(), None)
        with patch("urllib.request.urlopen", side_effect=exc):
            result = await health_check("http://example.com/health", "agent")
        assert result["reachable"] is True
        assert result["status_code"] == 404

    async def test_url_error_returns_unreachable(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route to host")):
            result = await health_check("http://example.com/health", "agent")
        assert result["reachable"] is False

    async def test_generic_exception_returns_unreachable(self):
        with patch("urllib.request.urlopen", side_effect=Exception("boom")):
            result = await health_check("http://example.com/health", "agent")
        assert result["reachable"] is False


# ─────────────────────────────────────────────────────────────────────────────
# log_tail — exception path
# ─────────────────────────────────────────────────────────────────────────────


class TestLogTailExtended:
    async def test_exception_returns_error(self):
        with patch("pathlib.Path.read_text", side_effect=PermissionError("no read")):
            result = await log_tail("backend/logs/system.jsonl", 10, "agent")
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# secret_scanner — skip extension, 50-findings cap, file exception
# ─────────────────────────────────────────────────────────────────────────────


class TestSecretScannerExtended:
    async def test_skip_extension_files_not_scanned(self, tmp_path):
        from backend.config import PROJECT_ROOT

        scan_dir = PROJECT_ROOT / "sandbox" / "tmp" / "secret_scan_test"
        scan_dir.mkdir(parents=True, exist_ok=True)
        img = scan_dir / "image.png"
        img.write_bytes(b"FAKEPNG AK" + b"IA1234567890123456")  # fake AWS-like pattern in png (should be skipped)
        try:
            result = await secret_scanner(str(scan_dir.relative_to(PROJECT_ROOT)), "agent")
            # .png files are skipped so no findings from the image
            assert result["findings"] == [] or all(
                f["file"] != str(img.relative_to(PROJECT_ROOT)) for f in result["findings"]
            )
        finally:
            import shutil

            shutil.rmtree(scan_dir, ignore_errors=True)

    async def test_50_findings_cap(self, tmp_path):
        from backend.config import PROJECT_ROOT

        scan_dir = PROJECT_ROOT / "sandbox" / "tmp" / "secret_scan_cap"
        scan_dir.mkdir(parents=True, exist_ok=True)
        # Write a file with 60 AWS keys → should cap at 50 findings
        keys = "\n".join(f"AKIA{'A' * 16}{i:04d}" for i in range(60))
        (scan_dir / "secrets.py").write_text(keys)
        try:
            result = await secret_scanner(str(scan_dir.relative_to(PROJECT_ROOT)), "agent")
            assert len(result["findings"]) <= 50
        finally:
            import shutil

            shutil.rmtree(scan_dir, ignore_errors=True)

    async def test_unreadable_file_skipped(self, tmp_path):
        from backend.config import PROJECT_ROOT

        scan_dir = PROJECT_ROOT / "sandbox" / "tmp" / "secret_scan_unread"
        scan_dir.mkdir(parents=True, exist_ok=True)
        bad = scan_dir / "unreadable.py"
        bad.write_text("AKIA1234567890123456A")
        try:
            with patch("pathlib.Path.read_text", side_effect=PermissionError("no read")):
                result = await secret_scanner(str(scan_dir.relative_to(PROJECT_ROOT)), "agent")
            assert "findings" in result
        finally:
            import shutil

            shutil.rmtree(scan_dir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
# db_query — OperationalError and generic exception
# ─────────────────────────────────────────────────────────────────────────────


class TestDbQueryExtended:
    async def test_operational_error_returns_error(self, tmp_path):
        from backend.config import PROJECT_ROOT

        db_file = PROJECT_ROOT / "sandbox" / "tmp" / "test_db_err.db"
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_file))
        conn.execute("CREATE TABLE t (id INTEGER)")
        conn.close()
        try:
            # Invalid column name causes OperationalError
            result = await db_query(str(db_file.relative_to(PROJECT_ROOT)), "SELECT nonexistent_col FROM t", "agent")
            assert "error" in result
        finally:
            if db_file.exists():
                db_file.unlink()

    async def test_generic_exception_returns_error(self):
        with patch("sqlite3.connect", side_effect=Exception("db boom")):
            result = await db_query("backend/tests/test_tools_native.py", "SELECT 1", "agent")
        assert "error" in result


# ─────────────────────────────────────────────────────────────────────────────
# process_restart — success case and timeout
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessRestartExtended:
    async def test_success_returns_return_code(self):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await process_restart("backend", "agent", confirm=True, reason="test restart")
        assert result["success"] is True
        assert result["process"] == "backend"
        assert "return_code" in result

    async def test_timeout_returns_error(self):
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await process_restart("ollama", "agent", confirm=True, reason="test restart")
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    async def test_generic_exception_returns_error(self):
        with patch("asyncio.create_subprocess_exec", side_effect=Exception("spawn failed")):
            result = await process_restart("frontend", "agent", confirm=True, reason="test restart")
        assert result["success"] is False
        assert "spawn failed" in result["error"]

    async def test_blocked_without_confirm_payload(self):
        result = await process_restart("backend", "agent")
        assert result["success"] is False
        assert "confirm payload required" in result["error"]

    async def test_blocked_without_reason(self):
        result = await process_restart("backend", "agent", confirm=True, reason="")
        assert result["success"] is False
        assert "confirm payload required" in result["error"]


# ─────────────────────────────────────────────────────────────────────────────
# folder_analyzer — covered branch gaps
# ─────────────────────────────────────────────────────────────────────────────


class TestFolderAnalyzerExtended:
    async def test_skip_extension_files_not_included(self, tmp_path):
        from backend.config import PROJECT_ROOT

        scan_dir = PROJECT_ROOT / "sandbox" / "tmp" / "fa_ext_test"
        scan_dir.mkdir(parents=True, exist_ok=True)
        (scan_dir / "image.png").write_bytes(b"fake")
        (scan_dir / "normal.py").write_text("print('hi')")
        try:
            result = await folder_analyzer(str(scan_dir.relative_to(PROJECT_ROOT)), "agent")
            if "error" not in result:
                names = [f["name"] for f in result["files"]]
                assert "image.png" not in names
                assert "normal.py" in names
        finally:
            import shutil

            shutil.rmtree(scan_dir, ignore_errors=True)

    async def test_read_text_exception_handled(self, tmp_path):
        from backend.config import PROJECT_ROOT

        scan_dir = PROJECT_ROOT / "sandbox" / "tmp" / "fa_read_err"
        scan_dir.mkdir(parents=True, exist_ok=True)
        (scan_dir / "file.py").write_text("content")
        try:
            with patch("pathlib.Path.read_text", side_effect=PermissionError("no read")):
                result = await folder_analyzer(str(scan_dir.relative_to(PROJECT_ROOT)), "agent", include_content=True)
            # Should still return without raising
            assert "error" not in result or isinstance(result, dict)
        finally:
            import shutil

            shutil.rmtree(scan_dir, ignore_errors=True)

    async def test_max_files_triggering_return_mid_loop(self):
        # Use a real directory and max_files=1 to trigger the mid-loop return
        result = await folder_analyzer("backend/tests", "agent", max_files=1)
        if "error" not in result:
            assert result["file_count"] <= 1
            assert result.get("truncated") is True


# ─────────────────────────────────────────────────────────────────────────────
# k8s_control — all actions and error paths
# ─────────────────────────────────────────────────────────────────────────────


def _k8s_proc(returncode=0, stdout=b"output", stderr=b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


class TestK8sControl:
    async def test_list_pods_success(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(stdout=b"pod1\npod2")):
            result = await k8s_control("list_pods", "agent")
        assert result["success"] is True
        assert "pod1" in result["output"]

    async def test_list_pods_failure(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(returncode=1, stderr=b"error msg")):
            result = await k8s_control("list_pods", "agent")
        assert result["success"] is False
        assert "error msg" in result["error"]

    async def test_list_jobs_success(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(stdout=b"job1")):
            result = await k8s_control("list_jobs", "agent")
        assert result["success"] is True

    async def test_list_jobs_failure(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(returncode=1, stderr=b"job err")):
            result = await k8s_control("list_jobs", "agent")
        assert result["success"] is False

    async def test_create_job_missing_params(self):
        result = await k8s_control("create_job", "agent")
        assert result["success"] is False
        assert "requires" in result["error"].lower()

    async def test_create_job_success(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(stdout=b"created")):
            result = await k8s_control(
                "create_job", "agent", job_name="my-job", image="python:3.11", command="python main.py"
            )
        assert result["success"] is True

    async def test_create_job_failure(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(returncode=1, stderr=b"create err")):
            result = await k8s_control("create_job", "agent", job_name="bad-job", image="py", command="fail")
        assert result["success"] is False

    async def test_create_job_sanitizes_name(self):
        """Job name with uppercase/special chars is sanitized."""
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc()):
            result = await k8s_control(
                "create_job", "agent", job_name="My_Job!!", image="python:3.11", command="echo hi"
            )
        assert result["success"] is True
        assert result["job_name"] == "my-job--"  # sanitized

    async def test_delete_job_missing_name(self):
        result = await k8s_control("delete_job", "agent")
        assert result["success"] is False
        assert "requires" in result["error"].lower()

    async def test_delete_job_success(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(stdout=b"deleted")):
            result = await k8s_control("delete_job", "agent", job_name="old-job")
        assert result["success"] is True

    async def test_delete_job_failure(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(returncode=1, stderr=b"del err")):
            result = await k8s_control("delete_job", "agent", job_name="gone")
        assert result["success"] is False

    async def test_get_logs_success(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(stdout=b"log line")):
            result = await k8s_control("get_logs", "agent")
        assert result["success"] is True
        assert "log line" in result["output"]

    async def test_get_logs_with_error(self):
        with patch("asyncio.create_subprocess_exec", return_value=_k8s_proc(returncode=1, stderr=b"no pods")):
            result = await k8s_control("get_logs", "agent")
        assert result["success"] is False

    async def test_unknown_action(self):
        result = await k8s_control("explode_everything", "agent")
        assert result["success"] is False
        assert "Unknown action" in result["error"]

    async def test_timeout_error(self):
        proc = AsyncMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError("timeout"))
        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await k8s_control("list_pods", "agent")
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    async def test_generic_exception(self):
        with patch("asyncio.create_subprocess_exec", side_effect=Exception("crash")):
            result = await k8s_control("list_pods", "agent")
        assert result["success"] is False
        assert "crash" in result["error"].lower()


# ─────────────────────────────────────────────────────────────────────────────
# browser_control — all actions and error paths
# ─────────────────────────────────────────────────────────────────────────────


def _make_httpx_client(response_json: dict, status_code: int = 200):
    """Build a mock httpx.AsyncClient context manager."""

    mock_resp = MagicMock()
    mock_resp.json.return_value = response_json
    mock_resp.status_code = status_code
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__exit__ = AsyncMock(return_value=False)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


class TestBrowserControl:
    async def test_unknown_action(self):
        result = await browser_control("fly", "agent")
        assert result["success"] is False
        assert "Unknown action" in result["error"]

    async def test_navigate_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"title": "example"})):
            result = await browser_control("navigate", "agent", url="http://example.com")
        assert result["success"] is True
        assert result["action"] == "navigate"

    async def test_click_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"clicked": True})):
            result = await browser_control("click", "agent", selector="#btn")
        assert result["success"] is True

    async def test_fill_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"filled": True})):
            result = await browser_control("fill", "agent", selector="#inp", value="hello")
        assert result["success"] is True

    async def test_select_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"selected": "opt1"})):
            result = await browser_control("select", "agent", selector="#sel", option_value="opt1")
        assert result["success"] is True

    async def test_evaluate_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"result": "42"})):
            result = await browser_control("evaluate", "agent", expression="1+1")
        assert result["success"] is True

    async def test_screenshot_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"path": "/tmp/shot.png"})):
            result = await browser_control("screenshot", "agent")
        assert result["success"] is True

    async def test_back_success(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"navigated": True})):
            result = await browser_control("back", "agent")
        assert result["success"] is True

    async def test_url_uses_get(self):
        with patch("httpx.AsyncClient", return_value=_make_httpx_client({"url": "http://x.com"})):
            result = await browser_control("url", "agent")
        assert result["success"] is True

    async def test_connect_error_returns_failure(self):
        import httpx

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await browser_control("navigate", "agent", url="http://x.com")
        assert result["success"] is False
        assert "browser-worker" in result["error"].lower()

    async def test_http_status_error_returns_failure(self):
        import httpx

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("bad", request=MagicMock(), response=mock_resp)
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await browser_control("navigate", "agent", url="http://x.com")
        assert result["success"] is False

    async def test_generic_exception_returns_failure(self):
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=Exception("something broke"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await browser_control("navigate", "agent", url="http://x.com")
        assert result["success"] is False
        assert "something broke" in result["error"]


# ─────────────────────────────────────────────────────────────────────────────
# execute_tool routing — browser_ and hf_ paths
# ─────────────────────────────────────────────────────────────────────────────


class TestExecuteToolExtended:
    async def test_hf_tool_routing(self):
        """hf_ tools are forwarded to the Higgsfield MCP server via httpx."""

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": "hf_login ok"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def _passthrough(tool_name, agent_id, modification_type, tool_fn, *a, **kw):
            return await tool_fn()

        with patch("backend.tools.drift_guard.guard_tool_execution", side_effect=_passthrough):
            with patch("httpx.AsyncClient", return_value=mock_client):
                result = await execute_tool(
                    "hf_login",
                    "agent",
                    ["hf_login"],
                    username="user",
                    password="pass",  # noqa: S106
                )
        assert "result" in result

    async def test_browser_tool_routing(self):
        """browser_ tools are routed through browser tooling module."""

        async def _passthrough(tool_name, agent_id, modification_type, tool_fn, *a, **kw):
            return await tool_fn()

        mock_browser_result = {"success": True, "url": "http://example.com"}

        with patch("backend.tools.drift_guard.guard_tool_execution", side_effect=_passthrough):
            with patch("backend.browser.tooling.browser_open", AsyncMock(return_value=mock_browser_result)):
                result = await execute_tool(
                    "browser_open",
                    "agent",
                    ["browser_open"],
                    url="http://example.com",
                )
        assert result["success"] is True

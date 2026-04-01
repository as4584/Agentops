"""Tests for the OCR agent definition, routing, and OCR module.

Validates:
  - ocr_agent is registered in ALL_AGENT_DEFINITIONS
  - ocr_agent definition fields are correct
  - keyword routing sends OCR-related messages to ocr_agent
  - ocr_agent is in VALID_AGENTS for Lex routing
  - backend.ocr module functions work (mocked HTTP)
  - document_ocr tool dispatches correctly
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.agents import ALL_AGENT_DEFINITIONS, BaseAgent, create_agent
from backend.models import ChangeImpactLevel
from backend.ocr import OCR_EXTENSIONS, extract_text, is_supported
from backend.orchestrator.lex_router import VALID_AGENTS, _keyword_route

# ── Agent Definition ────────────────────────────────────────────────


class TestOCRAgentDefinition:
    def test_ocr_agent_registered(self):
        assert "ocr_agent" in ALL_AGENT_DEFINITIONS

    def test_agent_id_matches_key(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert defn.agent_id == "ocr_agent"

    def test_role_is_set(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert "document extraction" in defn.role.lower()

    def test_system_prompt_mentions_glm_ocr(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert "GLM-OCR" in defn.system_prompt

    def test_document_ocr_in_tool_permissions(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert "document_ocr" in defn.tool_permissions

    def test_file_reader_in_tool_permissions(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert "file_reader" in defn.tool_permissions

    def test_memory_namespace_unique(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert defn.memory_namespace == "ocr_agent"
        other_namespaces = [d.memory_namespace for k, d in ALL_AGENT_DEFINITIONS.items() if k != "ocr_agent"]
        assert defn.memory_namespace not in other_namespaces

    def test_change_impact_is_low(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert defn.change_impact_level == ChangeImpactLevel.LOW

    def test_skills_assigned(self):
        defn = ALL_AGENT_DEFINITIONS["ocr_agent"]
        assert "token_optimization" in defn.skills

    def test_create_agent_factory(self):
        """create_agent('ocr_agent', ...) returns a BaseAgent."""
        mock_llm = AsyncMock()
        agent = create_agent("ocr_agent", mock_llm)
        assert isinstance(agent, BaseAgent)
        assert agent.agent_id == "ocr_agent"


# ── Routing ──────────────────────────────────────────────────────────


class TestOCRRouting:
    def test_ocr_in_valid_agents(self):
        assert "ocr_agent" in VALID_AGENTS

    def test_keyword_ocr(self):
        assert _keyword_route("run ocr on this file") == "ocr_agent"

    def test_keyword_pdf(self):
        assert _keyword_route("read the pdf report") == "ocr_agent"

    def test_keyword_scan_document(self):
        assert _keyword_route("scan document and extract text from it") == "ocr_agent"

    def test_keyword_extract_text(self):
        assert _keyword_route("extract text from the image") == "ocr_agent"

    def test_keyword_parse_document(self):
        assert _keyword_route("parse document and summarize") == "ocr_agent"

    def test_keyword_image_to_text(self):
        assert _keyword_route("convert this image to text") == "ocr_agent"


# ── OCR Module ───────────────────────────────────────────────────────


class TestOCRModule:
    def test_supported_extensions(self):
        assert ".pdf" in OCR_EXTENSIONS
        assert ".png" in OCR_EXTENSIONS
        assert ".jpg" in OCR_EXTENSIONS
        assert ".docx" in OCR_EXTENSIONS

    def test_is_supported_pdf(self):
        assert is_supported("/tmp/report.pdf") is True

    def test_is_supported_png(self):
        assert is_supported("/tmp/screenshot.PNG") is True

    def test_is_supported_txt_not_supported(self):
        assert is_supported("/tmp/notes.txt") is False

    def test_is_supported_py_not_supported(self):
        assert is_supported("/tmp/app.py") is False

    @pytest.mark.asyncio
    async def test_extract_text_disabled(self):
        """When GLMOCR_ENABLED is False, extract_text returns None."""
        with patch("backend.ocr.GLMOCR_ENABLED", False):
            result = await extract_text("/tmp/report.pdf")
            assert result is None

    @pytest.mark.asyncio
    async def test_extract_text_unsupported_extension(self):
        """Unsupported file extensions return None."""
        result = await extract_text("/tmp/notes.txt")
        assert result is None

    @pytest.mark.asyncio
    async def test_extract_text_file_not_found(self):
        """Non-existent file returns None."""
        with patch("backend.ocr.GLMOCR_ENABLED", True):
            result = await extract_text("/tmp/nonexistent_file_abc123.pdf")
            assert result is None

    @pytest.mark.asyncio
    async def test_extract_text_success(self, tmp_path: Path):
        """Successful extraction returns Markdown string."""
        from unittest.mock import MagicMock

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"markdown": "# Report\n\nExtracted content here."}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("backend.ocr.GLMOCR_ENABLED", True),
            patch("backend.ocr.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await extract_text(str(pdf_file))
            assert result is not None
            assert "# Report" in result
            assert "Extracted content" in result

    @pytest.mark.asyncio
    async def test_extract_text_service_unreachable(self, tmp_path: Path):
        """When GLM-OCR service is down, returns None (graceful degradation)."""
        import httpx

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        with (
            patch("backend.ocr.GLMOCR_ENABLED", True),
            patch("backend.ocr.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await extract_text(str(pdf_file))
            assert result is None

    @pytest.mark.asyncio
    async def test_extract_text_empty_response(self, tmp_path: Path):
        """Empty markdown in response returns None."""
        from unittest.mock import MagicMock

        pdf_file = tmp_path / "test.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake content")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"result": {"markdown": ""}}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with (
            patch("backend.ocr.GLMOCR_ENABLED", True),
            patch("backend.ocr.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await extract_text(str(pdf_file))
            assert result is None

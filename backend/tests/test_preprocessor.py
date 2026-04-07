"""Tests for the deterministic preprocessor."""

from __future__ import annotations

from backend.ml.preprocessor import preprocess


class TestFillerRemoval:
    def test_strips_um(self):
        r = preprocess("um can you help me with the deployment")
        assert "um" not in r.cleaned.lower().split()

    def test_strips_basically(self):
        r = preprocess("basically I need to deploy the code")
        assert "basically" not in r.cleaned.lower()

    def test_strips_honestly(self):
        r = preprocess("honestly the logs look weird")
        assert "honestly" not in r.cleaned.lower()

    def test_preserves_content_words(self):
        r = preprocess("um basically I need to deploy the code to production")
        assert "deploy" in r.cleaned.lower()
        assert "production" in r.cleaned.lower()

    def test_raw_preserved(self):
        msg = "um basically just deploy it"
        r = preprocess(msg)
        assert r.raw == msg


class TestDomainDetection:
    def test_coding_domain(self):
        r = preprocess("I have a bug in my python function that throws a type error")
        assert "coding" in r.domains

    def test_orchestration_domain(self):
        r = preprocess("route this message to the correct agent via the orchestrator pipeline")
        assert "orchestration" in r.domains

    def test_security_domain(self):
        r = preprocess("scan for secrets and check for CVE vulnerabilities in the codebase")
        assert "security" in r.domains

    def test_education_domain(self):
        r = preprocess("explain the curriculum for studio 4 and bloom taxonomy levels")
        assert "education" in r.domains

    def test_video_domain(self):
        r = preprocess("create a higgsfield video with mochi model for the character animation")
        assert "video" in r.domains

    def test_general_domain_fallback(self):
        r = preprocess("hello world")
        assert r.primary_domain == "general"

    def test_multi_domain(self):
        r = preprocess("refactor the python code and scan for security vulnerabilities")
        assert len(r.domains) >= 2


class TestConstraintExtraction:
    def test_file_references(self):
        r = preprocess("check backend/config.py for errors")
        assert "files" in r.constraints
        assert "backend/config.py" in r.constraints["files"]

    def test_tool_names(self):
        r = preprocess("use safe_shell to run the command")
        assert "tools" in r.constraints
        assert "safe_shell" in r.constraints["tools"]

    def test_agent_names(self):
        r = preprocess("route this to devops_agent for deployment")
        assert "agents" in r.constraints
        assert "devops_agent" in r.constraints["agents"]

    def test_numbers(self):
        r = preprocess("the CPU is at 95% and we have 512MB free")
        assert "numbers" in r.constraints

    def test_deadline_detection(self):
        r = preprocess("this needs to be done by Friday, its urgent")
        assert r.constraints.get("has_deadline") is True


class TestAmbiguity:
    def test_vague_message(self):
        r = preprocess("help")
        assert r.ambiguity == "vague"

    def test_clear_with_tool(self):
        r = preprocess("use safe_shell to restart the backend process on port 8000")
        assert r.ambiguity == "clear"

    def test_clear_with_agent(self):
        r = preprocess("route this to devops_agent for the CI/CD pipeline deployment")
        assert r.ambiguity == "clear"

    def test_needs_clarification(self):
        r = preprocess("fix something in the code")
        assert r.ambiguity in ("needs_clarification", "clear")


class TestTokenCounting:
    def test_token_count_positive(self):
        r = preprocess("deploy the application to production")
        assert r.token_count > 0

    def test_word_count(self):
        r = preprocess("deploy the application to production")
        assert r.word_count == 5


class TestPreprocessResult:
    def test_to_dict(self):
        r = preprocess("deploy the code to production using safe_shell")
        d = r.to_dict()
        assert "raw" in d
        assert "cleaned" in d
        assert "domains" in d
        assert "constraints" in d
        assert "token_count" in d
        assert isinstance(d, dict)

    def test_mentioned_tools(self):
        r = preprocess("use file_reader and db_query")
        assert "file_reader" in r.mentioned_tools
        assert "db_query" in r.mentioned_tools

    def test_mentioned_files(self):
        r = preprocess("edit backend/agents/__init__.py")
        assert "backend/agents/__init__.py" in r.mentioned_files

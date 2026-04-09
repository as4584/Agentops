"""
Tests for backend/ml/training_generator.py and backend/ml/learning_lab.py
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── AGENT_DOMAINS / WEAK_BOUNDARIES / RED_LINE_PATTERNS constants ─────────────


class TestModuleConstants:
    def test_agent_domains_has_all_valid_agents(self):
        from backend.ml.training_generator import AGENT_DOMAINS

        expected = {
            "soul_core",
            "devops_agent",
            "monitor_agent",
            "self_healer_agent",
            "code_review_agent",
            "security_agent",
            "data_agent",
            "comms_agent",
            "cs_agent",
            "it_agent",
            "knowledge_agent",
            "ocr_agent",
        }
        assert set(AGENT_DOMAINS.keys()) == expected

    def test_agent_domains_each_has_keywords(self):
        from backend.ml.training_generator import AGENT_DOMAINS

        for agent_id, domain in AGENT_DOMAINS.items():
            assert "keywords" in domain, f"{agent_id} missing keywords"
            assert len(domain["keywords"]) > 0

    def test_agent_domains_each_has_role(self):
        from backend.ml.training_generator import AGENT_DOMAINS

        for agent_id, domain in AGENT_DOMAINS.items():
            assert "role" in domain, f"{agent_id} missing role"
            assert isinstance(domain["role"], str)

    def test_agent_domains_each_has_tools(self):
        from backend.ml.training_generator import AGENT_DOMAINS

        for agent_id, domain in AGENT_DOMAINS.items():
            assert "tools" in domain, f"{agent_id} missing tools"
            assert isinstance(domain["tools"], list)

    def test_weak_boundaries_are_tuples(self):
        from backend.ml.training_generator import WEAK_BOUNDARIES

        for pair in WEAK_BOUNDARIES:
            assert len(pair) == 2

    def test_weak_boundaries_reference_valid_agents(self):
        from backend.ml.training_generator import AGENT_DOMAINS, WEAK_BOUNDARIES

        valid = set(AGENT_DOMAINS.keys())
        for a, b in WEAK_BOUNDARIES:
            assert a in valid, f"Unknown agent {a} in WEAK_BOUNDARIES"
            assert b in valid, f"Unknown agent {b} in WEAK_BOUNDARIES"

    def test_red_line_patterns_non_empty(self):
        from backend.ml.training_generator import RED_LINE_PATTERNS

        assert len(RED_LINE_PATTERNS) > 0

    def test_red_line_patterns_are_strings(self):
        from backend.ml.training_generator import RED_LINE_PATTERNS

        for p in RED_LINE_PATTERNS:
            assert isinstance(p, str) and p.strip()


# ── TrainingGenerator._extract_json ──────────────────────────────────────────


class TestExtractJson:
    def _extract(self, text):
        from backend.ml.training_generator import TrainingGenerator

        return TrainingGenerator._extract_json(text)

    def test_direct_json(self):
        result = self._extract('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_in_markdown_fence(self):
        text = '```json\n{"task": "foo"}\n```'
        result = self._extract(text)
        assert result == {"task": "foo"}

    def test_json_embedded_in_text(self):
        text = 'Here is JSON: {"answer": 42} done.'
        result = self._extract(text)
        assert result == {"answer": 42}

    def test_invalid_returns_none(self):
        assert self._extract("not json at all") is None

    def test_empty_returns_none(self):
        assert self._extract("") is None

    def test_nested_json(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = self._extract(text)
        assert result is not None
        assert result["outer"]["inner"] == [1, 2, 3]

    def test_with_whitespace_prefix(self):
        result = self._extract('   \n  {"x": 1}')
        assert result == {"x": 1}


# ── TrainingGenerator._append ─────────────────────────────────────────────────


class TestAppend:
    def test_appends_json_line(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        path = tmp_path / "out.jsonl"
        TrainingGenerator._append(path, {"key": "val"})
        lines = path.read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"key": "val"}

    def test_multiple_appends(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        path = tmp_path / "out.jsonl"
        TrainingGenerator._append(path, {"a": 1})
        TrainingGenerator._append(path, {"b": 2})
        lines = path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[1]) == {"b": 2}

    def test_creates_file_if_missing(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        path = tmp_path / "new_file.jsonl"
        assert not path.exists()
        TrainingGenerator._append(path, {"z": 99})
        assert path.exists()


# ── TrainingGenerator._generate_redline_routing ──────────────────────────────


class TestGenerateRedlineRouting:
    def _make_gen(self):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        return TrainingGenerator(llm)

    def test_returns_blocked_agent(self):
        gen = self._make_gen()
        result = gen._generate_redline_routing()
        assert result["expected_agent"] == "BLOCKED"

    def test_returns_empty_tools(self):
        gen = self._make_gen()
        result = gen._generate_redline_routing()
        assert result["expected_tools"] == []

    def test_confidence_is_1(self):
        gen = self._make_gen()
        result = gen._generate_redline_routing()
        assert result["confidence"] == 1.0

    def test_difficulty_is_red_line(self):
        gen = self._make_gen()
        result = gen._generate_redline_routing()
        assert result["difficulty"] == "red_line"

    def test_user_message_is_string(self):
        gen = self._make_gen()
        result = gen._generate_redline_routing()
        assert isinstance(result["user_message"], str)
        assert len(result["user_message"]) > 0


# ── TrainingGenerator async methods with mocked LLM ──────────────────────────


class TestGenerateEasyRouting:
    @pytest.mark.asyncio
    async def test_valid_message_returns_example(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="Check the deployment pipeline for any failed builds.")
        gen = TrainingGenerator(llm)
        gen._ts = "20240101_000000"
        with patch("backend.ml.training_generator.TRAINING_DIR", tmp_path):
            tmp_path.mkdir(exist_ok=True)
            result = await gen._generate_easy_routing()
        assert result is not None
        assert "user_message" in result
        assert result["difficulty"] == "easy"
        from backend.ml.training_generator import AGENT_DOMAINS
        assert result["expected_agent"] in AGENT_DOMAINS

    @pytest.mark.asyncio
    async def test_too_short_message_returns_none(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="hi")
        gen = TrainingGenerator(llm)
        result = await gen._generate_easy_routing()
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
        gen = TrainingGenerator(llm)
        result = await gen._generate_easy_routing()
        assert result is None


class TestGenerateHardRouting:
    @pytest.mark.asyncio
    async def test_returns_hard_example(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        message = "I see the logs show high CPU, could be a system issue or something needs restarting."
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=message)
        gen = TrainingGenerator(llm)
        result = await gen._generate_hard_routing()
        assert result is not None
        assert result["difficulty"] == "hard"
        assert "boundary" in result

    @pytest.mark.asyncio
    async def test_llm_exception_returns_none(self):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=Exception("fail"))
        gen = TrainingGenerator(llm)
        result = await gen._generate_hard_routing()
        assert result is None


class TestGenerateRoutingBatch:
    @pytest.mark.asyncio
    async def test_full_batch(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        good_msg = "Deploy the new Docker image to staging environment and verify health checks pass."
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=good_msg)
        gen = TrainingGenerator(llm)
        gen._ts = "20240101_120000"
        with patch("backend.ml.training_generator.TRAINING_DIR", tmp_path):
            result = await gen.generate_routing_batch(count=5)
        assert result["total"] >= 1  # at least redline examples
        assert "output_file" in result
        assert "easy" in result
        assert "hard" in result
        assert "redline" in result

    @pytest.mark.asyncio
    async def test_redline_always_in_output(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="x")  # too short, easy/hard return None
        gen = TrainingGenerator(llm)
        gen._ts = "test"
        with patch("backend.ml.training_generator.TRAINING_DIR", tmp_path):
            result = await gen.generate_routing_batch(count=5)
        # Even when easy/hard fail, redline examples are always generated
        assert result["total"] > 0


class TestGenerateTrajectoryBatch:
    @pytest.mark.asyncio
    async def test_batch_with_valid_llm_response(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        traj_json = json.dumps(
            {
                "task": "Deploy new image",
                "task_type": "deployment",
                "goal": "Successful deploy",
                "plan": ["build", "push", "deploy"],
                "actions": ["git_ops: git pull", "safe_shell: docker build"],
                "result": "Deployed successfully",
            }
        )
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=traj_json)
        gen = TrainingGenerator(llm)
        gen._ts = "test"
        with patch("backend.ml.training_generator.TRAINING_DIR", tmp_path):
            result = await gen.generate_trajectory_batch(count=3)
        assert result["total"] == 3
        assert "output_file" in result

    @pytest.mark.asyncio
    async def test_trajectory_llm_failure_skips(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("fail"))
        gen = TrainingGenerator(llm)
        gen._ts = "test"
        with patch("backend.ml.training_generator.TRAINING_DIR", tmp_path):
            result = await gen.generate_trajectory_batch(count=2)
        assert result["total"] == 0


class TestGeneratePreferenceBatch:
    @pytest.mark.asyncio
    async def test_batch_with_valid_llm_response(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        pair_json = json.dumps(
            {
                "user_message": "Is the system memory usage normal?",
                "good_response": "Route to monitor_agent: health metrics task.",
                "bad_response": "Route to it_agent: looks like an infra question.",
                "good_plan": ["check health", "tail logs"],
                "bad_plan": ["check system info"],
                "why_good_is_better": ["monitor owns metrics"],
            }
        )
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=pair_json)
        gen = TrainingGenerator(llm)
        gen._ts = "test"
        with patch("backend.ml.training_generator.DPO_DIR", tmp_path):
            result = await gen.generate_preference_batch(count=2)
        assert result["total"] == 2
        # categories populated
        assert len(result["categories"]) > 0

    @pytest.mark.asyncio
    async def test_llm_failure_skips_pair(self, tmp_path):
        from backend.ml.training_generator import TrainingGenerator

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("offline"))
        gen = TrainingGenerator(llm)
        gen._ts = "test"
        with patch("backend.ml.training_generator.DPO_DIR", tmp_path):
            result = await gen.generate_preference_batch(count=2)
        assert result["total"] == 0


# Helper injected into TrainingGenerator for agent ID access
def _get_all_agent_ids(self):
    from backend.ml.training_generator import AGENT_DOMAINS

    return list(AGENT_DOMAINS.keys())


from backend.ml.training_generator import TrainingGenerator  # noqa: E402

TrainingGenerator._get_all_agent_ids = _get_all_agent_ids  # type: ignore[attr-defined]


# ── LearningLab.training_data_summary ────────────────────────────────────────


class TestTrainingDataSummary:
    def _make_lab(self, training_dir, dpo_dir):
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = training_dir
        lab._dpo_dir = dpo_dir
        return lab

    def test_empty_dirs_zero_stats(self, tmp_path):
        training = tmp_path / "training"
        dpo = tmp_path / "dpo"
        training.mkdir()
        dpo.mkdir()
        lab = self._make_lab(training, dpo)
        stats = lab.training_data_summary()
        assert stats.routing_files == 0
        assert stats.trajectory_files == 0
        assert stats.dpo_files == 0
        assert stats.total_routing_pairs == 0

    def test_counts_routing_files(self, tmp_path):
        training = tmp_path / "training"
        dpo = tmp_path / "dpo"
        training.mkdir()
        dpo.mkdir()
        # Write routing JSONL
        (training / "lex_pairs_20240101.jsonl").write_text(
            '{"user_message": "m1", "expected_agent": "monitor_agent"}\n'
            '{"user_message": "m2", "expected_agent": "devops_agent"}\n'
        )
        lab = self._make_lab(training, dpo)
        stats = lab.training_data_summary()
        assert stats.routing_files == 1
        assert stats.total_routing_pairs == 2

    def test_counts_trajectory_files(self, tmp_path):
        training = tmp_path / "training"
        dpo = tmp_path / "dpo"
        training.mkdir()
        dpo.mkdir()
        (training / "gen_trajectory_20240101.jsonl").write_text(
            '{"task": "deploy"}\n{"task": "restart"}\n{"task": "check"}\n'
        )
        lab = self._make_lab(training, dpo)
        stats = lab.training_data_summary()
        assert stats.trajectory_files == 1
        assert stats.total_trajectory_pairs == 3

    def test_counts_dpo_files(self, tmp_path):
        training = tmp_path / "training"
        dpo = tmp_path / "dpo"
        training.mkdir()
        dpo.mkdir()
        (dpo / "gen_dpo_20240101.jsonl").write_text('{"pair": 1}\n{"pair": 2}\n')
        lab = self._make_lab(training, dpo)
        stats = lab.training_data_summary()
        assert stats.dpo_files == 1
        assert stats.total_dpo_pairs == 2

    def test_missing_dirs_returns_zeros(self, tmp_path):
        lab = self._make_lab(tmp_path / "no_training", tmp_path / "no_dpo")
        stats = lab.training_data_summary()
        assert stats.routing_files == 0
        assert stats.dpo_files == 0


# ── LearningLab.health_report ─────────────────────────────────────────────────


class TestHealthReport:
    def _make_lab(self, training_dir, dpo_dir):
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = training_dir
        lab._dpo_dir = dpo_dir
        return lab

    def test_report_has_timestamp(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        dpo = tmp_path / "dpo"
        dpo.mkdir()
        lab = self._make_lab(training, dpo)
        report = lab.health_report()
        assert report.timestamp != ""

    def test_low_routing_pairs_adds_recommendation(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        dpo = tmp_path / "dpo"
        dpo.mkdir()
        lab = self._make_lab(training, dpo)
        report = lab.health_report()
        assert any("Routing pairs" in r for r in report.recommendations)

    def test_low_dpo_pairs_adds_recommendation(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        dpo = tmp_path / "dpo"
        dpo.mkdir()
        lab = self._make_lab(training, dpo)
        report = lab.health_report()
        assert any("DPO pairs" in r for r in report.recommendations)

    def test_no_trajectory_adds_recommendation(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        dpo = tmp_path / "dpo"
        dpo.mkdir()
        lab = self._make_lab(training, dpo)
        report = lab.health_report()
        assert any("trajectory" in r for r in report.recommendations)

    def test_no_ollama_models_adds_recommendation(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        dpo = tmp_path / "dpo"
        dpo.mkdir()
        lab = self._make_lab(training, dpo)
        report = lab.health_report()
        assert any("Ollama" in r for r in report.recommendations)

    def test_sufficient_data_no_routing_recommendation(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        dpo = tmp_path / "dpo"
        dpo.mkdir()
        # Write 500+ routing pairs
        lines = "\n".join(['{"user_message": "m", "expected_agent": "devops_agent"}'] * 510)
        (training / "lex_pairs_big.jsonl").write_text(lines + "\n")
        lab = self._make_lab(training, dpo)
        report = lab.health_report()
        assert not any("Routing pairs" in r for r in report.recommendations)


# ── LearningLab.list_golden_tasks / add_golden_task ──────────────────────────


class TestGoldenTasks:
    def _make_lab(self, tmp_path):
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path / "training"
        lab._dpo_dir = tmp_path / "dpo"
        lab._training_dir.mkdir(parents=True, exist_ok=True)
        return lab

    def test_list_golden_tasks_missing_file(self, tmp_path):
        from backend.ml.learning_lab import LearningLab

        with patch("backend.ml.learning_lab.PROJECT_ROOT", tmp_path):
            lab = LearningLab()
            tasks = lab.list_golden_tasks()
        assert tasks == []

    def test_add_and_list_golden_task(self, tmp_path):
        from backend.ml.learning_lab import LearningLab

        with patch("backend.ml.learning_lab.PROJECT_ROOT", tmp_path):
            lab = LearningLab()
            _task = lab.add_golden_task(
                task_id="t001",
                user_message="Check if deployment is healthy",
                expected_agent="monitor_agent",
                expected_tools=["health_check"],
                difficulty="easy",
            )
            tasks = lab.list_golden_tasks()
        assert len(tasks) == 1
        assert tasks[0]["task_id"] == "t001"
        assert tasks[0]["expected_agent"] == "monitor_agent"

    def test_add_multiple_golden_tasks(self, tmp_path):
        from backend.ml.learning_lab import LearningLab

        with patch("backend.ml.learning_lab.PROJECT_ROOT", tmp_path):
            lab = LearningLab()
            lab.add_golden_task("t1", "msg1", "devops_agent")
            lab.add_golden_task("t2", "msg2", "monitor_agent")
            tasks = lab.list_golden_tasks()
        assert len(tasks) == 2
        ids = {t["task_id"] for t in tasks}
        assert ids == {"t1", "t2"}

    def test_add_golden_task_defaults(self, tmp_path):
        from backend.ml.learning_lab import LearningLab

        with patch("backend.ml.learning_lab.PROJECT_ROOT", tmp_path):
            lab = LearningLab()
            task = lab.add_golden_task("t1", "some message", "security_agent")
        assert task["expected_tools"] == []
        assert task["difficulty"] == "medium"
        assert task["boundary"] == ""
        assert "added" in task


# ── LearningLab.boundary_coverage ────────────────────────────────────────────


class TestBoundaryCoverage:
    def _make_lab(self, training_dir):
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = training_dir
        lab._dpo_dir = training_dir  # unused
        return lab

    def test_missing_dir_returns_empty(self, tmp_path):
        lab = self._make_lab(tmp_path / "nonexistent")
        coverage = lab.boundary_coverage()
        assert coverage == {}

    def test_counts_boundaries(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        data = "\n".join(
            [
                json.dumps({"boundary": "devops_agent_self_healer_agent"}),
                json.dumps({"boundary": "devops_agent_self_healer_agent"}),
                json.dumps({"boundary": "monitor_agent_it_agent"}),
                json.dumps({"user_message": "no boundary here"}),  # no boundary field
            ]
        )
        (training / "routing.jsonl").write_text(data + "\n")
        lab = self._make_lab(training)
        coverage = lab.boundary_coverage()
        # boundary keys should be counted
        total = sum(coverage.values())
        assert total == 3  # 2 + 1 boundary entries

    def test_skips_bad_json_lines(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        (training / "mixed.jsonl").write_text('bad json line\n{"boundary": "pair_a"}\n')
        lab = self._make_lab(training)
        coverage = lab.boundary_coverage()  # should not raise
        assert isinstance(coverage, dict)

    def test_sorted_descending(self, tmp_path):
        training = tmp_path / "training"
        training.mkdir()
        lines = (json.dumps({"boundary": "a_b"}) + "\n") * 3 + (json.dumps({"boundary": "c_d"}) + "\n")
        (training / "data.jsonl").write_text(lines)
        lab = self._make_lab(training)
        coverage = lab.boundary_coverage()
        values = list(coverage.values())
        assert values == sorted(values, reverse=True)

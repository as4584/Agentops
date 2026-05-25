from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.ml.learning_lab import DatasetStats, LabHealthReport
from backend.ml.training_job_manager import LexTrainingJobManager, SAFE_BASE_MODELS


def _app(*routers):
    app = FastAPI()
    for router in routers:
        app.include_router(router)
    return app


class FakePopen:
    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.pid = 43210

    def poll(self):
        return None


def _write_jsonl(path: Path, lines: int) -> None:
    path.write_text("".join('{"id": 1}\n' for _ in range(lines)), encoding="utf-8")


class TestLexTrainingJobManager:
    def test_start_job_stages_selected_datasets(self, tmp_path: Path):
        training_dir = tmp_path / "training"
        dpo_dir = tmp_path / "dpo"
        artifact_root = tmp_path / "artifacts-root"
        jobs_root = tmp_path / "jobs"
        training_dir.mkdir()
        dpo_dir.mkdir()
        artifact_root.mkdir()

        _write_jsonl(training_dir / "combined.jsonl", 3)
        _write_jsonl(training_dir / "filtered_combined.jsonl", 2)
        _write_jsonl(dpo_dir / "prefs.jsonl", 4)
        script_path = tmp_path / "finetune_lex.py"
        script_path.write_text("print('ok')\n", encoding="utf-8")

        manager = LexTrainingJobManager(
            jobs_root=jobs_root,
            training_dir=training_dir,
            dpo_dir=dpo_dir,
            artifact_root=artifact_root,
            finetune_script=script_path,
            python_executable="/usr/bin/python3",
        )

        with patch("backend.ml.training_job_manager.subprocess.Popen", FakePopen):
            job = manager.start_job(
                mode="sft",
                base_model=SAFE_BASE_MODELS[0],
                epochs=3,
                learning_rate=2e-4,
                batch_size=1,
                grad_accum=8,
                max_seq_len=4096,
                lora_rank=64,
                lora_alpha=16,
                training_files=["combined.jsonl"],
                dpo_files=[],
                source_artifact=None,
                ollama_model="lex",
                max_per_cat=20,
                deploy_to_ollama=False,
            )

        assert job["status"] == "running"
        assert "--skip-ollama" in job["command"]
        staged_training = Path(job["log_path"]).parent / "datasets" / "training"
        assert (staged_training / "combined.jsonl").exists()
        assert not (staged_training / "filtered_combined.jsonl").exists()

    def test_start_job_rejects_unknown_artifact(self, tmp_path: Path):
        training_dir = tmp_path / "training"
        dpo_dir = tmp_path / "dpo"
        artifact_root = tmp_path / "artifacts-root"
        jobs_root = tmp_path / "jobs"
        training_dir.mkdir()
        dpo_dir.mkdir()
        artifact_root.mkdir()
        _write_jsonl(training_dir / "combined.jsonl", 1)

        manager = LexTrainingJobManager(
            jobs_root=jobs_root,
            training_dir=training_dir,
            dpo_dir=dpo_dir,
            artifact_root=artifact_root,
            finetune_script=tmp_path / "finetune_lex.py",
            python_executable="/usr/bin/python3",
        )

        with pytest.raises(ValueError, match="Source artifact"):
            manager.start_job(
                mode="export",
                base_model=SAFE_BASE_MODELS[0],
                epochs=3,
                learning_rate=2e-4,
                batch_size=1,
                grad_accum=8,
                max_seq_len=4096,
                lora_rank=64,
                lora_alpha=16,
                training_files=[],
                dpo_files=[],
                source_artifact=str(tmp_path / "missing"),
                ollama_model="lex",
                max_per_cat=20,
                deploy_to_ollama=False,
            )


class TestMlTrainingRoutes:
    @pytest.fixture
    def client(self):
        from backend.routes.ml_training import router

        return TestClient(_app(router), raise_server_exceptions=True)

    def test_start_job_validation_error(self, client):
        response = client.post(
            "/api/ml/training/jobs",
            json={
                "mode": "export",
                "base_model": SAFE_BASE_MODELS[0],
                "epochs": 3,
                "learning_rate": 0.0002,
                "batch_size": 1,
                "grad_accum": 8,
                "max_seq_len": 4096,
                "lora_rank": 64,
                "lora_alpha": 16,
                "training_files": [],
                "dpo_files": [],
                "source_artifact": None,
                "ollama_model": "lex",
                "max_per_cat": 20,
                "deploy_to_ollama": False,
            },
        )
        assert response.status_code == 422

    def test_start_job_success(self, client):
        fake_job = {
            "job_id": "lex-1",
            "mode": "sft",
            "status": "running",
            "created_at": "2026-04-17T00:00:00+00:00",
            "base_model": SAFE_BASE_MODELS[0],
            "epochs": 3,
            "learning_rate": 0.0002,
            "batch_size": 1,
            "grad_accum": 8,
            "max_seq_len": 4096,
            "lora_rank": 64,
            "lora_alpha": 16,
            "ollama_model": "lex",
            "training_files": ["combined.jsonl"],
            "dpo_files": [],
            "source_artifact": None,
            "max_per_cat": 20,
            "deploy_to_ollama": False,
            "current_stage": "launching",
            "started_at": "2026-04-17T00:00:00+00:00",
            "finished_at": None,
            "pid": 1234,
            "returncode": None,
            "error": None,
            "log_path": "/tmp/job.log",
            "output_dir": "/tmp/output",
            "command": ["python", "scripts/finetune_lex.py"],
            "updated_at": "2026-04-17T00:00:00+00:00",
            "eval_score": None,
            "eval_n": None,
        }

        with patch("backend.routes.ml_training._job_manager") as manager:
            manager.start_job.return_value = fake_job
            response = client.post(
                "/api/ml/training/jobs",
                json={
                    "mode": "sft",
                    "base_model": SAFE_BASE_MODELS[0],
                    "epochs": 3,
                    "learning_rate": 0.0002,
                    "batch_size": 1,
                    "grad_accum": 8,
                    "max_seq_len": 4096,
                    "lora_rank": 64,
                    "lora_alpha": 16,
                    "training_files": ["combined.jsonl"],
                    "dpo_files": [],
                    "source_artifact": None,
                    "ollama_model": "lex",
                    "max_per_cat": 20,
                    "deploy_to_ollama": False,
                },
            )

        assert response.status_code == 200
        assert response.json()["job"]["job_id"] == "lex-1"

    def test_get_job_logs(self, client):
        with patch("backend.routes.ml_training._job_manager") as manager:
            manager.get_job_logs.return_value = {
                "job_id": "lex-1",
                "tail": 100,
                "lines": ["line 1", "line 2"],
                "text": "line 1\nline 2",
                "current_stage": "sft",
                "status": "running",
            }
            response = client.get("/api/ml/training/jobs/lex-1/logs?tail=100")

        assert response.status_code == 200
        assert response.json()["current_stage"] == "sft"

    def test_get_champion(self, client):
        with patch("backend.routes.ml_training._registry") as registry:
            registry.current.return_value = {
                "model": "lex-v3",
                "score": 0.93,
                "promoted_at": "2026-04-17T00:00:00+00:00",
            }
            response = client.get("/api/ml/training/champion")

        assert response.status_code == 200
        assert response.json()["model"] == "lex-v3"

    def test_promote_job_requires_eval_score(self, client):
        with patch("backend.routes.ml_training._job_manager") as manager:
            manager.get_job.return_value = {
                "job_id": "lex-1",
                "mode": "native",
                "ollama_model": "lex",
                "eval_score": None,
                "eval_n": None,
            }
            response = client.post("/api/ml/training/jobs/lex-1/promote")

        assert response.status_code == 409

    def test_promote_job_success(self, client):
        with (
            patch("backend.routes.ml_training._job_manager") as manager,
            patch("backend.routes.ml_training._registry") as registry,
        ):
            manager.get_job.return_value = {
                "job_id": "lex-1",
                "mode": "native",
                "ollama_model": "lex",
                "eval_score": 0.97,
                "eval_n": 100,
            }
            registry.promote.return_value = {
                "model": "lex-v3",
                "score": 0.97,
                "promoted_at": "2026-04-17T00:00:00+00:00",
            }

            response = client.post("/api/ml/training/jobs/lex-1/promote")

        assert response.status_code == 200
        assert response.json()["champion"]["model"] == "lex-v3"
        registry.promote.assert_called_once_with(model_name="lex-v3", job_id="lex-1", eval_score=0.97)

    def test_stream_metrics(self, client, tmp_path: Path):
        output_dir = tmp_path / "job-output"
        output_dir.mkdir()
        (output_dir / "training_metrics.jsonl").write_text(
            '{"step": 1, "loss": 1.23, "accuracy": 0.4, "ts": "2026-04-17T00:00:00+00:00"}\n',
            encoding="utf-8",
        )
        job = {
            "job_id": "lex-1",
            "status": "completed",
            "output_dir": str(output_dir),
        }

        with patch("backend.routes.ml_training._job_manager") as manager:
            manager.get_job.side_effect = [job, job]
            response = client.get("/api/ml/training/jobs/lex-1/metrics")

        assert response.status_code == 200
        assert 'data: {"step": 1, "loss": 1.23, "accuracy": 0.4, "ts": "2026-04-17T00:00:00+00:00"}' in response.text
        assert 'event: done\ndata: {"status": "completed"}' in response.text

    def test_workbench_snapshot(self, client):
        with (
            patch("backend.routes.ml_training._job_manager") as manager,
            patch("backend.routes.ml_training._lab") as lab,
            patch("backend.routes.ml_training._eval") as eval_framework,
            patch("backend.routes.ml_training._tracker") as tracker,
        ):
            manager.readiness.return_value = {
                "unsloth": {"installed": False},
                "ollama": {"reachable": False, "models": []},
                "gpu": {"available": False, "name": "none", "memory_gb": 0.0},
                "python": {"executable": "/tmp/python", "version": "3.12.0"},
                "finetune_script": {"exists": True, "path": "/tmp/finetune_lex.py"},
                "default_ollama_model": "lex",
                "base_model_options": SAFE_BASE_MODELS,
            }
            manager.list_artifacts.return_value = [{"name": "lex-sft", "label": "lex-sft · test", "kind": "directory", "path": "/tmp/lex-sft", "modified_at": "2026-04-17T00:00:00+00:00"}]
            manager.list_jobs.return_value = []
            manager.list_datasets.return_value = {"training": [{"name": "combined.jsonl"}], "dpo": [{"name": "prefs.jsonl"}]}
            manager.summarize_dataset_selection.return_value = {
                "training_files": 1,
                "training_lines": 12,
                "dpo_files": 1,
                "dpo_lines": 4,
            }
            manager.boundary_snapshot.return_value = {"total_files": 1, "top_files": [{"name": "combined.jsonl", "line_count": 12}]}

            lab.health_report.return_value = LabHealthReport(timestamp="2026-04-17T00:00:00+00:00", dataset_stats=DatasetStats(), recommendations=["Need more DPO"])
            lab.boundary_coverage.return_value = {"router_vs_it": 5}
            lab.list_golden_tasks.return_value = [{"task_id": "gt1", "difficulty": "hard"}]
            eval_framework.get_summary.return_value = {
                "total": 2,
                "avg_score": 0.8,
                "pass_rate": 0.5,
                "dimensions": {"tool_selection": {"avg": 0.9}},
            }
            eval_framework.get_results.return_value = [{"case_id": "c1", "overall_score": 0.9, "passed": True, "timestamp": "2026-04-17T00:00:00+00:00"}]
            tracker.list_runs.return_value = [{"run_id": "run-1", "status": "completed", "started_at": "2026-04-17T00:00:00+00:00", "hyperparameters": {}, "tags": {}, "artifacts": [], "notes": ""}]

            response = client.get("/api/ml/training/workbench")

        assert response.status_code == 200
        payload = response.json()
        assert payload["golden_coverage"]["total_tasks"] == 1
        assert payload["boundary_coverage"]["total_boundaries"] == 1
        assert payload["eval_summary"]["total_cases"] == 2

"""
Local Lex training job management for the dashboard control center.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

# UTC timezone compatibility (Python 3.10 and earlier)
UTC = timezone.utc
from pathlib import Path
from threading import Lock
from typing import Any, Literal
from urllib.error import URLError
from urllib.request import urlopen

from backend.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OUTPUT_DIR, PROJECT_ROOT

TRAINING_SOURCE_DIR = PROJECT_ROOT / "data" / "training"
DPO_SOURCE_DIR = PROJECT_ROOT / "data" / "dpo"
FINETUNE_SCRIPT = PROJECT_ROOT / "scripts" / "finetune_lex.py"
JOBS_ROOT = OUTPUT_DIR / "lex-finetune" / "jobs"
ARTIFACT_ROOT = OUTPUT_DIR / "lex-finetune"
NATIVE_MODELFILE_TEMPLATE = PROJECT_ROOT / "backend" / "ml" / "models" / "Modelfile.lex-v3"

SAFE_BASE_MODELS = [
    "google/gemma-3-12b-it",
    "unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
    "unsloth/Meta-Llama-3.1-8B-Instruct-bnb-4bit",
]

TrainingMode = Literal["prep-only", "sft", "dpo", "export", "native"]
JobStatus = Literal["running", "completed", "failed", "cancelling", "cancelled"]

_STAGE_PATTERNS: list[tuple[str, str]] = [
    ("native_curation", "Native Mode"),
    ("data_prep", "Stage 1: Data Preparation"),
    ("sft", "Stage 2: QLoRA Fine-tuning"),
    ("dpo", "Stage 2b: DPO Alignment"),
    ("gguf_export", "Stage 3: GGUF Export"),
    ("ollama_import", "Importing as"),
]
_SUCCESS_MARKERS = [
    "Pipeline complete in",
    "--prep-only: Stopping after data preparation.",
    "[OK] Native model '",
]
_FAILURE_MARKERS = ["[ERROR]", "Traceback (most recent call last):"]
_ARTIFACT_NAMES = {"lex-sft", "lex-dpo", "sft-checkpoint", "gguf"}


@dataclass
class DatasetEntry:
    name: str
    kind: Literal["training", "dpo"]
    size_bytes: int
    line_count: int
    modified_at: str


@dataclass
class ArtifactEntry:
    name: str
    label: str
    kind: str
    path: str
    modified_at: str


@dataclass
class TrainingJob:
    job_id: str
    mode: TrainingMode
    status: JobStatus
    created_at: str
    base_model: str
    epochs: int
    learning_rate: float
    batch_size: int
    grad_accum: int
    max_seq_len: int
    lora_rank: int
    lora_alpha: int
    ollama_model: str
    training_files: list[str] = field(default_factory=list)
    dpo_files: list[str] = field(default_factory=list)
    source_artifact: str | None = None
    max_per_cat: int = 20
    deploy_to_ollama: bool = True
    current_stage: str = "queued"
    started_at: str | None = None
    finished_at: str | None = None
    pid: int | None = None
    returncode: int | None = None
    error: str | None = None
    log_path: str = ""
    output_dir: str = ""
    command: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    eval_score: float | None = None
    eval_n: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TrainingJob":
        return cls(**payload)


class LexTrainingJobManager:
    def __init__(
        self,
        jobs_root: Path | None = None,
        training_dir: Path | None = None,
        dpo_dir: Path | None = None,
        artifact_root: Path | None = None,
        finetune_script: Path | None = None,
        python_executable: str | None = None,
    ) -> None:
        self._jobs_root = jobs_root or JOBS_ROOT
        self._jobs_root.mkdir(parents=True, exist_ok=True)
        self._index_path = self._jobs_root / "index.json"
        self._training_dir = training_dir or TRAINING_SOURCE_DIR
        self._dpo_dir = dpo_dir or DPO_SOURCE_DIR
        self._artifact_root = artifact_root or ARTIFACT_ROOT
        self._finetune_script = finetune_script or FINETUNE_SCRIPT
        self._python = python_executable or sys.executable
        self._lock = Lock()
        self._jobs: dict[str, TrainingJob] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._load()
        self.refresh_jobs()

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        self.refresh_jobs()
        jobs = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        return [job.to_dict() for job in jobs[:limit]]

    def get_job(self, job_id: str) -> dict[str, Any]:
        self.refresh_jobs()
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        return job.to_dict()

    def get_job_logs(self, job_id: str, tail: int = 200) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        path = Path(job.log_path)
        lines = self._tail_lines(path, tail)
        return {
            "job_id": job_id,
            "tail": tail,
            "lines": lines,
            "text": "\n".join(lines),
            "current_stage": job.current_stage,
            "status": job.status,
        }

    def list_datasets(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "training": [asdict(entry) for entry in self._scan_dataset_dir(self._training_dir, "training")],
            "dpo": [asdict(entry) for entry in self._scan_dataset_dir(self._dpo_dir, "dpo")],
        }

    def list_artifacts(self) -> list[dict[str, Any]]:
        return [asdict(entry) for entry in self._scan_artifacts()]

    def readiness(self) -> dict[str, Any]:
        ollama = self._probe_ollama()
        gpu = self._probe_gpu()
        return {
            "finetune_script": {
                "exists": self._finetune_script.exists(),
                "path": str(self._finetune_script),
            },
            "python": {
                "executable": self._python,
                "version": sys.version.split()[0],
            },
            "unsloth": {
                "installed": importlib.util.find_spec("unsloth") is not None,
            },
            "ollama": ollama,
            "gpu": gpu,
            "default_ollama_model": OLLAMA_MODEL,
            "base_model_options": SAFE_BASE_MODELS,
        }

    def start_job(
        self,
        *,
        mode: TrainingMode,
        base_model: str,
        epochs: int,
        learning_rate: float,
        batch_size: int,
        grad_accum: int,
        max_seq_len: int,
        lora_rank: int,
        lora_alpha: int,
        training_files: list[str],
        dpo_files: list[str],
        source_artifact: str | None,
        ollama_model: str,
        max_per_cat: int,
        deploy_to_ollama: bool,
    ) -> dict[str, Any]:
        self._validate_inputs(
            mode=mode,
            base_model=base_model,
            training_files=training_files,
            dpo_files=dpo_files,
            source_artifact=source_artifact,
        )

        created_at = datetime.now(UTC).isoformat()
        job_id = f"lex-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        suffix = 1
        while job_id in self._jobs:
            suffix += 1
            job_id = f"lex-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}-{suffix}"

        job_dir = self._jobs_root / job_id
        datasets_dir = job_dir / "datasets"
        training_stage_dir = datasets_dir / "training"
        dpo_stage_dir = datasets_dir / "dpo"
        artifacts_dir = job_dir / "artifacts"
        log_path = job_dir / "job.log"
        training_stage_dir.mkdir(parents=True, exist_ok=True)
        dpo_stage_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._stage_dataset_files(self._training_dir, training_stage_dir, training_files)
        self._stage_dataset_files(self._dpo_dir, dpo_stage_dir, dpo_files)

        env = os.environ.copy()
        env.update(
            {
                "PYTHONUNBUFFERED": "1",
                "LEX_TRAINING_DIR": str(training_stage_dir),
                "LEX_DPO_DIR": str(dpo_stage_dir),
                "LEX_OUTPUT_DIR": str(artifacts_dir),
                "LEX_NATIVE_MODELFILE": str(artifacts_dir / "Modelfile.lex-v3"),
                "LEX_BATCH_SIZE": str(batch_size),
                "LEX_GRAD_ACCUM": str(grad_accum),
                "LEX_MAX_SEQ_LEN": str(max_seq_len),
                "LEX_LORA_R": str(lora_rank),
                "LEX_LORA_ALPHA": str(lora_alpha),
                "OLLAMA_MODEL": ollama_model,
            }
        )
        native_modelfile = Path(env["LEX_NATIVE_MODELFILE"])
        if mode == "native" and NATIVE_MODELFILE_TEMPLATE.exists() and not native_modelfile.exists():
            shutil.copy2(NATIVE_MODELFILE_TEMPLATE, native_modelfile)

        command = [self._python, str(self._finetune_script)]
        if mode == "native":
            command.extend(["--native", "--max-per-cat", str(max_per_cat)])
            if not deploy_to_ollama:
                command.append("--skip-create")
        elif mode == "prep-only":
            command.extend(["--prep-only", "--base-model", base_model, "--epochs", str(epochs), "--lr", str(learning_rate)])
        elif mode == "sft":
            command.extend(["--base-model", base_model, "--epochs", str(epochs), "--lr", str(learning_rate)])
            if not deploy_to_ollama:
                command.append("--skip-ollama")
        elif mode == "dpo":
            command.extend(["--dpo", "--sft-model", source_artifact or ""])
            if not deploy_to_ollama:
                command.append("--skip-ollama")
        elif mode == "export":
            command.extend(["--export-only", "--sft-model", source_artifact or ""])
            if not deploy_to_ollama:
                command.append("--skip-ollama")

        job = TrainingJob(
            job_id=job_id,
            mode=mode,
            status="running",
            created_at=created_at,
            base_model=base_model,
            epochs=epochs,
            learning_rate=learning_rate,
            batch_size=batch_size,
            grad_accum=grad_accum,
            max_seq_len=max_seq_len,
            lora_rank=lora_rank,
            lora_alpha=lora_alpha,
            ollama_model=ollama_model,
            training_files=training_files,
            dpo_files=dpo_files,
            source_artifact=source_artifact,
            max_per_cat=max_per_cat,
            deploy_to_ollama=deploy_to_ollama,
            current_stage="launching",
            started_at=created_at,
            log_path=str(log_path),
            output_dir=str(artifacts_dir),
            command=command,
        )

        with log_path.open("w", encoding="utf-8") as handle:
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )

        job.pid = process.pid
        job.updated_at = datetime.now(UTC).isoformat()
        with self._lock:
            self._jobs[job_id] = job
            self._processes[job_id] = process
            self._save()
        return job.to_dict()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        self.refresh_jobs()
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        if job.status in {"completed", "failed", "cancelled"}:
            return job.to_dict()
        if job.pid is None:
            raise ValueError("Job has no live process")

        os.killpg(job.pid, signal.SIGTERM)
        job.status = "cancelling"
        job.updated_at = datetime.now(UTC).isoformat()
        self._save()
        return job.to_dict()

    def refresh_jobs(self) -> None:
        changed = False
        for job_id, job in list(self._jobs.items()):
            previous_eval_score = job.eval_score
            previous_eval_n = job.eval_n
            self._sync_artifact_metadata(job)
            if job.eval_score != previous_eval_score or job.eval_n != previous_eval_n:
                changed = True
            if job.status in {"completed", "failed", "cancelled"}:
                continue

            process = self._processes.get(job_id)
            returncode = process.poll() if process is not None else None
            if returncode is not None:
                job.returncode = returncode
                job.finished_at = datetime.now(UTC).isoformat()
                job.status = "cancelled" if job.status == "cancelling" else ("completed" if returncode == 0 else "failed")
                job.updated_at = datetime.now(UTC).isoformat()
                changed = True
            elif job.pid and self._pid_alive(job.pid):
                pass
            else:
                job.status = self._infer_terminal_status(job)
                job.finished_at = job.finished_at or datetime.now(UTC).isoformat()
                job.updated_at = datetime.now(UTC).isoformat()
                changed = True

            job.current_stage = self._infer_stage(Path(job.log_path), job.mode)

        if changed:
            self._save()

    def summarize_dataset_selection(self, training_files: list[str], dpo_files: list[str]) -> dict[str, Any]:
        training_entries = {entry.name: entry for entry in self._scan_dataset_dir(self._training_dir, "training")}
        dpo_entries = {entry.name: entry for entry in self._scan_dataset_dir(self._dpo_dir, "dpo")}
        training_total = sum(training_entries[name].line_count for name in training_files if name in training_entries)
        dpo_total = sum(dpo_entries[name].line_count for name in dpo_files if name in dpo_entries)
        return {
            "training_files": len(training_files),
            "training_lines": training_total,
            "dpo_files": len(dpo_files),
            "dpo_lines": dpo_total,
        }

    def boundary_snapshot(self) -> dict[str, Any]:
        counter: Counter[str] = Counter()
        for entry in self._scan_dataset_dir(self._training_dir, "training"):
            counter[entry.name] = entry.line_count
        return {
            "total_files": len(counter),
            "top_files": [{"name": name, "line_count": count} for name, count in counter.most_common(5)],
        }

    def _load(self) -> None:
        if not self._index_path.exists():
            return
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for raw_job in payload.get("jobs", []):
            try:
                job = TrainingJob.from_dict(raw_job)
            except TypeError:
                continue
            self._jobs[job.job_id] = job

    def _save(self) -> None:
        payload = {"jobs": [job.to_dict() for job in sorted(self._jobs.values(), key=lambda item: item.created_at)]}
        self._index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _scan_dataset_dir(self, base_dir: Path, kind: Literal["training", "dpo"]) -> list[DatasetEntry]:
        entries: list[DatasetEntry] = []
        if not base_dir.exists():
            return entries
        for path in sorted(base_dir.glob("*.jsonl")):
            try:
                line_count = sum(1 for _ in path.open(encoding="utf-8", errors="ignore"))
            except OSError:
                line_count = 0
            entries.append(
                DatasetEntry(
                    name=path.name,
                    kind=kind,
                    size_bytes=path.stat().st_size,
                    line_count=line_count,
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(),
                )
            )
        return entries

    def _scan_artifacts(self) -> list[ArtifactEntry]:
        entries: list[ArtifactEntry] = []
        seen: set[str] = set()
        if not self._artifact_root.exists():
            return entries

        for candidate in self._artifact_root.rglob("*"):
            if not candidate.exists():
                continue
            if candidate.name not in _ARTIFACT_NAMES:
                continue
            if candidate.is_dir() and not any(candidate.iterdir()):
                continue
            path_key = str(candidate.resolve())
            if path_key in seen:
                continue
            seen.add(path_key)
            label = f"{candidate.name} · {candidate.parent.name}"
            kind = "directory" if candidate.is_dir() else "file"
            entries.append(
                ArtifactEntry(
                    name=candidate.name,
                    label=label,
                    kind=kind,
                    path=path_key,
                    modified_at=datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC).isoformat(),
                )
            )

        return sorted(entries, key=lambda entry: entry.modified_at, reverse=True)

    def _probe_ollama(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "reachable": False,
            "base_url": OLLAMA_BASE_URL,
            "models": [],
        }
        try:
            with urlopen(f"{OLLAMA_BASE_URL}/api/tags", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            result["reachable"] = False
            return result

        result["reachable"] = True
        result["models"] = [item.get("name", "") for item in payload.get("models", []) if item.get("name")]
        return result

    def _probe_gpu(self) -> dict[str, Any]:
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                completed = subprocess.run(
                    [
                        nvidia_smi,
                        "--query-gpu=name,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=2,
                )
                lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
                if lines:
                    name, memory = [part.strip() for part in lines[0].split(",", maxsplit=1)]
                    return {
                        "available": True,
                        "name": name,
                        "memory_gb": round(float(memory) / 1024, 1),
                    }
            except (OSError, ValueError, subprocess.SubprocessError):
                pass

        try:
            import torch
        except ImportError:
            return {"available": False, "name": "none", "memory_gb": 0.0}

        if not torch.cuda.is_available():
            return {"available": False, "name": "none", "memory_gb": 0.0}

        props = torch.cuda.get_device_properties(0)
        return {
            "available": True,
            "name": torch.cuda.get_device_name(0),
            "memory_gb": round(props.total_memory / (1024**3), 1),
        }

    def _validate_inputs(
        self,
        *,
        mode: TrainingMode,
        base_model: str,
        training_files: list[str],
        dpo_files: list[str],
        source_artifact: str | None,
    ) -> None:
        if base_model not in SAFE_BASE_MODELS:
            raise ValueError(f"Unsupported base model: {base_model}")

        training_available = {entry.name for entry in self._scan_dataset_dir(self._training_dir, "training")}
        dpo_available = {entry.name for entry in self._scan_dataset_dir(self._dpo_dir, "dpo")}
        artifacts = {entry["path"] for entry in self.list_artifacts()}

        if any(name not in training_available for name in training_files):
            raise ValueError("Unknown training file selection")
        if any(name not in dpo_available for name in dpo_files):
            raise ValueError("Unknown DPO file selection")

        if mode in {"prep-only", "sft", "native"} and not training_files:
            raise ValueError("Select at least one training dataset")
        if mode == "dpo" and not dpo_files:
            raise ValueError("Select at least one DPO dataset")
        if mode in {"dpo", "export"} and not source_artifact:
            raise ValueError("A source artifact is required for this mode")
        if source_artifact and source_artifact not in artifacts:
            raise ValueError("Source artifact is not available")

    def _stage_dataset_files(self, source_root: Path, target_root: Path, file_names: list[str]) -> None:
        for file_name in file_names:
            src = source_root / file_name
            dst = target_root / file_name
            if dst.exists():
                continue
            try:
                dst.symlink_to(src)
            except OSError:
                shutil.copy2(src, dst)

    def _pid_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _tail_lines(self, path: Path, tail: int) -> list[str]:
        if not path.exists():
            return []
        try:
            return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-tail:]
        except OSError:
            return []

    def _sync_artifact_metadata(self, job: TrainingJob) -> None:
        eval_path = Path(job.output_dir) / "eval.json"
        if not eval_path.exists():
            return
        try:
            payload = json.loads(eval_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        score = payload.get("eval_score")
        total = payload.get("eval_n")
        try:
            job.eval_score = float(score) if score is not None else None
        except (TypeError, ValueError):
            job.eval_score = None
        try:
            job.eval_n = int(total) if total is not None else None
        except (TypeError, ValueError):
            job.eval_n = None

    def _infer_stage(self, log_path: Path, mode: TrainingMode) -> str:
        lines = self._tail_lines(log_path, 120)
        stage = "launching"
        for label, marker in _STAGE_PATTERNS:
            if any(marker in line for line in lines):
                stage = label
        if mode == "prep-only" and any(_SUCCESS_MARKERS[1] in line for line in lines):
            stage = "completed_prep"
        return stage

    def _infer_terminal_status(self, job: TrainingJob) -> JobStatus:
        lines = self._tail_lines(Path(job.log_path), 160)
        if job.status == "cancelling":
            return "cancelled"
        if any(marker in line for marker in _SUCCESS_MARKERS for line in lines):
            return "completed"
        if any(marker in line for marker in _FAILURE_MARKERS for line in lines):
            return "failed"
        return "failed"

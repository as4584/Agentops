from __future__ import annotations

from pathlib import Path

from backend.webgen.models import ClientBrief, PageSpec, SiteProject, SiteStatus
from backend.webgen.pipeline import WebGenPipeline
from backend.webgen.site_store import SiteStore


class _FakeLocalLLM:
    model = "local"


def _build_project(project_root: Path) -> SiteProject:
    project = SiteProject(brief=ClientBrief(business_name="Acme"))
    project.status = SiteStatus.QA_PASS
    project.output_dir = str(project_root / "output" / "webgen" / "acme")
    project.pages = [PageSpec(slug="index", title="Home", html="<html><body>ok</body></html>")]
    return project


def test_webgen_export_blocks_without_all_three_checks(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox"
    playbox_root = tmp_path / "playbox"

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    playbox_root.mkdir(parents=True, exist_ok=True)

    import sandbox.session_manager as session_manager
    import backend.webgen.pipeline as pipeline_module

    monkeypatch.setattr(session_manager, "SANDBOX_ROOT_DIR", sandbox_root)
    monkeypatch.setattr(session_manager, "PLAYBOX_DIR", playbox_root)
    monkeypatch.setattr(pipeline_module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(pipeline_module, "SANDBOX_ENFORCEMENT_ENABLED", True)

    pipeline = WebGenPipeline(llm=_FakeLocalLLM(), site_store=SiteStore(base_dir=tmp_path / "site-store"))
    project = _build_project(project_root)

    export_path = pipeline.export(project, quality_checks={"tests_ok": True})

    assert project.metadata.get("release_blocked") is True
    assert "sandbox_session_id" in project.metadata
    assert any(
        "Required quality check failed or missing" in item
        for item in project.metadata.get("release_violations", [])
    )

    rel_index = Path("output/webgen/acme/index.html")
    staged_index = export_path / rel_index
    released_index = project_root / rel_index
    assert staged_index.exists()
    assert not released_index.exists()


def test_webgen_export_releases_when_all_three_checks_pass(monkeypatch, tmp_path: Path):
    project_root = tmp_path / "project"
    sandbox_root = tmp_path / "sandbox"
    playbox_root = tmp_path / "playbox"

    project_root.mkdir(parents=True, exist_ok=True)
    (project_root / "docs").mkdir(parents=True, exist_ok=True)
    sandbox_root.mkdir(parents=True, exist_ok=True)
    playbox_root.mkdir(parents=True, exist_ok=True)

    import sandbox.session_manager as session_manager
    import backend.webgen.pipeline as pipeline_module

    monkeypatch.setattr(session_manager, "SANDBOX_ROOT_DIR", sandbox_root)
    monkeypatch.setattr(session_manager, "PLAYBOX_DIR", playbox_root)
    monkeypatch.setattr(pipeline_module, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(pipeline_module, "SANDBOX_ENFORCEMENT_ENABLED", True)

    pipeline = WebGenPipeline(llm=_FakeLocalLLM(), site_store=SiteStore(base_dir=tmp_path / "site-store"))
    project = _build_project(project_root)

    export_path = pipeline.export(
        project,
        quality_checks={
            "tests_ok": True,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
        },
    )

    rel_index = Path("output/webgen/acme/index.html")
    released_index = project_root / rel_index
    assert export_path == Path(project.output_dir)
    assert released_index.exists()
    assert project.status == SiteStatus.READY

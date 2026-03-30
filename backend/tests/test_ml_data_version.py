"""
Tests for DataVersioner — SHA-256 content hashing, versioning, diffs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ml.data_version import DataVersioner


@pytest.fixture
def versioner(tmp_path: Path) -> DataVersioner:
    data = tmp_path / "data"
    data.mkdir()
    return DataVersioner(training_dir=data, versions_dir=tmp_path / "versions")


def _seed(data_dir: Path, files: dict[str, str]) -> None:
    """Write files into the data directory."""
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (data_dir / name).write_text(content)


class TestDataVersioner:
    def test_compute_version_basic(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"a.csv": "col1,col2\n1,2\n"})
        result = versioner.compute_version()
        assert isinstance(result, dict)
        assert "version" in result
        assert len(result["version"]) == 16  # truncated SHA-256

    def test_same_content_same_hash(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"a.csv": "hello"})
        v1 = versioner.compute_version()["version"]
        v2 = versioner.compute_version()["version"]
        assert v1 == v2

    def test_different_content_different_hash(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"a.csv": "hello"})
        v1 = versioner.compute_version()["version"]
        _seed(versioner._data_dir, {"a.csv": "world"})
        v2 = versioner.compute_version()["version"]
        assert v1 != v2

    def test_get_version(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"data.txt": "test"})
        vh = versioner.compute_version()["version"]
        info = versioner.get_version(vh)
        assert info is not None
        assert info["version"] == vh
        assert "files" in info
        assert "data.txt" in [f["path"] for f in info["files"]]

    def test_list_versions(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"f.txt": "v1"})
        versioner.compute_version()
        _seed(versioner._data_dir, {"f.txt": "v2"})
        versioner.compute_version()
        versions = versioner.list_versions()
        assert len(versions) == 2

    def test_diff_versions(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"a.txt": "hello", "b.txt": "world"})
        v1 = versioner.compute_version()["version"]

        # Modify a, remove b, add c
        (versioner._data_dir / "b.txt").unlink()
        _seed(versioner._data_dir, {"a.txt": "changed", "c.txt": "new"})
        v2 = versioner.compute_version()["version"]

        diff = versioner.diff_versions(v1, v2)
        assert "c.txt" in diff["added"]
        assert "b.txt" in diff["removed"]
        assert "a.txt" in diff["modified"]

    def test_get_missing_version_returns_none(self, versioner: DataVersioner) -> None:
        result = versioner.get_version("0" * 16)
        assert result is None

    def test_diff_missing_version_raises(self, versioner: DataVersioner) -> None:
        _seed(versioner._data_dir, {"f.txt": "ok"})
        vh = versioner.compute_version()["version"]
        with pytest.raises(KeyError):
            versioner.diff_versions(vh, "0" * 16)

    def test_subdirectories(self, versioner: DataVersioner) -> None:
        sub = versioner._data_dir / "subdir"
        sub.mkdir(parents=True)
        (sub / "nested.csv").write_text("1,2,3")
        info = versioner.compute_version()
        paths = [f["path"] for f in info["files"]]
        assert any("nested.csv" in p for p in paths)

    def test_empty_directory(self, versioner: DataVersioner) -> None:
        result = versioner.compute_version()
        assert isinstance(result, dict)
        assert result["file_count"] == 0

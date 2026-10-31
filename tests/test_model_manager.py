"""Pruebas del manifiesto y del ciclo de descarga del gestor de modelos."""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest

from clases.gestor_modelos import (
    ModelIntegrityError,
    ModelManager,
    load_model_manifest,
)


def _write_manifest(
    path: Path,
    *,
    model_id: str = "sample",
    file_name: str = "test/sample.bin",
    content: bytes = b"model bytes",
    sha256: str | None = None,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "id": model_id,
                        "file": file_name,
                        "url": "https://example.invalid/sample.bin",
                        "sha256": sha256 or hashlib.sha256(content).hexdigest(),
                        "size": len(content),
                        "required": True,
                        "variant": "desktop",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


class FakeResponse(BytesIO):
    def __init__(
        self,
        content: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(content)
        self.status = status
        self.headers = headers or {"Content-Length": str(len(content))}

    def getcode(self) -> int:
        return self.status


def test_manifest_loads_declared_desktop_models() -> None:
    entries = load_model_manifest()

    assert {entry.id for entry in entries} == {
        "whisper-base",
        "whisper-tiny",
        "piper-es-voz",
        "piper-es-voz-config",
        "yolo11n",
    }
    assert next(entry for entry in entries if entry.id == "whisper-tiny").required is False


def test_ensure_downloads_to_part_verifies_hash_and_reports_progress(
    tmp_path: Path,
) -> None:
    content = b"downloaded model bytes"
    manifest_path = _write_manifest(tmp_path / "manifest.json", content=content)
    manager = ModelManager(manifest_path, models_dir=tmp_path / "models")
    progress: list[tuple[int, int]] = []

    with patch(
        "clases.gestor_modelos.urllib.request.urlopen",
        return_value=FakeResponse(content),
    ) as open_url:
        model_path = manager.ensure(
            "sample",
            on_progress=lambda downloaded, total: progress.append((downloaded, total)),
        )

    assert model_path.read_bytes() == content
    assert not model_path.with_name(model_path.name + ".part").exists()
    assert progress[-1] == (len(content), len(content))
    assert open_url.call_count == 1


def test_ensure_rejects_hash_mismatch_and_removes_corrupt_partial(
    tmp_path: Path,
) -> None:
    content = b"incorrect bytes"
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        content=content,
        sha256="0" * 64,
    )
    manager = ModelManager(manifest_path, models_dir=tmp_path / "models")

    with patch(
        "clases.gestor_modelos.urllib.request.urlopen",
        return_value=FakeResponse(content),
    ):
        with pytest.raises(ModelIntegrityError, match="SHA256 incorrecto"):
            manager.ensure("sample")

    assert not (tmp_path / "models" / "test" / "sample.bin").exists()
    assert not (tmp_path / "models" / "test" / "sample.bin.part").exists()


def test_is_ready_checks_size_without_recalculating_hash(
    tmp_path: Path,
) -> None:
    content = b"local model"
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        content=content,
        sha256="0" * 64,
    )
    models_dir = tmp_path / "models"
    model_path = models_dir / "test" / "sample.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(content)
    manager = ModelManager(manifest_path, models_dir=models_dir)

    with patch("clases.gestor_modelos._sha256_file") as calculate_hash:
        assert manager.is_ready("sample")
    calculate_hash.assert_not_called()


def test_ensure_rejects_hash_mismatch_in_existing_file(tmp_path: Path) -> None:
    content = b"existing bytes with wrong digest"
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        content=content,
        sha256="0" * 64,
    )
    models_dir = tmp_path / "models"
    model_path = models_dir / "test" / "sample.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(content)
    manager = ModelManager(manifest_path, models_dir=models_dir)

    with patch(
        "clases.gestor_modelos.urllib.request.urlopen",
        return_value=FakeResponse(content),
    ):
        with pytest.raises(ModelIntegrityError, match="SHA256 incorrecto"):
            manager.ensure("sample")

    assert model_path.read_bytes() == content


def test_legacy_development_model_path_remains_supported(tmp_path: Path) -> None:
    content = b"legacy YOLO weights"
    manifest_path = _write_manifest(
        tmp_path / "manifest.json",
        model_id="yolo11n",
        file_name="yolo/yolo11n.pt",
        content=content,
    )
    legacy_dir = tmp_path / "modelos"
    legacy_dir.mkdir()
    legacy_model = legacy_dir / "yolo11n.pt"
    legacy_model.write_bytes(content)
    manager = ModelManager(
        manifest_path,
        models_dir=tmp_path / "managed",
        legacy_models_dir=legacy_dir,
    )

    assert manager.is_ready("yolo11n")
    assert manager.path("yolo11n") == legacy_model

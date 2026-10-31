"""Carga manifiestos y gestiona descargas verificadas de modelos locales."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from platformdirs import user_data_path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "config" / "modelos.json"
MODEL_DIRECTORY_ENV = "ASISTENTE_MODELS_DIR"
CHUNK_SIZE = 64 * 1024
ProgressCallback = Callable[[int, int], None]


class ModelDownloadError(RuntimeError):
    """Error legible al descargar o guardar un modelo."""


class ModelIntegrityError(ModelDownloadError):
    """El modelo descargado no coincide con su tamaño o SHA256 esperado."""


@dataclass(frozen=True, slots=True)
class ModelEntry:
    """Metadatos validados de un archivo de modelo."""

    id: str
    file: str
    url: str
    sha256: str
    size: int
    required: bool
    variant: str | None = None


def load_model_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> tuple[ModelEntry, ...]:
    """Lee y valida el manifiesto de modelos."""
    manifest_path = Path(path)
    try:
        with manifest_path.open(encoding="utf-8") as manifest_file:
            data = json.load(manifest_file)
    except json.JSONDecodeError as error:
        raise ValueError(f"El manifiesto no contiene JSON válido: {manifest_path}") from error

    if not isinstance(data, dict) or set(data) != {"models"}:
        raise ValueError("El manifiesto debe contener únicamente la lista 'models'.")
    models = data["models"]
    if not isinstance(models, list) or not models:
        raise ValueError("El manifiesto debe definir al menos un modelo.")

    entries: list[ModelEntry] = []
    seen_ids: set[str] = set()
    seen_files: set[str] = set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("Cada definición de modelo debe ser un objeto JSON.")
        required_fields = {"id", "file", "url", "sha256", "size", "required"}
        if not required_fields.issubset(model) or set(model) - required_fields - {"variant"}:
            raise ValueError(
                "Cada modelo requiere id, file, url, sha256, size y required; "
                "variant es opcional."
            )

        model_id, file_name = model["id"], model["file"]
        url, sha256, size, is_required = (
            model["url"],
            model["sha256"],
            model["size"],
            model["required"],
        )
        variant = model.get("variant")
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("El identificador del modelo debe ser texto no vacío.")
        if model_id in seen_ids:
            raise ValueError(f"Identificador de modelo duplicado: {model_id}")
        if not isinstance(file_name, str) or not file_name.strip():
            raise ValueError(f"'{model_id}' requiere una ruta file no vacía.")
        relative_file = PurePosixPath(file_name)
        if (
            relative_file.is_absolute()
            or ".." in relative_file.parts
            or "\\" in file_name
        ):
            raise ValueError(f"La ruta de '{model_id}' debe ser relativa y segura.")
        if file_name in seen_files:
            raise ValueError(f"Ruta de modelo duplicada: {file_name}")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"'{model_id}' requiere un campo url.")
        parsed_url = urlsplit(url)
        if url != "TODO" and (
            parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc
        ):
            raise ValueError(f"La URL de '{model_id}' debe ser HTTP o HTTPS válida.")
        if not isinstance(sha256, str) or (
            sha256 != "TODO" and re.fullmatch(r"[a-fA-F0-9]{64}", sha256) is None
        ):
            raise ValueError(f"El SHA256 de '{model_id}' debe tener 64 dígitos hexadecimales.")
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            raise ValueError(f"El tamaño de '{model_id}' debe ser un entero positivo.")
        if not isinstance(is_required, bool):
            raise ValueError(f"El campo required de '{model_id}' debe ser booleano.")
        if variant is not None and (
            not isinstance(variant, str) or variant not in {"desktop", "android"}
        ):
            raise ValueError(f"La variante de '{model_id}' debe ser desktop o android.")

        entries.append(
            ModelEntry(
                id=model_id,
                file=file_name,
                url=url,
                sha256=sha256.lower(),
                size=size,
                required=is_required,
                variant=variant,
            )
        )
        seen_ids.add(model_id)
        seen_files.add(file_name)
    return tuple(entries)


class ModelManager:
    """Resuelve modelos locales y descarga archivos con comprobación SHA256."""

    def __init__(
        self,
        manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
        models_dir: str | Path | None = None,
        legacy_models_dir: str | Path | None = None,
    ) -> None:
        self._entries = {entry.id: entry for entry in load_model_manifest(manifest_path)}
        env_models_dir = os.environ.get(MODEL_DIRECTORY_ENV)
        if models_dir is not None:
            self._models_dir = Path(models_dir).expanduser()
            self._legacy_models_dir = (
                Path(legacy_models_dir).expanduser()
                if legacy_models_dir is not None
                else None
            )
        else:
            configured_dir = env_models_dir
            self._models_dir = (
                Path(configured_dir).expanduser()
                if configured_dir
                else user_data_path("asistente", appauthor=False) / "modelos"
            )
            self._legacy_models_dir = (
                Path(legacy_models_dir).expanduser()
                if legacy_models_dir is not None
                else PROJECT_ROOT / "modelos" if not configured_dir else None
            )

    @property
    def entries(self) -> tuple[ModelEntry, ...]:
        """Definiciones en el mismo orden del manifiesto."""
        return tuple(self._entries.values())

    def path(self, model_id: str) -> Path:
        """Devuelve el archivo válido disponible o la ruta de descarga predeterminada."""
        entry = self._get_entry(model_id)
        destination = self._destination(entry)
        if self._is_ready_at(destination, entry):
            return destination

        legacy_path = self._legacy_path(model_id)
        if legacy_path is not None and self._is_ready_at(legacy_path, entry):
            return legacy_path
        return destination

    def is_ready(self, model_id: str) -> bool:
        """Comprueba existencia y tamaño sin calcular el hash durante el arranque."""
        entry = self._get_entry(model_id)
        if self._is_ready_at(self._destination(entry), entry):
            return True
        legacy_path = self._legacy_path(model_id)
        return legacy_path is not None and self._is_ready_at(legacy_path, entry)

    def ensure(
        self,
        model_id: str,
        on_progress: ProgressCallback | None = None,
    ) -> Path:
        """Descarga el archivo si falta y lo publica tras verificar tamaño y SHA256.

        El callback recibe (bytes_descargados, tamaño_total). Las descargas
        incompletas quedan en `.part` y se reanudan si el servidor soporta Range.
        """
        entry = self._get_entry(model_id)
        if self.is_ready(model_id):
            existing_path = self.path(model_id)
            if entry.sha256 == "TODO" or _sha256_file(existing_path) == entry.sha256:
                return existing_path
        if entry.url == "TODO":
            raise ModelDownloadError(
                f"No hay una URL verificada para '{model_id}'; complete config/modelos.json."
            )
        if entry.sha256 == "TODO":
            raise ModelIntegrityError(
                f"No hay un SHA256 verificado para '{model_id}'; complete config/modelos.json."
            )

        destination = self._destination(entry)
        destination.parent.mkdir(parents=True, exist_ok=True)
        part_path = destination.with_name(destination.name + ".part")
        try:
            self._download_to_part(entry, part_path, on_progress)
        except (OSError, urllib.error.URLError) as error:
            raise ModelDownloadError(
                f"No se pudo descargar '{model_id}' desde {entry.url}: {error}"
            ) from error

        actual_size = part_path.stat().st_size
        if actual_size != entry.size:
            part_path.unlink(missing_ok=True)
            raise ModelIntegrityError(
                f"Tamaño incorrecto para '{model_id}': {actual_size} bytes; "
                f"se esperaban {entry.size}."
            )
        actual_sha256 = _sha256_file(part_path)
        if actual_sha256 != entry.sha256:
            part_path.unlink(missing_ok=True)
            raise ModelIntegrityError(
                f"SHA256 incorrecto para '{model_id}': {actual_sha256}."
            )

        os.replace(part_path, destination)
        return destination

    def _download_to_part(
        self,
        entry: ModelEntry,
        part_path: Path,
        on_progress: ProgressCallback | None,
    ) -> None:
        offset = part_path.stat().st_size if part_path.exists() else 0
        if offset >= entry.size:
            part_path.unlink()
            offset = 0

        request = urllib.request.Request(entry.url)
        if offset:
            request.add_header("Range", f"bytes={offset}-")

        with urllib.request.urlopen(request, timeout=60) as response:
            status = getattr(response, "status", response.getcode())
            if offset and status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    response.close()
                    part_path.unlink(missing_ok=True)
                    return self._download_to_part(entry, part_path, on_progress)
                mode = "ab"
                downloaded = offset
            else:
                mode = "wb"
                downloaded = 0

            if on_progress is not None:
                on_progress(downloaded, entry.size)
            with part_path.open(mode) as part_file:
                while chunk := response.read(CHUNK_SIZE):
                    part_file.write(chunk)
                    downloaded += len(chunk)
                    if on_progress is not None:
                        on_progress(downloaded, entry.size)

    def _get_entry(self, model_id: str) -> ModelEntry:
        try:
            return self._entries[model_id]
        except KeyError as error:
            raise KeyError(f"Modelo no definido en el manifiesto: {model_id}") from error

    def _destination(self, entry: ModelEntry) -> Path:
        return self._models_dir.joinpath(*PurePosixPath(entry.file).parts)

    def _legacy_path(self, model_id: str) -> Path | None:
        if self._legacy_models_dir is None:
            return None
        legacy_files = {
            "whisper-base": "ggml-base.bin",
            "whisper-tiny": "ggml-tiny.bin",
            "piper-es-voz": "voces/es_ES-sharvard-medium.onnx",
            "piper-es-voz-config": "voces/es_ES-sharvard-medium.onnx.json",
            "yolo11n": "yolo11n.pt",
        }
        legacy_file = legacy_files.get(model_id)
        return (
            self._legacy_models_dir / legacy_file
            if legacy_file is not None
            else None
        )

    @staticmethod
    def _is_ready_at(path: Path, entry: ModelEntry) -> bool:
        try:
            return path.is_file() and path.stat().st_size == entry.size
        except OSError:
            return False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        while chunk := model_file.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()

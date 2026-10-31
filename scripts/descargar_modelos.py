#!/usr/bin/env python3
"""Descarga modelos requeridos o verifica archivos locales contra el manifiesto."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from clases.gestor_modelos import ModelDownloadError, ModelManager  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        while chunk := model_file.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify(manager: ModelManager, model_ids: set[str]) -> int:
    failures = 0
    for entry in manager.entries:
        if entry.id not in model_ids:
            continue
        path = manager.path(entry.id)
        if not path.is_file():
            print(f"[FALTA] {entry.id}: {path}")
            failures += 1
            continue
        size = path.stat().st_size
        digest = _sha256(path)
        matches = size == entry.size and (
            entry.sha256 == "TODO" or digest == entry.sha256
        )
        status = "OK" if matches else "ERROR"
        print(f"[{status}] {entry.id}\t{size}\t{digest}\t{path}")
        failures += not matches
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verificar",
        action="store_true",
        help="Recalcula y compara tamaño y SHA256 sin descargar.",
    )
    parser.add_argument(
        "--solo",
        metavar="ID",
        help="Procesa solo el modelo indicado en config/modelos.json.",
    )
    args = parser.parse_args()

    try:
        manager = ModelManager()
        known_ids = {entry.id for entry in manager.entries}
        if args.solo and args.solo not in known_ids:
            parser.error(f"ID de modelo desconocido: {args.solo}")
        selected_ids = (
            {args.solo}
            if args.solo
            else {entry.id for entry in manager.entries if entry.required}
        )
        if args.verificar:
            return _verify(manager, selected_ids)

        for entry in manager.entries:
            if entry.id not in selected_ids:
                continue

            last_percent = -1

            def report_progress(downloaded: int, total: int) -> None:
                nonlocal last_percent
                percent = min(100, downloaded * 100 // total)
                if percent != last_percent:
                    print(
                        f"\r[{entry.id}] {percent:3d}% "
                        f"({downloaded}/{total} bytes)",
                        end="",
                        flush=True,
                    )
                    last_percent = percent

            path = (
                manager.path(entry.id)
                if manager.is_ready(entry.id)
                else manager.ensure(entry.id, on_progress=report_progress)
            )
            if last_percent >= 0:
                print()
            print(f"[LISTO] {entry.id}: {path}")
    except (ModelDownloadError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

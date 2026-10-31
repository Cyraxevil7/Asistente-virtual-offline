#!/usr/bin/env python3
"""Imprime SHA256 y tamaño de los modelos locales definidos en el manifiesto."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from clases.gestor_modelos import ModelManager  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as model_file:
        while chunk := model_file.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--solo",
        metavar="ID",
        help="Calcula solo el modelo indicado en config/modelos.json.",
    )
    args = parser.parse_args()

    manager = ModelManager()
    if args.solo and args.solo not in {entry.id for entry in manager.entries}:
        parser.error(f"ID de modelo desconocido: {args.solo}")

    missing = 0
    print("id\tfile\tsize\tsha256")
    for entry in manager.entries:
        if args.solo and entry.id != args.solo:
            continue
        path = manager.path(entry.id)
        if not path.is_file():
            print(f"[FALTA]\t{entry.id}\t{path}", file=sys.stderr)
            missing += 1
            continue
        print(
            f"{entry.id}\t{path}\t{path.stat().st_size}\t{_sha256(path)}"
        )
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Mide uso de RAM/CPU por fase sin cargar modelos adicionales."""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import psutil  # noqa: E402
from platformdirs import user_data_path  # noqa: E402


def _is_whisper_server(process: psutil.Process) -> bool:
    try:
        identity = " ".join((process.name(), *process.cmdline())).lower()
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return False
    return "whisper-server" in identity


def _process_tree(root: psutil.Process) -> list[psutil.Process]:
    try:
        return [root, *root.children(recursive=True)]
    except (psutil.AccessDenied, psutil.NoSuchProcess):
        return [root]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="PID del proceso main.py.")
    parser.add_argument(
        "--fase",
        choices=("reposo", "camara", "transcripcion"),
        required=True,
        help="Estado observado durante esta medición.",
    )
    parser.add_argument("--intervalo", type=float, default=1.0, help="Segundos entre muestras.")
    parser.add_argument("--duracion", type=float, default=60.0, help="Duración en segundos.")
    parser.add_argument(
        "--salida",
        type=Path,
        default=user_data_path("asistente", appauthor=False)
        / "mediciones"
        / "recursos.csv",
        help="CSV de salida (por defecto, fuera del repositorio).",
    )
    args = parser.parse_args()
    if args.intervalo <= 0 or args.duracion <= 0:
        parser.error("--intervalo y --duracion deben ser mayores que cero.")

    try:
        root = psutil.Process(args.pid)
    except psutil.NoSuchProcess:
        print(f"No existe el proceso con PID {args.pid}.", file=sys.stderr)
        return 1

    processes = _process_tree(root)
    for process in processes:
        try:
            process.cpu_percent(interval=None)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    write_header = not args.salida.exists() or args.salida.stat().st_size == 0
    columns = (
        "timestamp_utc",
        "fase",
        "pid_aplicacion",
        "ram_aplicacion_mb",
        "ram_whisper_mb",
        "ram_arbol_procesos_mb",
        "cpu_aplicacion_pct",
        "cpu_whisper_pct",
    )
    end_at = time.monotonic() + args.duracion
    try:
        with args.salida.open("a", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=columns)
            if write_header:
                writer.writeheader()
            print(
                f"Midiendo fase '{args.fase}' durante {args.duracion:g} s. "
                f"CSV: {args.salida}",
                flush=True,
            )
            while time.monotonic() < end_at:
                sample_processes = _process_tree(root)
                app_rss = 0
                whisper_rss = 0
                tree_rss = 0
                app_cpu = 0.0
                whisper_cpu = 0.0
                for process in sample_processes:
                    try:
                        memory = process.memory_info().rss
                        cpu = process.cpu_percent(interval=None)
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        continue
                    tree_rss += memory
                    if process.pid == root.pid:
                        app_rss = memory
                        app_cpu = cpu
                    elif _is_whisper_server(process):
                        whisper_rss += memory
                        whisper_cpu += cpu
                writer.writerow(
                    {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "fase": args.fase,
                        "pid_aplicacion": root.pid,
                        "ram_aplicacion_mb": round(app_rss / (1024 * 1024), 2),
                        "ram_whisper_mb": round(whisper_rss / (1024 * 1024), 2),
                        "ram_arbol_procesos_mb": round(tree_rss / (1024 * 1024), 2),
                        "cpu_aplicacion_pct": round(app_cpu, 2),
                        "cpu_whisper_pct": round(whisper_cpu, 2),
                    }
                )
                csv_file.flush()
                time.sleep(min(args.intervalo, max(0, end_at - time.monotonic())))
    except psutil.NoSuchProcess:
        print("El proceso principal terminó durante la medición.", file=sys.stderr)
        return 1
    print(f"Medición guardada en {args.salida}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

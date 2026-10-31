"""Pruebas de los ajustes que deben conservar el comportamiento actual."""

import sys
import subprocess
from pathlib import Path

from main import load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_settings_preserve_current_runtime_values() -> None:
    settings = load_settings()

    assert settings.whisper_model_id == "whisper-base"
    assert settings.camera_frames_per_second == 3
    assert settings.detection_interval_seconds == 2
    assert settings.announcement_interval_seconds == 5
    assert settings.yolo_confidence_threshold == 0.25
    assert settings.command_similarity_threshold == 80


def test_importing_main_does_not_load_opencv_or_ultralytics() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import main, sys; "
            "print(int('cv2' in sys.modules), int('ultralytics' in sys.modules))",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "0 0"

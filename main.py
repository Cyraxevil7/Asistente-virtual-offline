"""Punto de entrada: inicia solo la escucha y abre visión por orden de voz."""

import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Event

from clases.contratos import DetectionListener
from clases.controlador_voz import (
    PiperSpeechOutput,
    SpeechOutput,
    VoiceAssistant,
    WhisperCppCommandRecognizer,
)
from clases.catalogo_sistema import SystemEntityCatalog
from clases.comandos_sistema import (
    SYSTEM_OPEN_COMMAND_ID,
    RapidFuzzIntentResolver,
    SystemCommandHandler,
)
from clases.coordinador_vision import VisionCoordinator
from clases.deteccion import DetectionEvent
from clases.ejecutor_sistema_linux import LinuxSystemActionExecutor
from clases.enrutador_comandos import RapidFuzzCommandMatcher
from clases.entrada_teclado import PushToTalkKeyboard
from clases.gestor_modelos import (
    DEFAULT_MANIFEST_PATH,
    ModelDownloadError,
    ModelManager,
    ProgressCallback,
)


PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "ajustes.json"
VOICE_COMMANDS_PATH = PROJECT_ROOT / "config" / "voice_commands.json"
WHISPER_SERVER_ENV = "ASISTENTE_WHISPER_SERVER"
WHISPER_SERVER_CANDIDATES = (
    PROJECT_ROOT / "vendor" / "whisper.cpp" / "build" / "bin" / "whisper-server",
    PROJECT_ROOT
    / "modelos"
    / "ggml-org-whisper.cpp-d2a764c"
    / "build"
    / "bin"
    / "whisper-server",
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Ajustes de ejecución centralizados en config/ajustes.json."""

    whisper_model_id: str
    camera_frames_per_second: float
    detection_interval_seconds: float
    announcement_interval_seconds: float
    yolo_confidence_threshold: float
    command_similarity_threshold: int


def load_settings(path: str | Path = SETTINGS_PATH) -> AppSettings:
    """Lee ajustes y rechaza valores inválidos en vez de ocultar errores."""
    settings_path = Path(path)
    try:
        with settings_path.open(encoding="utf-8") as settings_file:
            data = json.load(settings_file)
    except json.JSONDecodeError as error:
        raise ValueError(f"El archivo de ajustes no contiene JSON válido: {settings_path}") from error

    expected_keys = {
        "whisper_model_id",
        "camera_frames_per_second",
        "detection_interval_seconds",
        "announcement_interval_seconds",
        "yolo_confidence_threshold",
        "command_similarity_threshold",
    }
    if not isinstance(data, dict) or set(data) != expected_keys:
        raise ValueError(f"El archivo de ajustes debe contener: {sorted(expected_keys)}.")
    if not isinstance(data["whisper_model_id"], str) or data[
        "whisper_model_id"
    ] not in {"whisper-base", "whisper-tiny"}:
        raise ValueError("'whisper_model_id' debe ser whisper-base o whisper-tiny.")

    positive_keys = (
        "camera_frames_per_second",
        "detection_interval_seconds",
        "announcement_interval_seconds",
    )
    for key in positive_keys:
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"'{key}' debe ser un número mayor que cero.")
    confidence = data["yolo_confidence_threshold"]
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("'yolo_confidence_threshold' debe estar entre 0 y 1.")
    similarity = data["command_similarity_threshold"]
    if (
        isinstance(similarity, bool)
        or not isinstance(similarity, int)
        or not 0 <= similarity <= 100
    ):
        raise ValueError("'command_similarity_threshold' debe ser un entero entre 0 y 100.")

    return AppSettings(
        whisper_model_id=data["whisper_model_id"],
        camera_frames_per_second=float(data["camera_frames_per_second"]),
        detection_interval_seconds=float(data["detection_interval_seconds"]),
        announcement_interval_seconds=float(data["announcement_interval_seconds"]),
        yolo_confidence_threshold=float(confidence),
        command_similarity_threshold=similarity,
    )


def _system_speak(text: str) -> bool:
    """Usa un sintetizador español opcional antes de cargar la voz Piper."""
    executable = shutil.which("espeak-ng") or shutil.which("espeak")
    if executable is None:
        return False
    try:
        subprocess.run(
            [executable, "-v", "es", text],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        LOGGER.exception("No se pudo usar el sintetizador de sistema opcional.")
        return False
    return True


def _system_progress(label: str) -> ProgressCallback:
    """Anuncia el progreso inicial con el sintetizador de sistema opcional."""
    last_bucket = 0

    def report(downloaded: int, total: int) -> None:
        nonlocal last_bucket
        percent = min(100, downloaded * 100 // total)
        bucket = percent // 20
        if bucket <= last_bucket:
            return
        last_bucket = bucket
        message = f"Descargando {label}, {percent} por ciento."
        print(f"[modelos] {message}", flush=True)
        _system_speak(message)

    return report


def _piper_progress(speech_output: SpeechOutput, label: str) -> ProgressCallback:
    """Anuncia por Piper el progreso posterior a preparar la voz española."""
    last_bucket = 0

    def report(downloaded: int, total: int) -> None:
        nonlocal last_bucket
        percent = min(100, downloaded * 100 // total)
        bucket = percent // 20
        if bucket <= last_bucket:
            return
        last_bucket = bucket
        speech_output.speak(f"Descargando {label}, {percent} por ciento.")

    return report


def _ensure_model(
    manager: ModelManager,
    model_id: str,
    on_progress: ProgressCallback | None = None,
) -> Path:
    if manager.is_ready(model_id):
        return manager.path(model_id)
    return manager.ensure(model_id, on_progress=on_progress)


def _prepare_models(manager: ModelManager, settings: AppSettings) -> SpeechOutput:
    """Prepara primero Piper y después los modelos requeridos, anunciando progreso."""
    try:
        voice_path = _ensure_model(
            manager,
            "piper-es-voz",
            _system_progress("la voz española"),
        )
        _ensure_model(
            manager,
            "piper-es-voz-config",
        )
    except ModelDownloadError as error:
        message = f"No se pudo preparar la voz de Piper: {error}"
        print(f"[modelos:error] {message}", file=sys.stderr, flush=True)
        _system_speak(message)
        raise

    speech_output = PiperSpeechOutput(voice_path)
    speech_output.speak("La voz está lista. Voy a preparar los modelos necesarios.")
    whisper_label = (
        "Whisper base"
        if settings.whisper_model_id == "whisper-base"
        else "Whisper tiny"
    )
    labels = (
        (settings.whisper_model_id, whisper_label),
        ("yolo11n", "YOLO11 nano"),
    )
    try:
        for model_id, label in labels:
            path = _ensure_model(
                manager,
                model_id,
                _piper_progress(speech_output, label),
            )
            print(f"[modelos] {label} listo: {path}", flush=True)
    except ModelDownloadError as error:
        message = f"No se pudo preparar un modelo requerido: {error}"
        print(f"[modelos:error] {message}", file=sys.stderr, flush=True)
        speech_output.speak(message)
        raise
    return speech_output


def _resolve_whisper_server() -> Path:
    """Prioriza la ruta configurada, luego vendor/ y el build local anterior."""
    configured_path = os.environ.get(WHISPER_SERVER_ENV)
    if configured_path:
        return Path(configured_path).expanduser()
    for candidate in WHISPER_SERVER_CANDIDATES:
        if candidate.is_file():
            return candidate
    return WHISPER_SERVER_CANDIDATES[0]


class ConsoleDetectionLogger(DetectionListener):
    """Ejemplo de consumidor que registra eventos como JSON en consola."""

    def on_detection(self, event: DetectionEvent) -> None:
        print(json.dumps(event.to_dict(), ensure_ascii=False))


def main() -> None:
    """Espera órdenes de teclado/voz y crea cámara/YOLO bajo demanda."""
    settings = load_settings()
    manager = ModelManager(DEFAULT_MANIFEST_PATH)
    speech_output = _prepare_models(manager, settings)
    whisper_server = _resolve_whisper_server()
    if not whisper_server.is_file():
        message = (
            f"No se encontró whisper-server en {whisper_server}. "
            "Construye el servidor con: bash scripts/construir_whisper.sh"
        )
        print(f"[voz:error] {message}", file=sys.stderr, flush=True)
        speech_output.speak(message)
        raise FileNotFoundError(message)

    camera_commands: Queue[str] = Queue()
    camera_stop_event = Event()

    def on_camera_command(command: str) -> None:
        if command == "close":
            camera_stop_event.set()
        camera_commands.put(command)

    command_matcher = RapidFuzzCommandMatcher(
        VOICE_COMMANDS_PATH,
        similarity_threshold=settings.command_similarity_threshold,
    )
    system_catalog = SystemEntityCatalog()
    system_resolver = RapidFuzzIntentResolver(
        system_catalog, command_matcher=command_matcher
    )
    system_command_handler = SystemCommandHandler(
        system_resolver,
        LinuxSystemActionExecutor(system_catalog),
        speech_output,
    )

    voice_assistant = VoiceAssistant(
        recognizer=WhisperCppCommandRecognizer(
            model_path=manager.path(settings.whisper_model_id),
            whisper_server=whisper_server,
        ),
        speech_output=speech_output,
        on_camera_command=on_camera_command,
        announcement_interval=settings.announcement_interval_seconds,
        command_phrases_path=VOICE_COMMANDS_PATH,
        command_matcher=command_matcher,
        intent_resolver=system_resolver,
        system_command_handler=system_command_handler.handle,
        system_command_ids=frozenset({SYSTEM_OPEN_COMMAND_ID}),
    )

    push_to_talk = PushToTalkKeyboard(
        on_press=voice_assistant.start_recording,
        on_release=voice_assistant.stop_recording,
    )
    try:
        voice_assistant.start()
        push_to_talk.start()
        print("Listo. Mantén pulsada «v» para hablar y suéltala para transcribir.", flush=True)
        while True:
            try:
                command = camera_commands.get(timeout=0.1)
            except Empty:
                continue
            if command != "open":
                continue

            camera_stop_event.clear()
            print("Activando cámara y detección local...", flush=True)
            voice_assistant.set_camera_active(True)
            try:
                from clases.controlador_modelo import YOLOModelController
                from clases.manejo_video import OpenCVCamera
                from clases.pantalla import OpenCVDisplay

                detector = YOLOModelController(
                    manager.path("yolo11n"),
                    confidence_threshold=settings.yolo_confidence_threshold,
                )
                camera = OpenCVCamera(
                    frames_per_second=settings.camera_frames_per_second
                )
                coordinator = VisionCoordinator(
                    video_source=camera,
                    detector=detector,
                    display=OpenCVDisplay(),
                    detection_interval=settings.detection_interval_seconds,
                    listeners=(ConsoleDetectionLogger(), voice_assistant),
                )
                coordinator.run(stop_event=camera_stop_event)
            finally:
                camera_stop_event.clear()
                voice_assistant.set_camera_active(False)
            print("Cámara cerrada; mantén pulsada «v» para otra orden.", flush=True)
    finally:
        push_to_talk.stop()
        voice_assistant.stop()


if __name__ == "__main__":
    main()

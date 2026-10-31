"""Punto de entrada: inicia solo la escucha y abre visión por orden de voz."""

import json
from pathlib import Path
from queue import Empty, Queue
from threading import Event

from clases.contratos import DetectionListener
from clases.controlador_modelo import YOLOModelController
from clases.controlador_voz import (
    PiperSpeechOutput,
    VoiceAssistant,
    WhisperCppCommandRecognizer,
)
from clases.coordinador_vision import VisionCoordinator
from clases.deteccion import DetectionEvent
from clases.entrada_teclado import PushToTalkKeyboard
from clases.manejo_video import OpenCVCamera
from clases.pantalla import OpenCVDisplay


PROJECT_ROOT = Path(__file__).resolve().parent
MODEL_PATH = PROJECT_ROOT / "modelos" / "yolo11n.pt"
# Cambia esta ruta para seleccionar otro modelo GGML compatible de whisper.cpp.
WHISPER_MODEL_PATH = PROJECT_ROOT / "modelos" / "ggml-base.bin"
WHISPER_SERVER_PATH = (
    PROJECT_ROOT
    / "modelos"
    / "ggml-org-whisper.cpp-d2a764c"
    / "build"
    / "bin"
    / "whisper-server"
)
PIPER_VOICE_PATH = PROJECT_ROOT / "modelos" / "voces" / "es_ES-sharvard-medium.onnx"
VOICE_COMMANDS_PATH = PROJECT_ROOT / "config" / "voice_commands.json"
CAMERA_FRAMES_PER_SECOND = 3
DETECTION_INTERVAL_SECONDS = 2


class ConsoleDetectionLogger(DetectionListener):
    """Ejemplo de consumidor que registra eventos como JSON en consola."""

    def on_detection(self, event: DetectionEvent) -> None:
        print(json.dumps(event.to_dict(), ensure_ascii=False))


def main() -> None:
    """Espera órdenes de teclado/voz y crea cámara/YOLO bajo demanda."""
    camera_commands: Queue[str] = Queue()
    camera_stop_event = Event()

    def on_camera_command(command: str) -> None:
        if command == "close":
            camera_stop_event.set()
        camera_commands.put(command)

    voice_assistant = VoiceAssistant(
        recognizer=WhisperCppCommandRecognizer(
            model_path=WHISPER_MODEL_PATH,
            whisper_server=WHISPER_SERVER_PATH,
        ),
        speech_output=PiperSpeechOutput(PIPER_VOICE_PATH),
        on_camera_command=on_camera_command,
        announcement_interval=5,
        command_phrases_path=VOICE_COMMANDS_PATH,
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
                detector = YOLOModelController(MODEL_PATH)
                camera = OpenCVCamera(
                    frames_per_second=CAMERA_FRAMES_PER_SECOND
                )
                coordinator = VisionCoordinator(
                    video_source=camera,
                    detector=detector,
                    display=OpenCVDisplay(),
                    detection_interval=DETECTION_INTERVAL_SECONDS,
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

"""Reconocimiento local de comandos y respuesta hablada del asistente."""

import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import wave
from collections.abc import Callable
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Protocol

from clases.contratos import (
    CommandCandidate,
    CommandMatcher,
    DetectionListener,
    IntentResolver,
)
from clases.deteccion import DetectionEvent
from clases.enrutador_comandos import (
    COMMAND_SIMILARITY_THRESHOLD,
    DEFAULT_COMMAND_PHRASES_PATH,
    RapidFuzzCommandMatcher,
    normalize_command_text,
)


LOGGER = logging.getLogger(__name__)

OBJECT_LABELS_ES = {
    "person": "persona",
    "bicycle": "bicicleta",
    "car": "auto",
    "motorcycle": "motocicleta",
    "airplane": "avión",
    "bus": "autobús",
    "train": "tren",
    "truck": "camión",
    "boat": "barco",
    "traffic light": "semáforo",
    "stop sign": "señal de alto",
    "bench": "banco",
    "bird": "pájaro",
    "cat": "gato",
    "dog": "perro",
    "horse": "caballo",
    "sheep": "oveja",
    "cow": "vaca",
    "elephant": "elefante",
    "bear": "oso",
    "zebra": "cebra",
    "giraffe": "jirafa",
    "backpack": "mochila",
    "umbrella": "paraguas",
    "handbag": "bolso",
    "tie": "corbata",
    "suitcase": "maleta",
    "frisbee": "frisbi",
    "skis": "esquís",
    "snowboard": "tabla de snowboard",
    "sports ball": "pelota",
    "kite": "cometa",
    "baseball bat": "bate de béisbol",
    "baseball glove": "guante de béisbol",
    "skateboard": "patineta",
    "surfboard": "tabla de surf",
    "tennis racket": "raqueta de tenis",
    "bottle": "botella",
    "wine glass": "copa",
    "cup": "taza",
    "fork": "tenedor",
    "knife": "cuchillo",
    "spoon": "cuchara",
    "bowl": "tazón",
    "banana": "plátano",
    "apple": "manzana",
    "sandwich": "sándwich",
    "orange": "naranja",
    "broccoli": "brócoli",
    "carrot": "zanahoria",
    "hot dog": "perrito caliente",
    "pizza": "pizza",
    "donut": "dona",
    "cake": "pastel",
    "chair": "silla",
    "couch": "sofá",
    "potted plant": "planta",
    "bed": "cama",
    "dining table": "mesa",
    "toilet": "inodoro",
    "tv": "televisor",
    "laptop": "computadora portátil",
    "mouse": "ratón",
    "remote": "control remoto",
    "keyboard": "teclado",
    "cell phone": "teléfono",
    "microwave": "microondas",
    "oven": "horno",
    "toaster": "tostadora",
    "sink": "lavabo",
    "refrigerator": "refrigerador",
    "book": "libro",
    "clock": "reloj",
    "vase": "florero",
    "scissors": "tijeras",
    "teddy bear": "oso de peluche",
    "hair drier": "secador de pelo",
    "toothbrush": "cepillo de dientes",
}

OPEN_CAMERA_INTENT = "open_camera"
CLOSE_CAMERA_INTENT = "close_camera"
COMMAND_CONFIRMATION_PHRASES = frozenset({"si", "correcto", "exacto", "eso es"})
COMMAND_REJECTION_PHRASES = frozenset({"no", "negativo"})


class CommandRecognizer(Protocol):
    """Captura audio bajo demanda y transcribe cada grabación completa."""

    def start(self) -> None:
        """Inicia los recursos persistentes del reconocedor."""

    def start_recording(self) -> None:
        """Empieza la captura de audio."""

    def stop_recording(self) -> str:
        """Detiene la captura y devuelve su transcripción."""

    def stop(self) -> None:
        """Libera los recursos persistentes del reconocedor."""


class SpeechOutput(Protocol):
    """Convierte una respuesta de texto a voz."""

    def speak(self, text: str) -> None:
        """Reproduce la respuesta hablada."""

    def pause(self) -> None:
        """Interrumpe el audio y evita nuevas reproducciones temporalmente."""

    def resume(self) -> None:
        """Permite reproducir audio después de una pausa temporal."""


class WhisperCppCommandRecognizer:
    """Captura audio ALSA mientras se mantiene pulsada la tecla de grabación."""

    def __init__(
        self,
        model_path: str | Path,
        whisper_server: str | Path,
        arecord_executable: str = "arecord",
        host: str = "127.0.0.1",
        port: int = 8080,
    ) -> None:
        self._model_path = Path(model_path)
        self._whisper_server = self._resolve_executable(str(whisper_server))
        self._arecord = self._resolve_executable(arecord_executable)
        if not self._model_path.is_file():
            raise FileNotFoundError(f"No se encontró el modelo Whisper: {self._model_path}")
        self._host = host
        self._port = port
        self._health_url = f"http://{host}:{port}/health"
        self._inference_url = f"http://{host}:{port}/inference"
        self._server_process: subprocess.Popen[bytes] | None = None
        self._recording_process: subprocess.Popen[bytes] | None = None
        self._recording_reader: threading.Thread | None = None
        self._recorded_audio = bytearray()
        self._recording_lock = threading.Lock()

    @staticmethod
    def _resolve_executable(executable: str) -> str:
        resolved = shutil.which(executable)
        if resolved is None:
            raise FileNotFoundError(f"No se encontró el ejecutable requerido: {executable}")
        return resolved

    def start(self) -> None:
        """Carga el modelo una sola vez y espera a que el servidor esté listo."""
        if self._server_process is not None and self._server_process.poll() is None:
            return
        self._server_process = subprocess.Popen(
            [
                self._whisper_server,
                "--model",
                str(self._model_path),
                "--host",
                self._host,
                "--port",
                str(self._port),
                "--no-gpu",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if self._server_process.poll() is not None:
                self._server_process = None
                raise RuntimeError("El servidor local de Whisper terminó durante el inicio.")
            try:
                with urllib.request.urlopen(self._health_url, timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, urllib.error.URLError):
                time.sleep(0.2)
        self.stop()
        raise TimeoutError("Whisper no estuvo listo después de 60 segundos.")

    def stop(self) -> None:
        """Cierra el servidor local iniciado por este reconocedor."""
        if self._recording_process is not None:
            self._stop_capture(require_audio=False)
        process = self._server_process
        self._server_process = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def start_recording(self) -> None:
        """Inicia arecord en PCM crudo, listo para guardarse como WAV al soltar la tecla."""
        if self._recording_process is not None:
            raise RuntimeError("Ya hay una grabación de voz en curso.")
        if self._server_process is None or self._server_process.poll() is not None:
            raise RuntimeError("El servidor local de Whisper no está iniciado.")

        process = subprocess.Popen(
            [
                self._arecord,
                "--quiet",
                "--format",
                "S16_LE",
                "--channels",
                "1",
                "--rate",
                "16000",
                "--file-type",
                "raw",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=None,
        )
        if process.stdout is None:
            process.terminate()
            process.wait()
            raise RuntimeError("No se pudo abrir el flujo de audio del micrófono.")

        with self._recording_lock:
            self._recorded_audio.clear()
            self._recording_process = process
            self._recording_reader = threading.Thread(
                target=self._read_audio_stream,
                args=(process,),
                name="captura-microfono",
                daemon=True,
            )
            self._recording_reader.start()
        time.sleep(0.1)
        if process.poll() is not None:
            self._stop_capture(require_audio=False)
            raise RuntimeError("arecord terminó al intentar abrir el micrófono.")

    def _read_audio_stream(self, process: subprocess.Popen[bytes]) -> None:
        """Drena el pipe de arecord mientras la grabación está activa."""
        if process.stdout is None:
            return
        while chunk := process.stdout.read(4096):
            with self._recording_lock:
                self._recorded_audio.extend(chunk)

    def _stop_capture(self, require_audio: bool = True) -> bytes:
        """Detiene arecord y devuelve todos los bytes PCM capturados."""
        with self._recording_lock:
            process = self._recording_process
            reader = self._recording_reader
            self._recording_process = None
            self._recording_reader = None
        if process is None:
            raise RuntimeError("No hay ninguna grabación de voz en curso.")

        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        if reader is not None:
            reader.join(timeout=5)
            if reader.is_alive():
                raise TimeoutError("El flujo del micrófono no se cerró a tiempo.")
        if process.stdout is not None:
            process.stdout.close()
        with self._recording_lock:
            audio = bytes(self._recorded_audio)
            self._recorded_audio.clear()
        if require_audio and len(audio) < 2:
            raise ValueError("La grabación no contiene audio suficiente para transcribir.")
        return audio

    def stop_recording(self) -> str:
        """Finaliza la captura y envía el WAV completo al servidor Whisper."""
        audio = self._stop_capture()
        with tempfile.TemporaryDirectory(prefix="asistente-voz-") as temporary_directory:
            audio_path = Path(temporary_directory) / "comando.wav"
            with wave.open(str(audio_path), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(audio)
            boundary = "----AsistenteWhisperBoundary"
            audio = audio_path.read_bytes()
            body = (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="comando.wav"\r\n'
                "Content-Type: audio/wav\r\n\r\n"
            ).encode() + audio + b"\r\n" + (
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="language"\r\n\r\n'
                "es\r\n"
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="response_format"\r\n\r\n'
                "json\r\n"
                f"--{boundary}--\r\n"
            ).encode()
            request = urllib.request.Request(
                self._inference_url,
                data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.loads(response.read().decode("utf-8"))
        return str(result.get("text", "")).strip()


class PiperSpeechOutput:
    """Sintetiza respuestas en español con Piper y las reproduce con ALSA."""

    def __init__(
        self,
        model_path: str | Path,
        aplay_executable: str = "aplay",
    ) -> None:
        """Carga una vez el modelo local de Piper para reutilizarlo."""
        from piper import PiperVoice

        self._model_path = Path(model_path)
        if not self._model_path.is_file():
            raise FileNotFoundError(f"No se encontró la voz Piper: {self._model_path}")
        self._voice = PiperVoice.load(self._model_path)
        resolved = shutil.which(aplay_executable)
        if resolved is None:
            raise FileNotFoundError(
                f"No se encontró el reproductor de audio: {aplay_executable}"
            )
        self._executable = resolved
        self._playback_lock = threading.Lock()
        self._playback_process: subprocess.Popen[str] | None = None
        self._playback_paused = False
        self._playback_generation = 0

    def speak(self, text: str) -> None:
        """Genera un WAV temporal y lo reproduce si la salida no está pausada."""
        if text.strip():
            with self._playback_lock:
                if self._playback_paused:
                    return
                generation = self._playback_generation
            with tempfile.TemporaryDirectory(
                prefix="asistente-piper-"
            ) as temporary_directory:
                audio_path = Path(temporary_directory) / "respuesta.wav"
                with wave.open(str(audio_path), "wb") as wav_file:
                    self._voice.synthesize_wav(text, wav_file)
                with self._playback_lock:
                    if (
                        self._playback_paused
                        or generation != self._playback_generation
                    ):
                        return
                    process = subprocess.Popen(
                        [self._executable, "-q", str(audio_path)],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    self._playback_process = process
                try:
                    stdout, stderr = process.communicate()
                    with self._playback_lock:
                        was_interrupted = (
                            generation != self._playback_generation
                        )
                    if process.returncode and not was_interrupted:
                        raise subprocess.CalledProcessError(
                            process.returncode,
                            process.args,
                            output=stdout,
                            stderr=stderr,
                        )
                finally:
                    with self._playback_lock:
                        if self._playback_process is process:
                            self._playback_process = None

    def pause(self) -> None:
        """Detiene el reproductor actual e invalida audio aún en síntesis."""
        with self._playback_lock:
            self._playback_paused = True
            self._playback_generation += 1
            process = self._playback_process
        if process is not None and process.poll() is None:
            process.terminate()

    def resume(self) -> None:
        """Reanuda la salida de voz para las respuestas posteriores."""
        with self._playback_lock:
            self._playback_paused = False


class VoiceAssistant(DetectionListener):
    """Enruta transcripciones a órdenes de cámara y del sistema."""

    def __init__(
        self,
        recognizer: CommandRecognizer,
        speech_output: SpeechOutput,
        on_camera_command: Callable[[str], None] | None = None,
        announcement_interval: float = 5,
        command_phrases_path: str | Path = DEFAULT_COMMAND_PHRASES_PATH,
        command_handlers: Mapping[str, Callable[[], None]] | None = None,
        command_matcher: CommandMatcher | None = None,
        intent_resolver: IntentResolver | None = None,
        system_command_handler: Callable[[str], bool] | None = None,
        system_command_ids: frozenset[str] = frozenset(),
    ) -> None:
        """Inyecta el matcher de cámara y los componentes opcionales del sistema.

        Las órdenes de cámara conservan CommandMatcher. El manejador de sistema
        recibe primero cada transcripción y decide si le corresponde procesarla.
        Los identificadores gestionados por esa capa no necesitan un handler
        directo en VoiceAssistant.
        """
        if announcement_interval <= 0:
            raise ValueError("El intervalo de anuncios debe ser mayor que cero.")
        self._command_matcher = command_matcher or RapidFuzzCommandMatcher(
            command_phrases_path,
            similarity_threshold=COMMAND_SIMILARITY_THRESHOLD,
        )
        self._intent_resolver = intent_resolver
        self._system_command_handler = system_command_handler
        parameterized_ids = getattr(
            self._command_matcher, "parameterized_command_ids", frozenset()
        )
        self._system_command_ids = (
            system_command_ids
            or parameterized_ids
        )
        unknown_system_ids = (
            self._system_command_ids - self._command_matcher.command_ids
        )
        if unknown_system_ids:
            raise ValueError(
                "Hay identificadores de órdenes del sistema que no existen "
                f"en la configuración: {sorted(unknown_system_ids)}"
            )
        self._routed_command_ids = (
            self._command_matcher.command_ids - self._system_command_ids
        )
        self._recognizer = recognizer
        self._speech_output = speech_output
        self._on_camera_command = on_camera_command
        self._command_handlers = dict(command_handlers or {})
        if on_camera_command is not None:
            self._command_handlers.setdefault(
                OPEN_CAMERA_INTENT, lambda: on_camera_command("open")
            )
            self._command_handlers.setdefault(
                CLOSE_CAMERA_INTENT, lambda: on_camera_command("close")
            )
        missing_handlers = (
            self._routed_command_ids
            - self._command_handlers.keys()
        )
        if missing_handlers and (
            command_handlers is not None or on_camera_command is not None
        ):
            raise ValueError(
                f"Faltan acciones para las órdenes configuradas: "
                f"{sorted(missing_handlers)}"
            )
        self._pending_command_candidates: tuple[CommandCandidate, ...] | None = None
        self._announcement_interval = announcement_interval
        self._lock = threading.Lock()
        self._latest_labels: tuple[str, ...] = ()
        self._stop_event = threading.Event()
        self._camera_active = threading.Event()
        self._announcement_wakeup = threading.Event()
        self._announcement_worker: threading.Thread | None = None
        self._recording_lock = threading.Lock()
        self._recording_active = False
        self._transcription_worker: threading.Thread | None = None

    def on_detection(self, event: DetectionEvent) -> None:
        """Actualiza el contexto hablado solo con los nombres de los objetos."""
        labels = tuple(dict.fromkeys(obj.label for obj in event.objects))
        with self._lock:
            self._latest_labels = labels

    def start(self) -> None:
        """Inicia Whisper; el micrófono permanece cerrado hasta pulsar la tecla."""
        self._recognizer.start()
        self._stop_event.clear()

    def stop(self) -> None:
        """Detiene una grabación activa, los anuncios y el servidor Whisper."""
        self._stop_event.set()
        self._announcement_wakeup.set()
        self.set_camera_active(False)
        self.stop_recording()
        worker = self._transcription_worker
        if worker is not None:
            worker.join()
            self._transcription_worker = None
        if self._announcement_worker is not None:
            self._announcement_worker.join()
            self._announcement_worker = None
        self._recognizer.stop()

    def start_recording(self) -> None:
        """Empieza una grabación cuando el usuario pulsa la tecla configurada."""
        with self._recording_lock:
            if self._stop_event.is_set():
                return
            if self._recording_active:
                return
            if (
                self._transcription_worker is not None
                and self._transcription_worker.is_alive()
            ):
                print("[voz] Espera a que termine la transcripción anterior.", flush=True)
                return
            self._speech_output.pause()
            try:
                self._recognizer.start_recording()
            except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError):
                self._speech_output.resume()
                LOGGER.exception("No se pudo iniciar la grabación de voz.")
                print("[voz:error] No se pudo abrir el micrófono.", flush=True)
                return
            self._recording_active = True
            print("[voz] Grabando; suelta la tecla v para transcribir.", flush=True)

    def stop_recording(self) -> None:
        """Detiene la grabación y transcribe en segundo plano al soltar la tecla."""
        with self._recording_lock:
            if not self._recording_active:
                return
            self._recording_active = False
            self._speech_output.resume()
            self._transcription_worker = threading.Thread(
                target=self._transcribe_recording,
                name="transcripcion-voz",
                daemon=True,
            )
            self._transcription_worker.start()

    def _transcribe_recording(self) -> None:
        try:
            transcript = self._recognizer.stop_recording()
            print(
                f"[voz {datetime.now().strftime('%H:%M:%S')}] "
                f"{transcript if transcript else '(sin voz reconocida)'}",
                flush=True,
            )
            self._handle_transcript(transcript)
        except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError):
            LOGGER.exception("No se pudo detener o transcribir la grabación.")
            print("[voz:error] No se pudo transcribir el audio.", flush=True)

    def set_camera_active(self, active: bool) -> None:
        """Activa o pausa los anuncios de detección mientras la cámara está abierta."""
        if active:
            self._camera_active.set()
            if (
                self._announcement_worker is None
                or not self._announcement_worker.is_alive()
            ):
                self._announcement_worker = threading.Thread(
                    target=self._announcement_loop,
                    name="anuncios-vision",
                    daemon=True,
                )
                self._announcement_worker.start()
        else:
            self._camera_active.clear()
        self._announcement_wakeup.set()

    def _handle_transcript(self, transcript: str) -> None:
        """Resuelve órdenes exactas, aproximadas, ambiguas o no reconocidas."""
        if (
            self._system_command_handler is not None
            and self._system_command_handler(transcript)
        ):
            return
        normalized_transcript = normalize_command_text(transcript)
        pending_candidates = self._pending_command_candidates
        if pending_candidates is not None:
            if normalized_transcript in COMMAND_REJECTION_PHRASES:
                self._pending_command_candidates = None
                self._speech_output.speak(
                    "De acuerdo, no ejecutaré esa orden. Dime qué quieres hacer."
                )
                return
            if normalized_transcript in COMMAND_CONFIRMATION_PHRASES:
                if len(pending_candidates) == 1:
                    self._pending_command_candidates = None
                    self._execute_command(pending_candidates[0].command_id)
                else:
                    self._speak_ambiguity_prompt(pending_candidates)
                return

            clarification = self._command_matcher.match(
                transcript,
                allowed_command_ids=frozenset(
                    candidate.command_id for candidate in pending_candidates
                ) & self._routed_command_ids,
            )
            if clarification.candidates:
                if len(clarification.candidates) == 1:
                    candidate = clarification.candidates[0]
                    self._pending_command_candidates = None
                    self._execute_command(candidate.command_id)
                else:
                    self._pending_command_candidates = clarification.candidates
                    self._speak_ambiguity_prompt(clarification.candidates)
                return
            self._pending_command_candidates = None

        match = self._command_matcher.match(
            transcript, allowed_command_ids=self._routed_command_ids
        )
        if not match.candidates:
            self._speak_unknown_command()
            return

        if len(match.candidates) > 1:
            self._pending_command_candidates = match.candidates
            self._speak_ambiguity_prompt(match.candidates)
            return

        candidate = match.candidates[0]
        if candidate.similarity < 100:
            self._pending_command_candidates = (candidate,)
            self._speech_output.speak(
                f"Creo que te refieres a {candidate.description}. "
                "¿Es correcto? Responde «sí» para confirmar o repite la orden."
            )
            return
        self._execute_command(candidate.command_id)

    def _execute_command(self, command_id: str) -> None:
        if command_id == OPEN_CAMERA_INTENT and self._camera_active.is_set():
            self._speech_output.speak(self._current_scene_response())
            return
        handler = self._command_handlers.get(command_id)
        if handler is None:
            raise RuntimeError(f"No hay una acción registrada para '{command_id}'.")
        handler()

    def _speak_ambiguity_prompt(
        self, candidates: tuple[CommandCandidate, ...]
    ) -> None:
        descriptions = tuple(dict.fromkeys(candidate.description for candidate in candidates))
        options = " o ".join(descriptions)
        self._speech_output.speak(
            f"No estoy seguro de la orden. ¿Quieres {options}? "
            "Por favor, di una de esas opciones con más claridad."
        )

    def _speak_unknown_command(self) -> None:
        descriptions = tuple(
            description
            for command_id, description in self._command_matcher.command_descriptions.items()
            if command_id in self._routed_command_ids
            or self._system_command_handler is not None
            and command_id in self._system_command_ids
        )
        available_commands = " o ".join(descriptions)
        self._speech_output.speak(
            f"No encontré un comando parecido. Puedes probar: {available_commands}."
        )

    def _announcement_loop(self) -> None:
        """Repite la última escena cada intervalo mientras la cámara siga abierta."""
        while not self._stop_event.is_set():
            if not self._camera_active.is_set():
                self._announcement_wakeup.wait()
                self._announcement_wakeup.clear()
                continue
            self._announcement_wakeup.clear()
            if self._announcement_wakeup.wait(timeout=self._announcement_interval):
                continue
            if self._camera_active.is_set() and not self._stop_event.is_set():
                try:
                    self._speech_output.speak(self._current_scene_response())
                except (OSError, RuntimeError, subprocess.CalledProcessError):
                    LOGGER.exception("No se pudo reproducir el anuncio de detección.")
                    self._stop_event.set()

    def _current_scene_response(self) -> str:
        """Construye la respuesta a partir de la última detección recibida."""
        with self._lock:
            labels = self._latest_labels
        if not labels:
            return "No detecto objetos en este momento."

        translated_labels = tuple(
            dict.fromkeys(OBJECT_LABELS_ES.get(label.lower(), label) for label in labels)
        )
        return f"Delante tienes: {', '.join(translated_labels)}."

    def response_for(self, transcript: str) -> str | None:
        """Responde solo a preguntas sobre lo que detecta la cámara."""
        match = self._command_matcher.match(transcript)
        if (
            not match.candidates
            or match.candidates[0].command_id != OPEN_CAMERA_INTENT
        ):
            return None
        return self._current_scene_response()

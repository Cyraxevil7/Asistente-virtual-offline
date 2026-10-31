"""Pruebas del flujo de voz sin micrófono ni sintetizador físico."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clases.controlador_voz import (
    PiperSpeechOutput,
    VoiceAssistant,
    WhisperCppCommandRecognizer,
)
from clases.contratos import IntentResult
from clases.deteccion import BoundingBox, DetectedObject, DetectionEvent
from clases.entrada_teclado import PushToTalkKeyboard


class FakeRecognizer:
    def __init__(self) -> None:
        self.recording = False
        self.started = False

    def start(self) -> None:
        self.started = True

    def start_recording(self) -> None:
        self.recording = True

    def stop_recording(self) -> str:
        self.recording = False
        return "prueba de transcripción"

    def stop(self) -> None:
        pass


class FakeSpeechOutput:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def speak(self, text: str) -> None:
        self.messages.append(text)


class FakeIntentResolver:
    def resolve(self, text: str) -> IntentResult:
        return IntentResult("unresolved", {"text": text}, 0.0)


def make_event(*labels: str) -> DetectionEvent:
    return DetectionEvent(
        timestamp=datetime.now(timezone.utc),
        frame_width=640,
        frame_height=480,
        objects=tuple(
            DetectedObject(
                label,
                0.99,
                bounding_box=BoundingBox(1, 2, 30, 40),
            )
            for label in labels
        ),
    )


class VoiceAssistantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.speech_output = FakeSpeechOutput()
        self.assistant = VoiceAssistant(FakeRecognizer(), self.speech_output)

    def test_answers_with_only_unique_object_names(self) -> None:
        self.assistant.on_detection(make_event("bus", "person", "bus"))

        response = self.assistant.response_for("¿Qué tengo delante?")

        self.assertEqual(response, "Delante tienes: autobús, persona.")
        self.assertNotIn("0.99", response)
        self.assertNotIn("640", response)

    def test_says_when_no_objects_were_detected(self) -> None:
        self.assistant.on_detection(make_event())

        response = self.assistant.response_for("¿Qué detectas?")

        self.assertEqual(response, "No detecto objetos en este momento.")

    def test_ignores_unrelated_transcription(self) -> None:
        self.assistant.on_detection(make_event("cat"))

        self.assertIsNone(self.assistant.response_for("Abre el navegador."))

    def test_transcribes_only_after_recording_is_released(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assistant.start()
            self.assistant.start_recording()
            self.assertTrue(self.assistant._recognizer.recording)
            self.assistant.stop_recording()
            worker = self.assistant._transcription_worker
            self.assertIsNotNone(worker)
            worker.join(timeout=1)
            self.assistant.stop()

        self.assertFalse(self.assistant._recognizer.recording)
        self.assertIn("Grabando", output.getvalue())
        self.assertIn("prueba de transcripción", output.getvalue())

    def test_voice_commands_open_and_close_the_camera(self) -> None:
        commands: list[str] = []
        assistant = VoiceAssistant(
            FakeRecognizer(),
            self.speech_output,
            on_camera_command=commands.append,
        )

        assistant._handle_transcript("¿Qué ves?")
        assistant._handle_transcript("Cerrar cámara")

        self.assertEqual(commands, ["open", "close"])
        self.assertEqual(self.speech_output.messages, [])

    def test_injected_intent_resolver_does_not_change_default_command_routing(self) -> None:
        commands: list[str] = []
        resolver = FakeIntentResolver()
        assistant = VoiceAssistant(
            FakeRecognizer(),
            self.speech_output,
            on_camera_command=commands.append,
            intent_resolver=resolver,
        )

        assistant._handle_transcript("¿Qué ves?")

        self.assertIs(assistant._intent_resolver, resolver)
        self.assertEqual(commands, ["open"])

    def test_keeps_the_existing_transcription_workaround_phrase(self) -> None:
        commands: list[str] = []
        assistant = VoiceAssistant(
            FakeRecognizer(),
            self.speech_output,
            on_camera_command=commands.append,
        )

        assistant._handle_transcript("de ten la cámara")

        self.assertEqual(commands, ["close"])

    def test_approximate_match_asks_for_confirmation_then_executes(self) -> None:
        commands: list[str] = []
        assistant = VoiceAssistant(
            FakeRecognizer(),
            self.speech_output,
            on_camera_command=commands.append,
        )

        assistant._handle_transcript("que ve")

        self.assertEqual(commands, [])
        self.assertIn("Creo que te refieres a abrir la cámara", self.speech_output.messages[-1])
        self.assertIn("Responde «sí»", self.speech_output.messages[-1])

        assistant._handle_transcript("sí")

        self.assertEqual(commands, ["open"])

    def test_ambiguous_match_asks_for_clarification_before_execution(self) -> None:
        commands: list[str] = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "voice_commands.json"
            config_path.write_text(
                json.dumps(
                    {
                        "open_camera": {
                            "description": "abrir la cámara",
                            "phrases": ["abrir camara"],
                        },
                        "close_camera": {
                            "description": "cerrar la cámara",
                            "phrases": ["cerrar camara"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            assistant = VoiceAssistant(
                FakeRecognizer(),
                self.speech_output,
                on_camera_command=commands.append,
                command_phrases_path=config_path,
            )

        assistant._handle_transcript("camara")

        self.assertEqual(commands, [])
        self.assertIn("abrir la cámara o cerrar la cámara", self.speech_output.messages[-1])

        assistant._handle_transcript("abrir camara")

        self.assertEqual(commands, ["open"])

    def test_unrecognized_command_suggests_available_actions(self) -> None:
        commands: list[str] = []
        assistant = VoiceAssistant(
            FakeRecognizer(),
            self.speech_output,
            on_camera_command=commands.append,
        )

        assistant._handle_transcript("hola como estas")

        self.assertEqual(commands, [])
        self.assertIn("No encontré un comando parecido", self.speech_output.messages[-1])
        self.assertIn("abrir la cámara", self.speech_output.messages[-1])

    def test_loads_editable_phrases_from_custom_json(self) -> None:
        commands: list[str] = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "voice_commands.json"
            config_path.write_text(
                json.dumps(
                    {
                        "open_camera": {
                            "description": "abrir la vista",
                            "phrases": ["activa la vista"],
                        },
                        "close_camera": {
                            "description": "cerrar la vista",
                            "phrases": ["termina la vista"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            assistant = VoiceAssistant(
                FakeRecognizer(),
                self.speech_output,
                on_camera_command=commands.append,
                command_phrases_path=config_path,
            )

        assistant._handle_transcript("Activa la vista")
        assistant._handle_transcript("Termina la vista")

        self.assertEqual(commands, ["open", "close"])

    def test_custom_command_uses_its_registered_handler(self) -> None:
        actions: list[str] = []
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "voice_commands.json"
            config_path.write_text(
                json.dumps(
                    {
                        "greet": {
                            "description": "saludar",
                            "phrases": ["saluda"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            assistant = VoiceAssistant(
                FakeRecognizer(),
                self.speech_output,
                command_phrases_path=config_path,
                command_handlers={"greet": lambda: actions.append("greet")},
            )

        assistant._handle_transcript("saluda")

        self.assertEqual(actions, ["greet"])

    def test_rejects_invalid_command_phrase_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            config_path = Path(temporary_directory) / "voice_commands.json"
            config_path.write_text('{"open_camera": []}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "description.*phrases"):
                VoiceAssistant(
                    FakeRecognizer(),
                    self.speech_output,
                    command_phrases_path=config_path,
                )

    def test_query_while_camera_is_open_does_not_queue_another_open(self) -> None:
        commands: list[str] = []
        assistant = VoiceAssistant(
            FakeRecognizer(),
            self.speech_output,
            on_camera_command=commands.append,
        )
        assistant.on_detection(make_event("bus"))
        assistant._camera_active.set()

        assistant._handle_transcript("¿Qué ves?")

        self.assertEqual(commands, [])
        self.assertEqual(self.speech_output.messages, ["Delante tienes: autobús."])

    def test_camera_announces_latest_detection_every_five_seconds(self) -> None:
        announced = threading.Event()

        class RecordingSpeechOutput:
            def speak(self, text: str) -> None:
                if text == "Delante tienes: autobús.":
                    announced.set()

        assistant = VoiceAssistant(
            FakeRecognizer(),
            RecordingSpeechOutput(),
            announcement_interval=0.01,
        )
        assistant.on_detection(make_event("bus"))
        assistant.set_camera_active(True)
        try:
            self.assertTrue(announced.wait(timeout=1))
        finally:
            assistant.stop()


class WhisperCppRecognizerTests(unittest.TestCase):
    def test_records_until_stopped_and_transcribes_wav_through_server(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "ggml-tiny.bin"
            model_path.write_bytes(b"test model")
            uploaded_requests = []
            raw_audio = b"\0\0" * 100

            class FakeProcess:
                def __init__(self, *_: object, **kwargs: object) -> None:
                    self.parameters = kwargs
                    self.stdout = BytesIO(raw_audio)
                    self.returncode = None

                def poll(self) -> int | None:
                    return self.returncode

                def terminate(self) -> None:
                    self.returncode = 0

                def wait(self, **_: object) -> int:
                    self.returncode = 0
                    return 0

            class FakeResponse:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_: object) -> None:
                    pass

                def read(self) -> bytes:
                    return b'{"text":" \xc2\xbfQu\xc3\xa9 tengo delante? \\n"}'

            def open_url(request, **_: object) -> FakeResponse:
                uploaded_requests.append(request)
                return FakeResponse()

            with (
                patch(
                    "clases.controlador_voz.shutil.which",
                    side_effect=lambda executable: {
                        "/tools/whisper-server": "/tools/whisper-server",
                        "arecord": "/usr/bin/arecord",
                    }.get(executable),
                ),
                patch(
                    "clases.controlador_voz.subprocess.Popen",
                    side_effect=FakeProcess,
                ) as popen,
                patch("clases.controlador_voz.urllib.request.urlopen", side_effect=open_url),
            ):
                recognizer = WhisperCppCommandRecognizer(
                    model_path=model_path,
                    whisper_server="/tools/whisper-server",
                    arecord_executable="arecord",
                )
                recognizer._server_process = FakeProcess()
                recognizer.start_recording()
                transcript = recognizer.stop_recording()

        self.assertEqual(transcript, "¿Qué tengo delante?")
        self.assertEqual(uploaded_requests[0].full_url, "http://127.0.0.1:8080/inference")
        self.assertIn(b'name="language"\r\n\r\nes', uploaded_requests[0].data)
        self.assertIn(b'name="response_format"\r\n\r\njson', uploaded_requests[0].data)
        self.assertIn(b"RIFF", uploaded_requests[0].data)
        self.assertIn(b"\0\0" * 100, uploaded_requests[0].data)
        self.assertNotIn("--duration", popen.call_args.args[0])
        self.assertEqual(popen.call_args.kwargs["stdout"], -1)
        self.assertIsNone(popen.call_args.kwargs["stderr"])


class PushToTalkKeyboardTests(unittest.TestCase):
    def test_records_on_press_and_transcribes_on_release_once(self) -> None:
        actions: list[str] = []
        keyboard = PushToTalkKeyboard(
            on_press=lambda: actions.append("start"),
            on_release=lambda: actions.append("stop"),
        )
        voice_key = SimpleNamespace(char="v")
        other_key = SimpleNamespace(char="x")

        keyboard._handle_key_press(voice_key)
        keyboard._handle_key_press(voice_key)
        keyboard._handle_key_press(other_key)
        keyboard._handle_key_release(other_key)
        keyboard._handle_key_release(voice_key)
        keyboard._handle_key_release(voice_key)

        self.assertEqual(actions, ["start", "stop"])


class PiperSpeechOutputTests(unittest.TestCase):
    def test_synthesizes_and_plays_using_piper_voice(self) -> None:
        from piper import PiperVoice

        def write_test_wav(text: str, wav_file: wave.Wave_write) -> None:
            self.assertEqual(text, "Delante tienes: autobús.")
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(b"\0\0")

        fake_voice = SimpleNamespace(synthesize_wav=write_test_wav)
        with tempfile.TemporaryDirectory() as temporary_directory:
            model_path = Path(temporary_directory) / "spanish.onnx"
            model_path.write_bytes(b"test voice")
            with (
                patch.object(PiperVoice, "load", return_value=fake_voice) as load_voice,
                patch(
                    "clases.controlador_voz.shutil.which",
                    return_value="/usr/bin/aplay",
                ),
                patch("clases.controlador_voz.subprocess.run") as run,
            ):
                output = PiperSpeechOutput(model_path)
                output.speak("Delante tienes: autobús.")

        load_voice.assert_called_once_with(model_path)
        self.assertTrue(run.call_args.kwargs["check"])
        self.assertEqual(run.call_args.args[0][:2], ["/usr/bin/aplay", "-q"])


if __name__ == "__main__":
    unittest.main()

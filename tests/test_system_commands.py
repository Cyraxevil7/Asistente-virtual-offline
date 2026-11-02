"""Pruebas del intérprete local y el ejecutor seguro de comandos del sistema."""

import json
from pathlib import Path
from unittest.mock import patch

from clases.catalogo_sistema import SystemEntityCatalog
from clases.comandos_sistema import (
    ConversationState,
    RapidFuzzIntentResolver,
    SystemCommandHandler,
)
from clases.controlador_voz import VoiceAssistant
from clases.ejecutor_sistema_linux import LinuxSystemActionExecutor


class RecordingSpeechOutput:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def speak(self, text: str) -> None:
        self.messages.append(text)

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass


class RecordingExecutor:
    def __init__(self) -> None:
        self.opened_folders: list[str] = []
        self.launched_applications: list[str] = []

    def open_folder(self, entity_id: str) -> None:
        self.opened_folders.append(entity_id)

    def launch_application(self, entity_id: str) -> None:
        self.launched_applications.append(entity_id)


def build_system(
    tmp_path: Path,
    *,
    clock=lambda: 0.0,
    subfolders: dict[str, list[str]] | None = None,
    symlinks: dict[str, dict[str, Path]] | None = None,
):
    home = tmp_path / "home"
    home.mkdir()
    downloads = home / "Bajadas"
    documents = home / "Documents"
    downloads.mkdir()
    documents.mkdir()
    root_directories = {
        "downloads": downloads,
        "documents": documents,
        "pictures": home / "Pictures",
        "videos": home / "Videos",
        "desktop": home / "Desktop",
        "music": home / "Music",
    }
    for root_directory in root_directories.values():
        root_directory.mkdir(exist_ok=True)
    for root_id, folder_names in (subfolders or {}).items():
        for folder_name in folder_names:
            (root_directories[root_id] / folder_name).mkdir(parents=True)
    for root_id, links in (symlinks or {}).items():
        for link_name, target in links.items():
            (root_directories[root_id] / link_name).symlink_to(
                target, target_is_directory=True
            )
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    xdg_config = home / ".config"
    xdg_config.mkdir()
    (xdg_config / "user-dirs.dirs").write_text(
        'XDG_DOWNLOAD_DIR="$HOME/Bajadas"\n'
        'XDG_DOCUMENTS_DIR="$HOME/Documents"\n',
        encoding="utf-8",
    )
    applications_directory = tmp_path / "data" / "applications"
    applications_directory.mkdir(parents=True)
    (applications_directory / "firefox.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Firefox\n"
        "Exec=/usr/bin/true %U\n",
        encoding="utf-8",
    )
    (applications_directory / "firefox-esr.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Firefox ESR\n"
        "Exec=/usr/bin/true\n",
        encoding="utf-8",
    )
    (applications_directory / "hidden.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Hidden application\n"
        "NoDisplay=true\n"
        "Exec=/usr/bin/true\n",
        encoding="utf-8",
    )
    (applications_directory / "xterm.desktop").write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=XTerm\n"
        "Exec=/usr/bin/true\n",
        encoding="utf-8",
    )
    folders_path = config_directory / "folders.json"
    folders_path.write_text(
        json.dumps(
            {
                "version": 1,
                "folders": [
                    {
                        "id": "downloads",
                        "name": "Descargas",
                        "xdg_user_dir": "DOWNLOAD",
                        "fallback_path": "Downloads",
                        "aliases": ["downloads", "download"],
                    },
                    {
                        "id": "documents",
                        "name": "Documentos",
                        "xdg_user_dir": "DOCUMENTS",
                        "fallback_path": "Documents",
                        "aliases": ["documents"],
                    },
                    {
                        "id": "pictures",
                        "name": "Imágenes",
                        "xdg_user_dir": "PICTURES",
                        "fallback_path": "Pictures",
                        "aliases": ["imagenes", "fotos"],
                    },
                    {
                        "id": "videos",
                        "name": "Vídeos",
                        "xdg_user_dir": "VIDEOS",
                        "fallback_path": "Videos",
                        "aliases": ["videos"],
                    },
                    {
                        "id": "desktop",
                        "name": "Escritorio",
                        "xdg_user_dir": "DESKTOP",
                        "fallback_path": "Desktop",
                        "aliases": ["escritorio"],
                    },
                    {
                        "id": "music",
                        "name": "Música",
                        "xdg_user_dir": "MUSIC",
                        "fallback_path": "Music",
                        "aliases": ["musica"],
                    },
                    {
                        "id": "missing",
                        "name": "Inexistente",
                        "path": str(home / "No existe"),
                        "aliases": ["inexistente"],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    applications_path = config_directory / "applications.json"
    applications_path.write_text(
        json.dumps(
            {
                "version": 1,
                "applications": [
                    {
                        "desktop_ids": [
                            "firefox.desktop",
                            "firefox-esr.desktop",
                        ],
                        "aliases": ["navegador"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    catalog = SystemEntityCatalog(
        folders_path,
        applications_path,
        home=home,
        data_directories=(tmp_path / "data",),
    )
    resolver = RapidFuzzIntentResolver(catalog)
    speech = RecordingSpeechOutput()
    executor = RecordingExecutor()
    handler = SystemCommandHandler(resolver, executor, speech, clock=clock)
    return catalog, resolver, speech, executor, handler


def test_direct_open_folder_resolves_and_executes(tmp_path: Path) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)

    result = resolver.resolve("Abre Descargas")

    assert result.intent_id == "open"
    assert result.entity_type == "folder"
    assert result.entity_id == "downloads"
    assert result.status == "complete"
    assert 0 <= result.confidence <= 100
    assert handler.handle("Abre Descargas")
    assert executor.opened_folders == ["downloads"]
    assert speech.messages == ["Abriendo Descargas."]


def test_complete_folder_sentence_does_not_ask_for_extra_information(
    tmp_path: Path,
) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)

    result = resolver.resolve("Quiero abrir la carpeta de documentos")

    assert result.status == "complete"
    assert result.entity_type == "folder"
    assert result.entity_id == "documents"
    handler.handle("Quiero abrir la carpeta de documentos")
    assert executor.opened_folders == ["documents"]
    assert speech.messages == ["Abriendo Documentos."]


def test_incomplete_folder_command_continues_with_target(tmp_path: Path) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)

    result = resolver.resolve("Quiero abrir una carpeta")
    assert result.intent_id == "open"
    assert result.status == "incomplete"
    assert result.state == ConversationState.WAITING_TARGET

    assert handler.handle("Quiero abrir una carpeta")
    assert handler.context.state == ConversationState.WAITING_TARGET
    assert speech.messages[-1] == "¿Qué carpeta quieres abrir?"

    assert handler.handle("Documentos")
    assert executor.opened_folders == ["documents"]
    assert handler.context.state == ConversationState.WAITING_ORDER


def test_typo_resolves_only_a_high_similarity_authorized_target(
    tmp_path: Path,
) -> None:
    _, resolver, _, executor, handler = build_system(tmp_path)

    result = resolver.resolve("Abre Descargaz")

    assert result.status == "complete"
    assert result.entity_id == "downloads"
    handler.handle("Abre Descargaz")
    assert executor.opened_folders == ["downloads"]


def test_ambiguous_application_alias_waits_for_number_selection(
    tmp_path: Path,
) -> None:
    _, _, speech, executor, handler = build_system(tmp_path)

    assert handler.handle("Abre navegador")
    assert handler.context.state == ConversationState.WAITING_SELECTION
    assert "Opción primera: aplicación Firefox." in speech.messages[-1]
    assert "Opción segunda: aplicación Firefox ESR." in speech.messages[-1]
    assert executor.launched_applications == []

    assert handler.handle("segunda")
    assert executor.launched_applications == ["firefox-esr.desktop"]
    assert handler.context.state == ConversationState.WAITING_ORDER


def test_ambiguous_application_can_be_selected_by_name(tmp_path: Path) -> None:
    _, _, _, executor, handler = build_system(tmp_path)
    handler.handle("Abre navegador")

    assert handler.handle("Firefox ESR")

    assert executor.launched_applications == ["firefox-esr.desktop"]


def test_selection_accepts_spoken_ordinal_with_option_word(tmp_path: Path) -> None:
    _, _, _, executor, handler = build_system(tmp_path)
    handler.handle("Abre navegador")

    assert handler.handle("segunda opción")

    assert executor.launched_applications == ["firefox-esr.desktop"]


def test_direct_application_order_and_numeric_option_selection(
    tmp_path: Path,
) -> None:
    _, _, _, executor, handler = build_system(tmp_path)

    assert handler.handle("Ejecuta Firefox")
    assert executor.launched_applications == ["firefox.desktop"]

    handler.handle("Abre navegador")
    assert handler.handle("2")

    assert executor.launched_applications == [
        "firefox.desktop",
        "firefox-esr.desktop",
    ]


def test_cancel_clears_pending_operation_without_execution(tmp_path: Path) -> None:
    _, _, speech, executor, handler = build_system(tmp_path)
    handler.handle("Quiero abrir una carpeta")

    assert handler.handle("Cancelar")

    assert handler.context.state == ConversationState.WAITING_ORDER
    assert executor.opened_folders == []
    assert speech.messages[-1] == "De acuerdo, cancelé la operación."


def test_known_but_missing_folder_is_reported_without_execution(
    tmp_path: Path,
) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)
    result = resolver.resolve("Abre Inexistente")

    assert result.status == "unavailable"
    assert handler.handle("Abre Inexistente")
    assert "no existe o no está disponible" in speech.messages[-1]
    assert executor.opened_folders == []


def test_subfolders_in_the_five_authorized_roots_are_resolvable_and_openable(
    tmp_path: Path,
) -> None:
    root_ids = ("pictures", "documents", "videos", "desktop", "downloads")
    subfolders = {root_id: [f"Subcarpeta {root_id}"] for root_id in root_ids}
    catalog, resolver, _, executor, handler = build_system(
        tmp_path, subfolders=subfolders
    )

    for root_id in root_ids:
        folder_name = f"Subcarpeta {root_id}"
        result = resolver.resolve(f"Abre {folder_name}")
        assert result.status == "complete"
        assert result.entity_type == "folder"
        assert result.entity_id == f"subfolder:{root_id}:{folder_name}"
        assert catalog.get("folder", result.entity_id).parent_folder_id == root_id
        assert handler.handle(f"Abre {folder_name}")

    assert executor.opened_folders == [
        f"subfolder:{root_id}:Subcarpeta {root_id}" for root_id in root_ids
    ]


def test_subfolders_outside_authorized_roots_are_not_discovered(
    tmp_path: Path,
) -> None:
    _, resolver, _, _, _ = build_system(
        tmp_path,
        subfolders={"music": ["Privado"], "downloads": ["Permitido"]},
    )

    assert resolver.resolve("Abre Privado").status == "not_found"
    assert resolver.resolve("Abre Permitido").status == "complete"


def test_subfolder_index_is_shallow_and_does_not_follow_symlinks(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    _, resolver, _, _, _ = build_system(
        tmp_path,
        subfolders={"downloads": ["Proyecto/Interno"]},
        symlinks={"downloads": {"Acceso externo": outside}},
    )

    assert resolver.resolve("Abre Proyecto").status == "complete"
    assert resolver.resolve("Abre Interno").status == "not_found"
    assert resolver.resolve("Abre Acceso externo").status == "not_found"


def test_executor_rejects_subfolder_replaced_by_symlink_outside_its_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    catalog, _, _, _, _ = build_system(
        tmp_path,
        subfolders={"downloads": ["Temporal"]},
    )
    resource = catalog.get("folder", "subfolder:downloads:Temporal")
    assert resource.path is not None
    resource.path.rmdir()
    resource.path.symlink_to(outside, target_is_directory=True)
    executor = LinuxSystemActionExecutor(catalog)

    with patch("clases.ejecutor_sistema_linux.subprocess.Popen") as popen:
        try:
            executor.open_folder(resource.entity_id)
        except FileNotFoundError as error:
            assert "raíz autorizada" in str(error)
        else:
            raise AssertionError("El ejecutor aceptó un enlace fuera de la raíz.")

    popen.assert_not_called()


def test_unknown_folder_and_shell_like_transcription_are_rejected(
    tmp_path: Path,
) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)

    assert resolver.resolve("Abre carpeta no registrada").status == "not_found"
    assert resolver.resolve("Abre ../../etc; rm -rf /").status == "rejected"
    assert resolver.resolve("Ejecuta XTerm -e rm -rf /").status == "rejected"
    assert handler.handle("Abre ../../etc; rm -rf /")
    assert "No acepto rutas ni argumentos" in speech.messages[-1]
    assert executor.opened_folders == []
    assert executor.launched_applications == []


def test_uninstalled_application_is_reported_without_execution(
    tmp_path: Path,
) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)

    assert resolver.resolve("Ejecuta aplicación que no existe").status == "not_found"
    assert handler.handle("Ejecuta aplicación que no existe")

    assert "No encontré" in speech.messages[-1]
    assert executor.launched_applications == []


def test_pending_context_expires_and_cannot_reuse_old_target(tmp_path: Path) -> None:
    current_time = [10.0]
    _, _, speech, executor, handler = build_system(
        tmp_path, clock=lambda: current_time[0]
    )
    handler.handle("Quiero abrir una carpeta")
    current_time[0] += 31

    assert handler.handle("Descargas")

    assert executor.opened_folders == []
    assert handler.context.state == ConversationState.WAITING_ORDER
    assert "venció" in speech.messages[-1]


def test_existing_camera_command_remains_available(tmp_path: Path) -> None:
    _, resolver, speech, executor, handler = build_system(tmp_path)
    camera_commands: list[str] = []

    class FakeRecognizer:
        def start(self) -> None:
            pass

        def start_recording(self) -> None:
            pass

        def stop_recording(self) -> str:
            return ""

        def stop(self) -> None:
            pass

    assistant = VoiceAssistant(
        FakeRecognizer(),
        speech,
        on_camera_command=camera_commands.append,
        system_command_handler=handler.handle,
    )
    assistant._handle_transcript("¿Qué ves?")
    assistant._handle_transcript("Abrir cámara")
    assistant._handle_transcript("Abre Descargas")
    assistant._handle_transcript("abrir")
    assistant._handle_transcript("hola como estas")

    assert camera_commands == ["open", "open", "open"]
    assert executor.opened_folders == ["downloads"]
    assert resolver.resolve("Abre la cámara").status == "legacy_camera"
    assert "abrir una carpeta o aplicación" in speech.messages[-1]


def test_open_variants_are_configured_in_voice_commands_not_intents() -> None:
    config_directory = Path(__file__).resolve().parents[1] / "config"
    voice_commands = json.loads(
        (config_directory / "voice_commands.json").read_text(encoding="utf-8")
    )
    system_intents = json.loads(
        (config_directory / "intenciones_sistema.json").read_text(encoding="utf-8")
    )

    assert "quiero abrir una carpeta" in voice_commands["open_resource"]["phrases"]
    assert "folder" in voice_commands["open_resource"]["entity_type_phrases"]["folder"]
    assert "phrases" not in system_intents
    assert "cancel_phrases" in system_intents


def test_linux_executor_uses_catalog_argv_without_shell_interpolation(
    tmp_path: Path,
) -> None:
    catalog, _, _, _, _ = build_system(
        tmp_path, subfolders={"downloads": ["Carpeta autorizada"]}
    )
    executor = LinuxSystemActionExecutor(catalog)

    with patch("clases.ejecutor_sistema_linux.subprocess.Popen") as popen:
        executor.launch_application("firefox.desktop")
        executor.open_folder("downloads")
        executor.open_folder("subfolder:downloads:Carpeta autorizada")

    application_args = popen.call_args_list[0].args[0]
    assert application_args == ["/usr/bin/true"]
    assert popen.call_args_list[0].kwargs["start_new_session"] is True
    assert "shell" not in popen.call_args_list[0].kwargs
    folder_args = popen.call_args_list[1].args[0]
    assert folder_args[0].endswith("xdg-open")
    assert folder_args[1] == str(catalog.get("folder", "downloads").path)
    assert "shell" not in popen.call_args_list[1].kwargs
    subfolder_args = popen.call_args_list[2].args[0]
    assert subfolder_args[0].endswith("xdg-open")
    assert subfolder_args[1] == str(
        catalog.get("folder", "subfolder:downloads:Carpeta autorizada").path
    )
    assert "shell" not in popen.call_args_list[2].kwargs


def test_desktop_entries_with_no_display_are_not_discovered(
    tmp_path: Path,
) -> None:
    catalog, _, _, _, _ = build_system(tmp_path)

    candidates = catalog.resolve(
        "Hidden application",
        entity_type="application",
    )

    assert candidates == ()


def test_intent_confidence_is_a_similarity_score_not_a_probability(
    tmp_path: Path,
) -> None:
    _, resolver, _, _, _ = build_system(tmp_path)

    result = resolver.resolve("Abre Descargas")

    assert result.confidence == 90


def test_entity_threshold_is_configurable_in_intent_catalog(
    tmp_path: Path,
) -> None:
    catalog, _, _, _, _ = build_system(tmp_path)
    configuration_path = (
        Path(__file__).resolve().parents[1]
        / "config"
        / "intenciones_sistema.json"
    )
    configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
    configuration["entity_similarity_threshold"] = 95
    custom_configuration = tmp_path / "intenciones.json"
    custom_configuration.write_text(json.dumps(configuration), encoding="utf-8")
    strict_resolver = RapidFuzzIntentResolver(
        catalog,
        configuration_path=custom_configuration,
    )

    assert strict_resolver.resolve("Abre Descargaz").status == "not_found"
    assert strict_resolver.resolve("Abre Descargas").status == "complete"

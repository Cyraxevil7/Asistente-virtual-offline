"""Catálogos locales y resolución de carpetas/aplicaciones autorizadas."""

from __future__ import annotations

import configparser
import json
import logging
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rapidfuzz import fuzz

from clases.contratos import IntentCandidate
from clases.enrutador_comandos import normalize_command_text


LOGGER = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FOLDERS_PATH = PROJECT_ROOT / "config" / "carpetas.json"
DEFAULT_APPLICATIONS_PATH = PROJECT_ROOT / "config" / "aplicaciones.json"
DEFAULT_XDG_DATA_DIRS = (Path("/usr/local/share"), Path("/usr/share"))
_XDG_DIRECTORY_FALLBACKS = {
    "DESKTOP": "Desktop",
    "DOCUMENTS": "Documents",
    "DOWNLOAD": "Downloads",
    "MUSIC": "Music",
    "PICTURES": "Pictures",
    "VIDEOS": "Videos",
    "PUBLICSHARE": "Public",
    "TEMPLATES": "Templates",
}
_DESKTOP_FILE_CODES = {"%f", "%F", "%u", "%U"}
_FIELD_CODE_PATTERN = re.compile(r"%[A-Za-z]")
_SUBFOLDER_ROOT_IDS = frozenset(
    {"pictures", "documents", "videos", "desktop", "downloads"}
)


@dataclass(frozen=True, slots=True)
class SystemResource:
    """Recurso descubierto en un catálogo local, nunca derivado como comando.

    Las carpetas hijas indican la raíz autorizada para poder validar su ruta
    tanto al resolver la voz como inmediatamente antes de abrirlas.
    """

    entity_id: str
    entity_type: str
    name: str
    aliases: tuple[str, ...]
    available: bool
    path: Path | None = None
    desktop_file: Path | None = None
    launch_arguments: tuple[str, ...] = ()
    parent_folder_id: str | None = None


class SystemEntityCatalog:
    """Carga una vez las carpetas autorizadas y aplicaciones XDG disponibles."""

    def __init__(
        self,
        folders_path: str | Path = DEFAULT_FOLDERS_PATH,
        applications_path: str | Path = DEFAULT_APPLICATIONS_PATH,
        *,
        home: Path | None = None,
        data_directories: Iterable[Path] | None = None,
    ) -> None:
        self._home = (home or Path.home()).expanduser().resolve()
        self._resources: dict[tuple[str, str], SystemResource] = {}
        self._resources_by_type: dict[str, list[SystemResource]] = {
            "folder": [],
            "application": [],
        }
        self._load_folders(Path(folders_path))
        application_aliases = _load_application_aliases(Path(applications_path))
        self._load_applications(data_directories, application_aliases)

    def resolve(
        self,
        query: str,
        *,
        entity_type: str | None = None,
        allowed_resources: frozenset[tuple[str, str]] | None = None,
        similarity_threshold: int = 84,
        ambiguity_margin: int = 5,
        max_candidates: int = 3,
    ) -> tuple[IntentCandidate, ...]:
        """Compara solo el catálogo ya cargado y devuelve opciones ordenadas."""
        normalized_query = normalize_command_text(query)
        if not normalized_query:
            return ()
        if entity_type is not None and entity_type not in self._resources_by_type:
            raise ValueError(f"Tipo de recurso no admitido: {entity_type}")

        resources = (
            self._resources_by_type[entity_type]
            if entity_type is not None
            else [
                resource
                for typed_resources in self._resources_by_type.values()
                for resource in typed_resources
            ]
        )
        scored: list[IntentCandidate] = []
        for resource in resources:
            if (
                allowed_resources is not None
                and (resource.entity_type, resource.entity_id) not in allowed_resources
            ):
                continue
            aliases = (resource.name, *resource.aliases)
            score = max(
                (
                    fuzz.ratio(normalized_query, normalize_command_text(alias))
                    for alias in aliases
                ),
                default=0,
            )
            if score >= similarity_threshold:
                available = (
                    self.is_authorized_folder(resource)
                    if resource.entity_type == "folder"
                    else resource.available
                )
                scored.append(
                    IntentCandidate(
                        entity_id=resource.entity_id,
                        entity_type=resource.entity_type,
                        label=resource.name,
                        similarity=float(score),
                        available=available,
                    )
                )
        ranked = sorted(
            scored,
            key=lambda candidate: (
                -candidate.similarity,
                normalize_command_text(candidate.label),
                candidate.entity_type,
                candidate.entity_id,
            ),
        )
        if not ranked:
            return ()
        best_score = ranked[0].similarity
        return tuple(
            candidate
            for candidate in ranked
            if best_score - candidate.similarity <= ambiguity_margin
        )[:max_candidates]

    def get(self, entity_type: str, entity_id: str) -> SystemResource:
        """Devuelve exclusivamente recursos del catálogo ya validado."""
        try:
            return self._resources[(entity_type, entity_id)]
        except KeyError as error:
            raise KeyError(
                f"El recurso '{entity_id}' no está registrado como '{entity_type}'."
            ) from error

    def _load_folders(self, path: Path) -> None:
        configuration = _load_json(path, "catálogo de carpetas")
        if (
            not isinstance(configuration, dict)
            or set(configuration) != {"version", "folders"}
            or configuration["version"] != 1
            or not isinstance(configuration["folders"], list)
        ):
            raise ValueError(f"Formato inválido en el catálogo de carpetas: {path}")

        user_directories = _load_xdg_user_directories(self._home)
        seen_ids: set[str] = set()
        for definition in configuration["folders"]:
            if not isinstance(definition, dict):
                raise ValueError(f"Entrada de carpeta inválida en {path}")
            entity_id = _required_text(definition, "id", path)
            name = _required_text(definition, "name", path)
            aliases = _load_aliases(definition, path)
            if entity_id in seen_ids:
                raise ValueError(f"ID de carpeta duplicado '{entity_id}' en {path}")
            seen_ids.add(entity_id)

            has_path = "path" in definition
            has_xdg = "xdg_user_dir" in definition
            if has_path == has_xdg:
                raise ValueError(
                    f"La carpeta '{entity_id}' debe definir exactamente "
                    "'path' o 'xdg_user_dir'."
                )
            if has_path:
                raw_path = definition["path"]
                if not isinstance(raw_path, str) or not raw_path.strip():
                    raise ValueError(f"La ruta de '{entity_id}' debe ser texto no vacío.")
                folder_path = Path(raw_path).expanduser()
                if not folder_path.is_absolute():
                    raise ValueError(f"La ruta de '{entity_id}' debe ser absoluta.")
                folder_path = folder_path.resolve()
            else:
                xdg_id = definition["xdg_user_dir"]
                fallback = definition.get("fallback_path")
                if not isinstance(xdg_id, str) or xdg_id not in _XDG_DIRECTORY_FALLBACKS:
                    raise ValueError(f"XDG user dir inválido en '{entity_id}'.")
                if (
                    not isinstance(fallback, str)
                    or not fallback
                    or Path(fallback).is_absolute()
                    or ".." in Path(fallback).parts
                ):
                    raise ValueError(
                        f"'fallback_path' debe ser relativo y seguro en '{entity_id}'."
                    )
                folder_path = user_directories.get(
                    xdg_id, self._home / fallback
                ).expanduser().resolve()

            self._add_resource(
                SystemResource(
                    entity_id=entity_id,
                    entity_type="folder",
                    name=name,
                    aliases=aliases,
                    available=folder_path.is_dir(),
                    path=folder_path,
                )
            )
        self._discover_root_subfolders()

    def _load_applications(
        self,
        data_directories: Iterable[Path] | None,
        configured_aliases: dict[str, tuple[str, ...]],
    ) -> None:
        directories = (
            tuple(Path(directory).expanduser() for directory in data_directories)
            if data_directories is not None
            else _application_data_directories()
        )
        discovered: dict[str, SystemResource] = {}
        for data_directory in directories:
            applications_directory = data_directory / "applications"
            if not applications_directory.is_dir():
                continue
            for desktop_file in sorted(applications_directory.rglob("*.desktop")):
                if not desktop_file.is_file():
                    continue
                desktop_id = desktop_file.relative_to(
                    applications_directory
                ).as_posix().replace("/", "-")
                if desktop_id in discovered:
                    continue
                resource = _read_desktop_application(
                    desktop_file,
                    desktop_id,
                    configured_aliases.get(desktop_id, ()),
                )
                if resource is not None:
                    discovered[desktop_id] = resource
        for resource in discovered.values():
            self._add_resource(resource)

    def _add_resource(self, resource: SystemResource) -> None:
        key = (resource.entity_type, resource.entity_id)
        if key in self._resources:
            raise ValueError(
                f"ID de recurso duplicado '{resource.entity_id}' "
                f"para '{resource.entity_type}'."
            )
        self._resources[key] = resource
        self._resources_by_type[resource.entity_type].append(resource)

    def is_authorized_folder(self, resource: SystemResource) -> bool:
        """Comprueba existencia y pertenencia a raíz justo antes de abrir."""
        if (
            resource.entity_type != "folder"
            or resource.path is None
            or resource.path.is_symlink()
            or not resource.path.is_dir()
        ):
            return False
        if resource.parent_folder_id is None:
            return True
        if resource.parent_folder_id not in _SUBFOLDER_ROOT_IDS:
            return False
        try:
            root = self.get("folder", resource.parent_folder_id)
        except KeyError:
            return False
        if (
            root.path is None
            or root.path.is_symlink()
            or not root.path.is_dir()
        ):
            return False
        try:
            return (
                resource.path.resolve(strict=True).parent
                == root.path.resolve(strict=True)
            )
        except (OSError, RuntimeError):
            return False

    def _discover_root_subfolders(self) -> None:
        """Indexa una vez los hijos directos de las cinco raíces autorizadas."""
        for root_id in sorted(_SUBFOLDER_ROOT_IDS):
            root = self._resources.get(("folder", root_id))
            if root is None or root.path is None or not root.path.is_dir():
                continue
            try:
                # Mantener el índice superficial evita escanear grandes árboles.
                children = sorted(root.path.iterdir(), key=lambda path: path.name.casefold())
                for child in children:
                    if (
                        child.name.startswith(".")
                        or child.is_symlink()
                        or not child.is_dir()
                    ):
                        continue
                    self._add_resource(
                        SystemResource(
                            entity_id=f"subfolder:{root_id}:{child.name}",
                            entity_type="folder",
                            name=f"{child.name} (dentro de {root.name})",
                            aliases=(child.name,),
                            available=True,
                            path=child,
                            parent_folder_id=root_id,
                        )
                    )
            except OSError:
                LOGGER.warning(
                    "No se pudieron indexar subcarpetas de la raíz %s (%s).",
                    root.name,
                    root.path,
                    exc_info=True,
                )


def _load_json(path: Path, description: str) -> object:
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSON inválido en {description}: {path}") from error


def _required_text(definition: dict[str, object], key: str, path: Path) -> str:
    value = definition.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{key}' debe ser texto no vacío en {path}")
    return value.strip()


def _load_aliases(definition: dict[str, object], path: Path) -> tuple[str, ...]:
    aliases = definition.get("aliases", [])
    if not isinstance(aliases, list) or any(
        not isinstance(alias, str) or not alias.strip() for alias in aliases
    ):
        raise ValueError(f"'aliases' debe ser una lista de textos en {path}")
    return tuple(alias.strip() for alias in aliases)


def _load_application_aliases(path: Path) -> dict[str, tuple[str, ...]]:
    configuration = _load_json(path, "catálogo de aplicaciones")
    if (
        not isinstance(configuration, dict)
        or set(configuration) != {"version", "applications"}
        or configuration["version"] != 1
        or not isinstance(configuration["applications"], list)
    ):
        raise ValueError(f"Formato inválido en el catálogo de aplicaciones: {path}")

    aliases_by_desktop_id: dict[str, list[str]] = {}
    for definition in configuration["applications"]:
        if not isinstance(definition, dict):
            raise ValueError(f"Entrada de aplicación inválida en {path}")
        desktop_ids = definition.get("desktop_ids")
        aliases = _load_aliases(definition, path)
        if (
            not isinstance(desktop_ids, list)
            or not desktop_ids
            or any(
                not isinstance(desktop_id, str)
                or not desktop_id.endswith(".desktop")
                or "/" in desktop_id
                for desktop_id in desktop_ids
            )
        ):
            raise ValueError(f"'desktop_ids' inválido en {path}")
        for desktop_id in desktop_ids:
            aliases_by_desktop_id.setdefault(desktop_id, []).extend(aliases)
    return {
        desktop_id: tuple(dict.fromkeys(aliases))
        for desktop_id, aliases in aliases_by_desktop_id.items()
    }


def _application_data_directories() -> tuple[Path, ...]:
    home = Path.home()
    raw_data_home = os.environ.get("XDG_DATA_HOME")
    data_home = Path(
        raw_data_home if raw_data_home else home / ".local" / "share"
    ).expanduser()
    raw_data_dirs = os.environ.get("XDG_DATA_DIRS")
    data_dirs = (
        tuple(Path(value) for value in raw_data_dirs.split(":") if value)
        if raw_data_dirs
        else DEFAULT_XDG_DATA_DIRS
    )
    if not data_home.is_absolute() or any(not directory.is_absolute() for directory in data_dirs):
        raise ValueError("XDG_DATA_HOME y XDG_DATA_DIRS deben contener rutas absolutas.")
    return (data_home, *data_dirs)


def _load_xdg_user_directories(home: Path) -> dict[str, Path]:
    fallback_paths = {
        directory_id: home / relative_path
        for directory_id, relative_path in _XDG_DIRECTORY_FALLBACKS.items()
    }
    raw_config_home = os.environ.get("XDG_CONFIG_HOME")
    config_home = Path(
        raw_config_home if raw_config_home else home / ".config"
    ).expanduser()
    if not config_home.is_absolute():
        raise ValueError("XDG_CONFIG_HOME debe contener una ruta absoluta.")
    user_dirs_file = config_home / "user-dirs.dirs"
    if not user_dirs_file.is_file():
        return fallback_paths

    pattern = re.compile(r'^\s*XDG_([A-Z]+)_DIR\s*=\s*"((?:\\.|[^"])*)"\s*$')
    with user_dirs_file.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            match = pattern.match(line)
            if match is None:
                raise ValueError(
                    f"Formato no admitido en {user_dirs_file}, línea {line_number}."
                )
            directory_id, raw_value = match.groups()
            if directory_id not in fallback_paths:
                continue
            value = raw_value.replace(r"\"", '"').replace(r"\\", "\\")
            if value.startswith("$HOME/"):
                user_path = home / value[len("$HOME/") :]
            elif value.startswith("${HOME}/"):
                user_path = home / value[len("${HOME}/") :]
            elif value == "$HOME" or value == "${HOME}":
                user_path = home
            elif value.startswith("/"):
                user_path = Path(value)
            else:
                raise ValueError(
                    f"Ruta XDG no segura en {user_dirs_file}, línea {line_number}."
                )
            fallback_paths[directory_id] = user_path.resolve()
    return fallback_paths


def _read_desktop_application(
    desktop_file: Path,
    desktop_id: str,
    aliases: tuple[str, ...],
) -> SystemResource | None:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        with desktop_file.open(encoding="utf-8") as file:
            parser.read_file(file)
        entry = parser["Desktop Entry"]
        if entry.get("Type") != "Application":
            return None
        if entry.getboolean("Hidden", fallback=False) or entry.getboolean(
            "NoDisplay", fallback=False
        ):
            return None
        name = _localized_name(entry)
        if not name:
            return None
        try_exec = entry.get("TryExec")
        if try_exec and not _executable_exists(try_exec):
            return None
        executable_arguments = _expand_desktop_exec(
            entry.get("Exec", ""),
            name=name,
            desktop_file=desktop_file,
            icon=entry.get("Icon"),
        )
        if not executable_arguments or not _executable_exists(executable_arguments[0]):
            return None
    except (OSError, KeyError, configparser.Error, ValueError) as error:
        LOGGER.warning("Se omite entrada .desktop inválida %s: %s", desktop_file, error)
        return None

    desktop_aliases = tuple(
        dict.fromkeys((desktop_id.removesuffix(".desktop"), *aliases))
    )
    return SystemResource(
        entity_id=desktop_id,
        entity_type="application",
        name=name,
        aliases=desktop_aliases,
        available=True,
        desktop_file=desktop_file,
        launch_arguments=executable_arguments,
    )


def _localized_name(entry: configparser.SectionProxy) -> str:
    language = (
        os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or ""
    ).split(".", maxsplit=1)[0].split("@", maxsplit=1)[0]
    language_tag = language.split("_", maxsplit=1)[0]
    for key in (f"name[{language}]", f"name[{language_tag}]", "name"):
        value = entry.get(key)
        if value and value.strip():
            return value.strip()
    return ""


def _executable_exists(executable: str) -> bool:
    candidate = Path(executable)
    if candidate.is_absolute() or "/" in executable:
        return candidate.is_file() and os.access(candidate, os.X_OK)
    return shutil.which(executable) is not None


def _expand_desktop_exec(
    command: str,
    *,
    name: str,
    desktop_file: Path,
    icon: str | None,
) -> tuple[str, ...]:
    if not command.strip():
        raise ValueError("el campo Exec está vacío")
    expanded: list[str] = []
    for token in shlex.split(command, posix=True):
        if token in _DESKTOP_FILE_CODES:
            continue
        if token == "%i":
            if icon:
                expanded.extend(("--icon", icon))
            continue
        token = token.replace("%%", "\0").replace("%c", name).replace(
            "%k", str(desktop_file)
        )
        if _FIELD_CODE_PATTERN.search(token):
            raise ValueError("el campo Exec contiene un código de archivo no admitido")
        expanded.append(token.replace("\0", "%"))
    return tuple(expanded)

"""Ejecución limitada a recursos presentes en los catálogos del asistente."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from clases.catalogo_sistema import SystemEntityCatalog


class LinuxSystemActionExecutor:
    """Abre carpetas registradas y lanza aplicaciones XDG sin shell."""

    def __init__(
        self,
        catalog: SystemEntityCatalog,
        file_manager_executable: str = "xdg-open",
    ) -> None:
        self._catalog = catalog
        self._file_manager = shutil.which(file_manager_executable)

    def open_folder(self, entity_id: str) -> None:
        """Abre una ruta de carpeta validada desde el catálogo local."""
        resource = self._catalog.get("folder", entity_id)
        if not self._catalog.is_authorized_folder(resource):
            raise FileNotFoundError(
                f"La carpeta autorizada '{resource.name}' ya no está disponible "
                "o dejó de estar dentro de su raíz autorizada."
            )
        if self._file_manager is None:
            raise FileNotFoundError(
                "No se encontró xdg-open para abrir carpetas en este entorno Linux."
            )
        subprocess.Popen(
            [self._file_manager, str(resource.path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def launch_application(self, entity_id: str) -> None:
        """Ejecuta la entrada .desktop registrada, sin interpolar voz en el argv."""
        resource = self._catalog.get("application", entity_id)
        if (
            not resource.available
            or resource.desktop_file is None
            or not resource.desktop_file.is_file()
            or not resource.launch_arguments
            or not _is_executable_available(resource.launch_arguments[0])
        ):
            raise FileNotFoundError(
                f"La aplicación '{resource.name}' ya no está disponible."
            )
        subprocess.Popen(
            list(resource.launch_arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def _is_executable_available(executable: str) -> bool:
    path = Path(executable)
    if path.is_absolute() or "/" in executable:
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(executable) is not None

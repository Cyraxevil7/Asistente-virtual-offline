"""Contratos para desacoplar captura, inferencia, pantalla y consumidores."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from clases.deteccion import DetectionEvent, DetectionResult


class VideoSource(Protocol):
    """Fuente reemplazable de fotogramas."""

    def read(self) -> np.ndarray:
        """Captura y devuelve el siguiente fotograma."""

    def close(self) -> None:
        """Libera los recursos de la fuente de video."""


class ObjectDetector(Protocol):
    """Detector reemplazable que produce datos y una vista anotada."""

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """Analiza un fotograma y devuelve su resultado."""


class DetectionListener(Protocol):
    """Consumidor que recibe una observación para registrarla o procesarla."""

    def on_detection(self, event: DetectionEvent) -> None:
        """Procesa una observación publicada por el coordinador."""


@dataclass(frozen=True, slots=True)
class CommandCandidate:
    """Orden candidata encontrada por el reconocedor aproximado."""

    command_id: str
    description: str
    matched_phrase: str
    similarity: float


@dataclass(frozen=True, slots=True)
class CommandMatch:
    """Resultado de comparación: ninguna, una o varias órdenes candidatas."""

    candidates: tuple[CommandCandidate, ...]


class CommandMatcher(Protocol):
    """Contrato reemplazable para asociar una transcripción con órdenes."""

    @property
    def command_ids(self) -> frozenset[str]:
        """Identificadores de órdenes registrados."""

    @property
    def command_descriptions(self) -> Mapping[str, str]:
        """Descripciones legibles para confirmar o aclarar órdenes."""

    def match(
        self,
        transcript: str,
        allowed_command_ids: frozenset[str] | None = None,
    ) -> CommandMatch:
        """Devuelve candidatas que superen el umbral de similitud."""


class Display(Protocol):
    """Interfaz de visualización intercambiable."""

    def show(self, frame: np.ndarray) -> None:
        """Muestra un fotograma."""

    def should_close(self) -> bool:
        """Indica si el usuario solicitó cerrar la interfaz."""

    def close(self) -> None:
        """Libera los recursos de visualización."""

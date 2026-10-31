"""Tipos inmutables para comunicar detecciones entre componentes."""

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Coordenadas de una caja detectada en píxeles."""

    x1: float
    y1: float
    x2: float
    y2: float

    def to_dict(self) -> dict[str, float]:
        """Devuelve las coordenadas en un formato serializable."""
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


@dataclass(frozen=True, slots=True)
class DetectedObject:
    """Clase, confianza y ubicación de un objeto detectado."""

    label: str
    confidence: float
    bounding_box: BoundingBox

    def to_dict(self) -> dict[str, object]:
        """Devuelve los datos del objeto para registro o transporte."""
        return {
            "label": self.label,
            "confidence": self.confidence,
            "bounding_box": self.bounding_box.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class DetectionEvent:
    """Observación estructurada que se entrega a los consumidores."""

    timestamp: datetime
    frame_width: int
    frame_height: int
    objects: tuple[DetectedObject, ...]

    def to_dict(self) -> dict[str, object]:
        """Convierte la observación a un diccionario serializable como JSON."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "objects": [detected_object.to_dict() for detected_object in self.objects],
        }


@dataclass(frozen=True, slots=True)
class DetectionResult:
    """Evento para consumidores y fotograma anotado para la interfaz visual."""

    event: DetectionEvent
    annotated_frame: np.ndarray

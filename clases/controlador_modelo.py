"""Adaptador del modelo YOLO al contrato de detección del proyecto."""

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from ultralytics import YOLO

from clases.contratos import ObjectDetector
from clases.deteccion import (
    BoundingBox,
    DetectedObject,
    DetectionEvent,
    DetectionResult,
)


class YOLOModelController(ObjectDetector):
    """Carga un modelo local y convierte su salida a tipos del proyecto."""

    def __init__(self, model_path: str | Path, confidence_threshold: float = 0.25) -> None:
        self._model_path = Path(model_path)
        if not self._model_path.is_file():
            raise FileNotFoundError(f"No se encontró el modelo local: {self._model_path}")
        if not 0 <= confidence_threshold <= 1:
            raise ValueError("El umbral de confianza debe estar entre 0 y 1.")

        self._confidence_threshold = confidence_threshold
        self._model = YOLO(str(self._model_path))

    def detect(self, frame: np.ndarray) -> DetectionResult:
        """Ejecuta YOLO y prepara el evento y el fotograma anotado."""
        results = self._model.predict(
            source=frame,
            conf=self._confidence_threshold,
            verbose=False,
        )
        if not results:
            raise RuntimeError("El modelo no devolvió un resultado de detección.")

        result = results[0]
        height, width = frame.shape[:2]
        objects: list[DetectedObject] = []

        if result.boxes is not None:
            boxes = result.boxes
            coordinates = boxes.xyxy.cpu().tolist()
            confidences = boxes.conf.cpu().tolist()
            class_ids = boxes.cls.cpu().tolist()

            for coordinates_for_box, confidence, class_id in zip(
                coordinates, confidences, class_ids, strict=True
            ):
                x1, y1, x2, y2 = coordinates_for_box
                objects.append(
                    DetectedObject(
                        label=result.names[int(class_id)],
                        confidence=float(confidence),
                        bounding_box=BoundingBox(
                            x1=float(x1),
                            y1=float(y1),
                            x2=float(x2),
                            y2=float(y2),
                        ),
                    )
                )

        event = DetectionEvent(
            timestamp=datetime.now(timezone.utc),
            frame_width=width,
            frame_height=height,
            objects=tuple(objects),
        )
        return DetectionResult(event=event, annotated_frame=result.plot())

"""Coordina captura, detección, visualización y publicación de observaciones."""

import time
from collections.abc import Iterable
from threading import Event

from clases.contratos import DetectionListener, Display, ObjectDetector, VideoSource


class VisionCoordinator:
    """Conecta las dependencias de visión sin acoplarlas a una interfaz concreta."""

    def __init__(
        self,
        video_source: VideoSource,
        detector: ObjectDetector,
        display: Display,
        detection_interval: float = 2,
        listeners: Iterable[DetectionListener] = (),
    ) -> None:
        if detection_interval <= 0:
            raise ValueError("El intervalo de detección debe ser mayor que cero.")

        self._video_source = video_source
        self._detector = detector
        self._display = display
        self._detection_interval = detection_interval
        self._listeners = list(listeners)
        self._last_detection_at: float | None = None

    def add_listener(self, listener: DetectionListener) -> None:
        """Suscribe un consumidor, como el futuro módulo de audio."""
        self._listeners.append(listener)

    def run(self, stop_event: Event | None = None) -> None:
        """Ejecuta la visión hasta pulsar q o recibir una orden externa de cierre."""
        last_annotated_frame = None
        try:
            while (
                (stop_event is None or not stop_event.is_set())
                and not self._display.should_close()
            ):
                frame = self._video_source.read()
                now = time.monotonic()

                if (
                    self._last_detection_at is None
                    or now - self._last_detection_at >= self._detection_interval
                ):
                    result = self._detector.detect(frame)
                    self._last_detection_at = time.monotonic()
                    for listener in self._listeners:
                        listener.on_detection(result.event)
                    last_annotated_frame = result.annotated_frame

                self._display.show(last_annotated_frame if last_annotated_frame is not None else frame)
        finally:
            try:
                self._video_source.close()
            finally:
                self._display.close()

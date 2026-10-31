"""Captura local desde una cámara compatible con OpenCV."""

import time

import cv2
import numpy as np


class OpenCVCamera:
    """Fuente de video con límite de tasa de captura por software."""

    def __init__(self, camera_index: int = 0, frames_per_second: float = 3) -> None:
        if frames_per_second <= 0:
            raise ValueError("La tasa de captura debe ser mayor que cero.")

        self._frame_interval = 1 / frames_per_second
        self._last_read_at: float | None = None
        self._capture = cv2.VideoCapture(camera_index)
        self._capture.set(cv2.CAP_PROP_FPS, frames_per_second)

        if not self._capture.isOpened():
            self._capture.release()
            raise RuntimeError(f"No se pudo abrir la cámara con índice {camera_index}.")

    def read(self) -> np.ndarray:
        """Lee un fotograma, esperando si hace falta para respetar la tasa."""
        if self._last_read_at is not None:
            elapsed = time.monotonic() - self._last_read_at
            if elapsed < self._frame_interval:
                time.sleep(self._frame_interval - elapsed)

        success, frame = self._capture.read()
        self._last_read_at = time.monotonic()
        if not success:
            raise RuntimeError("No se pudo leer un fotograma de la cámara.")
        return frame

    def close(self) -> None:
        """Libera la cámara; puede llamarse más de una vez."""
        self._capture.release()

"""Visualización de fotogramas y control de cierre mediante OpenCV."""

import cv2
import numpy as np

from clases.contratos import Display


class OpenCVDisplay(Display):
    """Muestra la cámara en una ventana y permite salir con la tecla q."""

    def __init__(self, window_name: str = "Asistente - deteccion de objetos") -> None:
        self._window_name = window_name
        self._close_requested = False

    def show(self, frame: np.ndarray) -> None:
        """Muestra un fotograma y registra si se pulsó q."""
        cv2.imshow(self._window_name, frame)
        self._close_requested = (cv2.waitKey(1) & 0xFF) == ord("q")

    def should_close(self) -> bool:
        """Devuelve si el usuario solicitó salir."""
        return self._close_requested

    def close(self) -> None:
        """Cierra la ventana de video."""
        cv2.destroyAllWindows()
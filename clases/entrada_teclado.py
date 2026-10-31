"""Entrada de voz por pulsación sostenida de una tecla global."""

import threading
from collections.abc import Callable


class PushToTalkKeyboard:
    """Inicia y detiene una grabación al pulsar y soltar la tecla configurada.

    En Linux, pynput necesita una sesión gráfica compatible con X11 para detectar
    eventos globales de teclado mientras OpenCV está mostrando su propia ventana.
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        key_character: str = "v",
    ) -> None:
        if len(key_character) != 1:
            raise ValueError("La tecla de grabación debe ser un solo carácter.")
        self._on_press_callback = on_press
        self._on_release_callback = on_release
        self._key_character = key_character.casefold()
        self._listener: threading.Thread | None = None
        self._pressed = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Registra un listener global de teclado para detectar pulsación y liberación."""
        from pynput import keyboard

        if self._listener is not None and self._listener.is_alive():
            return
        listener = keyboard.Listener(
            on_press=self._handle_key_press,
            on_release=self._handle_key_release,
        )
        listener.start()
        self._listener = listener

    def stop(self) -> None:
        """Detiene el listener y finaliza una grabación que siga activa."""
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()
            listener.join()
        with self._lock:
            was_pressed = self._pressed
            self._pressed = False
        if was_pressed:
            self._on_release_callback()

    def _handle_key_press(self, key: object) -> None:
        character = getattr(key, "char", None)
        if not isinstance(character, str) or character.casefold() != self._key_character:
            return
        with self._lock:
            if self._pressed:
                return
            self._pressed = True
        self._on_press_callback()

    def _handle_key_release(self, key: object) -> None:
        character = getattr(key, "char", None)
        if not isinstance(character, str) or character.casefold() != self._key_character:
            return
        with self._lock:
            if not self._pressed:
                return
            self._pressed = False
        self._on_release_callback()

"""Motor de automação da sequência de teclas."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from .keyboard_controller import WindowsKeyboardController
from .settings_manager import Settings

LOGGER = logging.getLogger(__name__)


class AutomationEngine:
    """Executa uma sequência em uma única thread de trabalho."""

    def __init__(
        self,
        controller: WindowsKeyboardController,
        settings: Settings,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._controller = controller
        self._settings = settings
        self._on_error = on_error
        self._state_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False
        self._last_error: str | None = None

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    @property
    def last_error(self) -> str | None:
        with self._state_lock:
            return self._last_error

    def set_settings(self, settings: Settings) -> None:
        """Atualiza configurações somente quando o motor está parado."""

        with self._state_lock:
            if self._running:
                raise RuntimeError("Pare a automação antes de alterar as configurações.")
            self._settings = settings
            self._last_error = None

    def start(self) -> bool:
        """Inicia exatamente um ciclo de trabalho; retorna se iniciou agora."""

        with self._state_lock:
            if self._running:
                return False
            self._stop_event.clear()
            self._last_error = None
            self._running = True
            self._thread = threading.Thread(
                target=self._worker,
                name="WASD-AutoToggle",
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception:
                self._running = False
                self._thread = None
                raise
            return True

    def stop(self) -> bool:
        """Solicita parada e aguarda a thread, liberando eventos pendentes."""

        with self._state_lock:
            thread = self._thread
            was_running = self._running
            self._stop_event.set()

        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        try:
            self._controller.release_all()
        finally:
            with self._state_lock:
                if thread is self._thread and (thread is None or not thread.is_alive()):
                    self._thread = None
                    self._running = False
        return was_running

    def toggle(self) -> bool:
        """Alterna o estado e retorna o novo estado."""

        if self.is_running:
            self.stop()
        else:
            self.start()
        return self.is_running

    def close(self) -> None:
        """Encerra o motor de forma idempotente."""

        self.stop()
        self._controller.release_all()

    def _worker(self) -> None:
        index = 0
        try:
            while not self._stop_event.is_set():
                with self._state_lock:
                    settings = self._settings
                key = settings.sequence[index % len(settings.sequence)]
                key_was_pressed = False
                try:
                    self._controller.key_down(key)
                    key_was_pressed = True
                    if self._stop_event.wait(settings.press_duration_ms / 1000.0):
                        break
                finally:
                    if key_was_pressed:
                        self._controller.key_up(key)

                if self._stop_event.wait(settings.interval_ms / 1000.0):
                    break
                index += 1
        except Exception as exc:
            LOGGER.exception("A automação foi interrompida por uma falha")
            with self._state_lock:
                self._last_error = str(exc)
            if self._on_error is not None:
                try:
                    self._on_error(exc)
                except Exception:
                    LOGGER.exception("O callback de erro também falhou")
        finally:
            try:
                self._controller.release_all()
            finally:
                with self._state_lock:
                    self._running = False
                    self._thread = None

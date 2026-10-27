"""Atalho global F6 do WASD Auto Toggle."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from collections.abc import Callable
from ctypes import wintypes


LOGGER = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_F6 = 0x75

# Impede que manter o F6 pressionado gere vários acionamentos.
MOD_NOREPEAT = 0x4000


class GlobalHotkeyError(RuntimeError):
    """Erro ao registrar o atalho global."""


class GlobalHotkeyManager:
    """Registra F6 globalmente usando a API RegisterHotKey do Windows."""

    def __init__(
        self,
        callback: Callable[[], None],
        hotkey_id: int = 0x57415344,
    ) -> None:
        self._callback = callback
        self._hotkey_id = hotkey_id

        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None

        self._ready = threading.Event()
        self._stop_event = threading.Event()

        self._error: Exception | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        """Inicia o monitor global do F6."""

        if os.name != "nt":
            raise GlobalHotkeyError(
                "O atalho global F6 funciona somente no Windows."
            )

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return

            self._ready.clear()
            self._stop_event.clear()
            self._error = None

            self._thread = threading.Thread(
                target=self._message_loop,
                name="WASD-GlobalHotkey-F6",
                daemon=True,
            )

            self._thread.start()

        if not self._ready.wait(timeout=5):
            self.stop()
            raise GlobalHotkeyError(
                "O Windows não respondeu ao registrar o atalho F6."
            )

        if self._error is not None:
            error = self._error
            self.stop()
            raise GlobalHotkeyError(str(error)) from error

    def stop(self) -> None:
        """Para o monitor global e libera o registro do F6."""

        self._stop_event.set()

        thread_id = self._thread_id

        if thread_id is not None and os.name == "nt":
            try:
                user32 = ctypes.WinDLL(
                    "user32",
                    use_last_error=True,
                )

                user32.PostThreadMessageW(
                    wintypes.DWORD(thread_id),
                    WM_QUIT,
                    0,
                    0,
                )
            except Exception:
                LOGGER.exception(
                    "Não foi possível encerrar o loop do atalho F6."
                )

        thread = self._thread

        if (
            thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=5)

        with self._lock:
            if thread is self._thread:
                self._thread = None
                self._thread_id = None

    def _message_loop(self) -> None:
        """Loop de mensagens do Windows executado em thread própria."""

        user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )

        kernel32 = ctypes.WinDLL(
            "kernel32",
            use_last_error=True,
        )

        self._thread_id = kernel32.GetCurrentThreadId()

        registered = False

        try:
            registered = bool(
                user32.RegisterHotKey(
                    None,
                    self._hotkey_id,
                    MOD_NOREPEAT,
                    VK_F6,
                )
            )

            if not registered:
                error_code = ctypes.get_last_error()

                raise GlobalHotkeyError(
                    "Não foi possível registrar o F6 globalmente. "
                    "O atalho pode estar sendo usado por outro programa. "
                    f"Código do Windows: {error_code}."
                )

            self._ready.set()

            message = wintypes.MSG()

            user32.GetMessageW.argtypes = [
                ctypes.POINTER(wintypes.MSG),
                wintypes.HWND,
                wintypes.UINT,
                wintypes.UINT,
            ]

            user32.GetMessageW.restype = ctypes.c_int

            while not self._stop_event.is_set():
                result = user32.GetMessageW(
                    ctypes.byref(message),
                    None,
                    0,
                    0,
                )

                if result == -1:
                    error_code = ctypes.get_last_error()

                    raise GlobalHotkeyError(
                        "Erro no loop global do F6. "
                        f"Código do Windows: {error_code}."
                    )

                if result == 0:
                    break

                if (
                    message.message == WM_HOTKEY
                    and message.wParam == self._hotkey_id
                ):
                    try:
                        self._callback()
                    except Exception:
                        LOGGER.exception(
                            "Erro ao executar o callback do F6."
                        )

        except Exception as error:
            self._error = error
            self._ready.set()

            LOGGER.exception(
                "Falha no atalho global F6."
            )

        finally:
            if registered:
                user32.UnregisterHotKey(
                    None,
                    self._hotkey_id,
                )

            self._ready.set()

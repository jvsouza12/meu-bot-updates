"""Entrada de teclado para Windows usando SendInput."""

from __future__ import annotations

import ctypes
import logging
import os
import threading
from ctypes import wintypes

from .keymap import virtual_key_code


LOGGER = logging.getLogger(__name__)


class KeyboardControllerError(RuntimeError):
    """Falha ao enviar um evento de teclado."""


ULONG_PTR = (
    ctypes.c_ulonglong
    if ctypes.sizeof(ctypes.c_void_p) == 8
    else ctypes.c_ulong
)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("union",)

    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUTUNION),
    ]


class WindowsKeyboardController:
    """Controlador thread-safe para eventos de teclado do Windows."""

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError(
                "O controlador de teclado está disponível somente no Windows."
            )

        pointer_size = ctypes.sizeof(ctypes.c_void_p)
        input_size = ctypes.sizeof(INPUT)

        # Tamanho oficial da estrutura INPUT:
        # Windows 32 bits: 28 bytes
        # Windows 64 bits: 40 bytes
        expected_size = 40 if pointer_size == 8 else 28

        if input_size != expected_size:
            raise RuntimeError(
                f"Estrutura INPUT inválida: {input_size} bytes. "
                f"Esperado: {expected_size} bytes."
            )

        self._user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )

        self._lock = threading.RLock()
        self._pressed_vks: set[int] = set()

        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]

        self._user32.SendInput.restype = wintypes.UINT

    def _send_vk(self, vk: int, key_up: bool) -> None:
        """Envia um evento de tecla pressionada ou liberada."""

        flags = self.KEYEVENTF_KEYUP if key_up else 0

        keyboard_input = KEYBDINPUT()
        keyboard_input.wVk = vk
        keyboard_input.wScan = 0
        keyboard_input.dwFlags = flags
        keyboard_input.time = 0
        keyboard_input.dwExtraInfo = 0

        input_union = INPUTUNION()
        input_union.ki = keyboard_input

        input_event = INPUT()
        input_event.type = self.INPUT_KEYBOARD
        input_event.union = input_union

        sent = self._user32.SendInput(
            1,
            ctypes.byref(input_event),
            ctypes.sizeof(INPUT),
        )

        if sent != 1:
            error_code = ctypes.get_last_error()

            raise KeyboardControllerError(
                "O Windows recusou o evento de teclado "
                f"(código {error_code})."
            )

    def key_down(self, key: str) -> None:
        """Pressiona uma tecla."""

        vk = virtual_key_code(key)

        with self._lock:
            if vk in self._pressed_vks:
                return

            self._send_vk(vk, key_up=False)
            self._pressed_vks.add(vk)

    def key_up(self, key: str) -> None:
        """Libera uma tecla."""

        vk = virtual_key_code(key)

        with self._lock:
            if vk not in self._pressed_vks:
                return

            try:
                self._send_vk(vk, key_up=True)
            finally:
                self._pressed_vks.discard(vk)

    def release_all(self) -> None:
        """Libera todas as teclas pressionadas pelo aplicativo."""

        with self._lock:
            pressed_keys = tuple(self._pressed_vks)

            for vk in pressed_keys:
                try:
                    self._send_vk(vk, key_up=True)
                except Exception:
                    LOGGER.exception(
                        "Falha ao liberar a tecla virtual %s",
                        vk,
                    )
                finally:
                    self._pressed_vks.discard(vk)


def create_keyboard_controller() -> WindowsKeyboardController:
    """Cria o controlador padrão."""

    return WindowsKeyboardController()

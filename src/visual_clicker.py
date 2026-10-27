"""Detecção visual e clique seguro em botões do jogo.

O monitor procura continuamente as imagens configuradas na tela inteira.
Enquanto estiver ativo, ele continua buscando depois de cada clique e também
continua funcionando após erros isolados de captura ou reconhecimento.
"""

from __future__ import annotations

import ctypes
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


LOGGER = logging.getLogger(__name__)


class VisualClickerError(RuntimeError):
    """Erro de inicialização ou clique visual."""


@dataclass(frozen=True)
class ButtonTemplate:
    """Imagem de referência e prioridade de um botão."""

    name: str
    path: Path
    confidence: float = 0.86
    priority: int = 0
    clickable: bool = True
    requires_invitation: bool = False
    navigation_stage: str = "any"
    terminal: bool = False
    click_points: tuple[tuple[float, float], ...] = ()
    optional: bool = False
    promotion_gate: bool = False
    promotion_action: str = ""


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)

    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", _INPUTUNION),
    ]


class EnterMatchMonitor:
    """Busca continuamente e clica nos botões configurados."""

    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    VK_RETURN = 0x0D
    KEYEVENTF_KEYUP = 0x0002

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004

    def __init__(
        self,
        templates: list[ButtonTemplate],
        on_status: Callable[[str], None] | None = None,
        scan_interval: float = 0.30,
        click_cooldown: float = 1.50,
        invitation_authorization_seconds: float = 15.0,
        channel_retry_interval: float = 0.18,
        promotion_ok_relative: tuple[float, float] = (0.50, 0.78),
        promotion_verify_later_relative: tuple[float, float] = (0.82, 0.90),
    ) -> None:
        self._templates = tuple(templates)
        self._on_status = on_status

        self._scan_interval = max(
            0.05,
            scan_interval,
        )

        self._click_cooldown = max(
            0.10,
            click_cooldown,
        )

        self._invitation_authorization_seconds = max(
            1.0,
            invitation_authorization_seconds,
        )
        self._channel_retry_interval = max(
            0.05,
            channel_retry_interval,
        )
        # Coordenadas normalizadas da tela, mantidas juntas para ajuste fácil.
        self._promotion_ok_relative = promotion_ok_relative
        self._promotion_verify_later_relative = promotion_verify_later_relative

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

        self._last_click = 0.0
        self._last_status = ""
        self._invitation_authorized_until = 0.0
        self._navigation_stage = "server"
        self._room_reached = False
        self._click_point_index: dict[str, int] = {}
        self._last_channel_match = None
        self._promotion_phase = "idle"

        self._consecutive_matches: dict[
            str,
            int,
        ] = {}

    def start(self) -> None:
        """Inicia uma única thread de busca contínua."""

        if os.name != "nt":
            raise VisualClickerError(
                "O detector visual está disponível "
                "somente no Windows."
            )

        missing = [
            str(item.path)
            for item in self._templates
            if not item.optional and not item.path.exists()
        ]

        if missing:
            raise VisualClickerError(
                "Imagens de referência não encontradas: "
                + ", ".join(missing)
            )

        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                return

            self._stop_event.clear()
            self._last_click = 0.0
            self._last_status = ""
            self._invitation_authorized_until = 0.0
            self._navigation_stage = "server"
            self._room_reached = False
            self._click_point_index.clear()
            self._last_channel_match = None
            self._promotion_phase = "idle"
            self._consecutive_matches.clear()

            self._thread = threading.Thread(
                target=self._worker,
                name="WASD-ButtonMonitor",
                daemon=True,
            )

            self._thread.start()

    def stop(self) -> None:
        """Interrompe a busca e aguarda a thread terminar."""

        self._stop_event.set()

        thread = self._thread

        if (
            thread is not None
            and thread is not threading.current_thread()
        ):
            thread.join(
                timeout=3.0
            )

        with self._lock:
            if thread is self._thread:
                self._thread = None

    def _notify(
        self,
        text: str,
    ) -> None:
        """Envia status sem repetir mensagens idênticas."""

        if text == self._last_status:
            return

        self._last_status = text

        if self._on_status is not None:
            try:
                self._on_status(text)

            except Exception:
                LOGGER.exception(
                    "Falha ao atualizar status "
                    "do detector visual."
                )

    def _worker(self) -> None:
        """Executa a busca contínua enquanto não receber stop()."""

        try:
            import cv2
            import mss
            import numpy as np

        except ImportError:
            self._notify(
                (
                    "Detector visual indisponível: "
                    "instale mss, OpenCV e NumPy."
                )
            )

            LOGGER.exception(
                "Dependência ausente no detector visual."
            )

            return

        loaded: list[
            tuple[
                ButtonTemplate,
                object,
                int,
                int,
            ]
        ] = []

        for item in self._templates:
            template = cv2.imread(
                str(item.path),
                cv2.IMREAD_GRAYSCALE,
            )

            if template is None:
                LOGGER.warning(
                    "Não foi possível carregar %s",
                    item.path,
                )
                continue

            height, width = template.shape[:2]

            loaded.append(
                (
                    item,
                    template,
                    width,
                    height,
                )
            )

            self._consecutive_matches[
                item.name
            ] = 0

        if not loaded:
            self._notify(
                "Nenhuma imagem de botão pôde ser carregada."
            )
            return

        scales = (
            0.70,
            0.80,
            0.90,
            1.00,
            1.10,
            1.20,
            1.35,
            1.50,
        )

        self._notify(
            "Detector ativo"
        )

        try:
            with mss.mss() as screen:
                while not self._stop_event.is_set():
                    # Cada varredura é independente.
                    # Uma falha isolada não encerra o monitor.
                    try:
                        best = self._find_best(
                            screen,
                            cv2,
                            np,
                            loaded,
                            scales,
                        )

                        visible_names = {
                            item.name
                            for item, *_ in best
                        }

                        promotion_gate_visible = any(
                            item.promotion_gate
                            and self._consecutive_matches.get(
                                item.name,
                                0,
                            ) >= 2
                            for item, *_ in best
                        )

                        promotion_actions_visible = any(
                            item.promotion_action
                            and self._consecutive_matches.get(
                                item.name,
                                0,
                            ) >= 2
                            for item, *_ in best
                        )

                        terminal_visible = any(
                            item.terminal
                            and self._consecutive_matches.get(
                                item.name,
                                0,
                            ) >= 2
                            for item, *_ in best
                        )

                        if terminal_visible and not self._room_reached:
                            self._room_reached = True
                            self._navigation_stage = "rooms"
                            self._notify(
                                "Salas detectadas; navegação de servidor concluída."
                            )

                        for match in best:
                            if match[0].name == "Canal 2":
                                self._last_channel_match = match

                        for item, *_ in loaded:
                            if item.name in visible_names:
                                self._consecutive_matches[
                                    item.name
                                ] += 1
                            else:
                                self._consecutive_matches[
                                    item.name
                                ] = 0

                        candidates = [
                            match
                            for match in best
                            if (
                                match[0].clickable
                                and (
                                    (
                                        match[0].promotion_action
                                        and promotion_gate_visible
                                        and (
                                            (
                                                match[0].promotion_action == "ok"
                                                and self._promotion_phase == "idle"
                                            )
                                            or (
                                                match[0].promotion_action == "later"
                                                and self._promotion_phase == "ok"
                                            )
                                        )
                                    )
                                    or (
                                        not match[0].promotion_action
                                        and not self._room_reached
                                    )
                                )
                                and (
                                    match[0].navigation_stage == "any"
                                    or match[0].navigation_stage
                                    == self._navigation_stage
                                )
                                and (
                                    self._navigation_stage == "channel_retry"
                                    and match[0].name == "Canal 2"
                                    or self._consecutive_matches[
                                        match[0].name
                                    ] >= 2
                                )
                                and (
                                    not match[0].requires_invitation
                                    or time.monotonic()
                                    <= self._invitation_authorized_until
                                )
                            )
                        ]

                        # Sem template dos botões, usa a posição relativa
                        # somente após detectar a tela "Parabéns".
                        if (
                            promotion_gate_visible
                            and not promotion_actions_visible
                            and self._promotion_phase in ("idle", "ok")
                        ):
                            gate_match = next(
                                (
                                    match
                                    for match in best
                                    if match[0].promotion_gate
                                ),
                                None,
                            )
                            if gate_match is not None:
                                monitor = screen.monitors[0]
                                relative = (
                                    self._promotion_ok_relative
                                    if self._promotion_phase == "idle"
                                    else self._promotion_verify_later_relative
                                )
                                candidates = [
                                    (
                                        gate_match[0],
                                        monitor["left"]
                                        + int(monitor["width"] * relative[0]),
                                        monitor["top"]
                                        + int(monitor["height"] * relative[1]),
                                        0,
                                        0,
                                        1.0,
                                        1.0,
                                    )
                                ]

                        invitation_visible = any(
                            (
                                item.requires_invitation
                                and not item.clickable
                                and self._consecutive_matches[
                                    item.name
                                ] >= 2
                            )
                            for item, *_ in best
                        )

                        if invitation_visible:
                            self._invitation_authorized_until = (
                                time.monotonic()
                                + self._invitation_authorization_seconds
                            )

                            self._notify(
                                "Convite detectado; Enter e Pronto liberados temporariamente."
                            )

                        full_channel_visible = any(
                            item.name == "Canal cheio"
                            and self._consecutive_matches.get(
                                item.name,
                                0,
                            ) >= 2
                            for item, *_ in best
                        )

                        if full_channel_visible and not self._room_reached:
                            self._navigation_stage = "channel_retry"
                            self._notify(
                                "Canal 2 cheio; iniciando tentativas com clique e Enter."
                            )

                        # No modo de canal cheio, continua usando a última
                        # posição conhecida do Canal 2 mesmo quando o aviso
                        # cobre o texto por alguns frames.
                        if (
                            not candidates
                            and self._navigation_stage == "channel_retry"
                            and self._last_channel_match is not None
                        ):
                            candidates = [self._last_channel_match]

                        candidates.sort(
                            key=lambda match: (
                                match[0].priority,
                                match[5],
                            ),
                            reverse=True,
                        )

                        retry_mode = self._navigation_stage == "channel_retry"
                        click_interval = (
                            self._channel_retry_interval
                            if retry_mode
                            else self._click_cooldown
                        )
                        can_click = (
                            time.monotonic()
                            - self._last_click
                            >= click_interval
                        )

                        if candidates and can_click:
                            (
                                item,
                                x,
                                y,
                                width,
                                height,
                                scale,
                                score,
                            ) = candidates[0]

                            is_screen_fallback = (
                                item.promotion_gate
                                and width == 0
                            )
                            click_points = item.click_points
                            if is_screen_fallback:
                                self._click_at(x, y)
                            elif click_points:
                                point_index = min(
                                    self._click_point_index.get(item.name, 0),
                                    len(click_points) - 1,
                                )
                                relative_x, relative_y = click_points[point_index]
                                self._click_relative_point(
                                    x,
                                    y,
                                    width,
                                    height,
                                    scale,
                                    relative_x,
                                    relative_y,
                                )
                                if point_index < len(click_points) - 1:
                                    self._click_point_index[item.name] = point_index + 1
                            else:
                                self._click_center(
                                    x,
                                    y,
                                    width,
                                    height,
                                    scale,
                                )

                            if item.name == "Agulhas Negras":
                                self._navigation_stage = "channel"
                                self._notify(
                                    "Agulhas Negras selecionado; procurando o Canal 2."
                                )
                            elif item.name == "Canal 2":
                                if self._navigation_stage == "channel_retry":
                                    self._press_enter()
                                    self._notify(
                                        "Tentativa no Canal 2 enviada com Enter."
                                    )
                                else:
                                    self._notify(
                                        "Canal 2 selecionado; aguardando a tela de salas."
                                    )
                            elif item.promotion_action == "ok":
                                self._promotion_phase = "ok"
                                self._notify(
                                    "Promoção confirmada; aguardando Verificar Depois."
                                )
                            elif item.promotion_action == "later":
                                self._promotion_phase = "idle"
                                self._notify(
                                    "Recompensa de patente adiada com Verificar Depois."
                                )
                            elif is_screen_fallback:
                                self._promotion_phase = (
                                    "ok"
                                    if self._promotion_phase == "idle"
                                    else "idle"
                                )
                                self._notify(
                                    "Ação da promoção executada por coordenada relativa."
                                )

                            self._last_click = (
                                time.monotonic()
                            )

                            self._notify(
                                (
                                    f"Botão {item.name} "
                                    f"clicado ({score:.0%})."
                                )
                            )

                            # Zera somente esse botão.
                            # A busca continua normalmente.
                            self._consecutive_matches[
                                item.name
                            ] = 0

                    except Exception as exc:
                        LOGGER.exception(
                            (
                                "Falha em uma varredura visual; "
                                "a busca continuará."
                            )
                        )

                        self._notify(
                            (
                                "Falha temporária na busca "
                                "visual; tentando novamente: "
                                f"{exc}"
                            )
                        )

                    # A espera também pode ser interrompida
                    # imediatamente pelo método stop().
                    self._stop_event.wait(
                        self._scan_interval
                    )

        except Exception as exc:
            self._notify(
                f"Detector visual interrompido: {exc}"
            )

            LOGGER.exception(
                "Falha geral no monitor visual."
            )

    def _find_best(
        self,
        screen,
        cv2,
        np,
        loaded,
        scales,
    ):
        """Procura a melhor correspondência de cada imagem."""

        monitor = screen.monitors[0]

        screenshot = np.array(
            screen.grab(monitor)
        )

        frame = cv2.cvtColor(
            screenshot,
            cv2.COLOR_BGRA2GRAY,
        )

        matches = []

        for (
            item,
            template,
            width,
            height,
        ) in loaded:
            best_score = -1.0
            best_data = None

            for scale in scales:
                scaled_width = max(
                    10,
                    int(width * scale),
                )

                scaled_height = max(
                    10,
                    int(height * scale),
                )

                if (
                    scaled_width
                    >= frame.shape[1]
                    or scaled_height
                    >= frame.shape[0]
                ):
                    continue

                candidate = cv2.resize(
                    template,
                    (
                        scaled_width,
                        scaled_height,
                    ),
                    interpolation=cv2.INTER_AREA,
                )

                result = cv2.matchTemplate(
                    frame,
                    candidate,
                    cv2.TM_CCOEFF_NORMED,
                )

                _, score, _, location = (
                    cv2.minMaxLoc(result)
                )

                if score > best_score:
                    best_score = score
                    best_data = (
                        location[0],
                        location[1],
                        scale,
                    )

            if (
                best_data is not None
                and best_score >= item.confidence
            ):
                x, y, scale = best_data

                matches.append(
                    (
                        item,
                        x + monitor["left"],
                        y + monitor["top"],
                        width,
                        height,
                        scale,
                        best_score,
                    )
                )

        return matches

    @classmethod
    def _click_relative_point(
        cls,
        x: int,
        y: int,
        width: int,
        height: int,
        scale: float,
        relative_x: float,
        relative_y: float,
    ) -> None:
        """Clica em uma posição proporcional dentro do template detectado."""

        cls._click_at(
            int(x + (width * scale * relative_x)),
            int(y + (height * scale * relative_y)),
        )

    @classmethod
    def _click_at(cls, center_x: int, center_y: int) -> None:
        """Executa um clique esquerdo em coordenadas absolutas."""

        if os.name != "nt":
            raise VisualClickerError(
                "O clique visual só está disponível no Windows."
            )

        user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        user32.SetCursorPos.restype = ctypes.c_int
        user32.SendInput.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        user32.SendInput.restype = ctypes.c_uint

        if not user32.SetCursorPos(center_x, center_y):
            raise VisualClickerError(
                f"SetCursorPos falhou: {ctypes.get_last_error()}"
            )

        down = _INPUT(
            type=cls.INPUT_MOUSE,
            mi=_MOUSEINPUT(
                dx=0, dy=0, mouseData=0,
                dwFlags=cls.MOUSEEVENTF_LEFTDOWN,
                time=0, dwExtraInfo=None,
            ),
        )
        up = _INPUT(
            type=cls.INPUT_MOUSE,
            mi=_MOUSEINPUT(
                dx=0, dy=0, mouseData=0,
                dwFlags=cls.MOUSEEVENTF_LEFTUP,
                time=0, dwExtraInfo=None,
            ),
        )
        sent = user32.SendInput(
            2,
            (_INPUT * 2)(down, up),
            ctypes.sizeof(_INPUT),
        )
        if sent != 2:
            raise VisualClickerError(
                "O Windows recusou o clique "
                f"(código {ctypes.get_last_error()})."
            )

    @classmethod
    def _press_enter(cls) -> None:
        """Envia Enter pelo Windows usando SendInput."""

        if os.name != "nt":
            raise VisualClickerError(
                "O Enter visual só está disponível no Windows."
            )

        user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )
        user32.SendInput.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        user32.SendInput.restype = ctypes.c_uint

        down = _INPUT(
            type=cls.INPUT_KEYBOARD,
            ki=_KEYBDINPUT(
                wVk=cls.VK_RETURN,
                wScan=0,
                dwFlags=0,
                time=0,
                dwExtraInfo=None,
            ),
        )
        up = _INPUT(
            type=cls.INPUT_KEYBOARD,
            ki=_KEYBDINPUT(
                wVk=cls.VK_RETURN,
                wScan=0,
                dwFlags=cls.KEYEVENTF_KEYUP,
                time=0,
                dwExtraInfo=None,
            ),
        )
        events = (_INPUT * 2)(down, up)
        sent = user32.SendInput(
            2,
            events,
            ctypes.sizeof(_INPUT),
        )

        if sent != 2:
            raise VisualClickerError(
                "O Windows recusou o Enter "
                f"(código {ctypes.get_last_error()})."
            )

    @classmethod
    def _click_center(
        cls,
        x: int,
        y: int,
        width: int,
        height: int,
        scale: float,
    ) -> None:
        """Executa clique no centro da correspondência encontrada."""

        cls._click_at(
            int(x + (width * scale) / 2),
            int(y + (height * scale) / 2),
        )

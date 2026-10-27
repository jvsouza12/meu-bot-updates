"""Interface gráfica do WASD Auto Toggle."""

from __future__ import annotations

import logging
import os
import queue
import sys
import tkinter.messagebox as messagebox
from datetime import datetime
from pathlib import Path
from tkinter import END, StringVar

import customtkinter as ctk
from PIL import Image

from .automation import AutomationEngine
from .auth_db import AuthDatabase, UserRecord
from .hotkey_manager import GlobalHotkeyError, GlobalHotkeyManager
from .keyboard_controller import create_keyboard_controller
from .keymap import format_sequence, parse_sequence_text
from .settings_manager import (
    Settings,
    SettingsManager,
    SettingsValidationError,
)
from .visual_clicker import (
    ButtonTemplate,
    EnterMatchMonitor,
    VisualClickerError,
)


LOGGER = logging.getLogger(__name__)


class App(ctk.CTk):
    """Janela principal, mantendo interface e automação separadas."""

    def __init__(
        self,
        user: UserRecord | None = None,
        license_info=None,
    ) -> None:
        super().__init__()

        self._user = user
        self._remote_license = license_info

        self.title("Auto Click by ]BETANO")
        self.geometry("620x720")
        self.minsize(560, 640)

        self.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

        self._settings_manager = SettingsManager()
        self._settings = self._settings_manager.load()

        self._ui_queue: queue.Queue[
            tuple[str, object]
        ] = queue.Queue()

        self._closing = False
        self._hotkey: GlobalHotkeyManager | None = None
        self._controller = None
        self._engine: AutomationEngine | None = None

        self._enter_match_monitor: (
            EnterMatchMonitor | None
        ) = None

        self._visual_monitor_running = False
        self._log_box: ctk.CTkTextbox | None = None

        self._build_widgets()
        self._initialize_engine()

        self.after(
            100,
            self._poll_state,
        )

    def _build_widgets_legacy(self) -> None:
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")

        outer = ctk.CTkFrame(
            self,
            corner_radius=12,
        )

        outer.pack(
            fill="both",
            expand=True,
            padx=18,
            pady=18,
        )

        ctk.CTkLabel(
            outer,
            text="WASD Auto Toggle",
            font=ctk.CTkFont(
                size=26,
                weight="bold",
            ),
        ).pack(
            pady=(20, 2),
        )

        ctk.CTkLabel(
            outer,
            text=(
                "Automação controlada "
                "pelo atalho global F6"
            ),
            text_color=(
                "#555555",
                "#BBBBBB",
            ),
        ).pack(
            pady=(0, 18),
        )

        self._license_var = StringVar(
            value=self._license_text(),
        )

        ctk.CTkLabel(
            outer,
            textvariable=self._license_var,
            font=ctk.CTkFont(
                size=18,
                weight="bold",
            ),
            text_color=(
                "#1E8449",
                "#7DCEA0",
            ),
            fg_color=(
                "#E9F7EF",
                "#163A27",
            ),
            corner_radius=8,
        ).pack(
            fill="x",
            padx=22,
            pady=(0, 16),
        )

        status_frame = ctk.CTkFrame(
            outer,
            fg_color=(
                "#E9F7EF",
                "#163A27",
            ),
            corner_radius=8,
        )

        status_frame.pack(
            fill="x",
            padx=22,
            pady=(0, 16),
        )

        self._status_var = StringVar(
            value="INATIVO",
        )

        self._status_label = ctk.CTkLabel(
            status_frame,
            textvariable=self._status_var,
            font=ctk.CTkFont(
                size=19,
                weight="bold",
            ),
            text_color=(
                "#1E8449",
                "#7DCEA0",
            ),
        )

        self._status_label.pack(
            pady=12,
        )

        self._toggle_button = ctk.CTkButton(
            outer,
            text="Iniciar automação",
            height=40,
            command=self._toggle_from_button,
        )

        self._toggle_button.pack(
            fill="x",
            padx=22,
            pady=(0, 18),
        )

        form = ctk.CTkFrame(
            outer,
            fg_color="transparent",
        )

        form.pack(
            fill="x",
            padx=22,
        )

        form.grid_columnconfigure(
            1,
            weight=1,
        )

        self._interval_var = StringVar(
            value=str(
                self._settings.interval_ms,
            ),
        )

        self._duration_var = StringVar(
            value=str(
                self._settings.press_duration_ms,
            ),
        )

        self._sequence_var = StringVar(
            value=format_sequence(
                self._settings.sequence,
            ),
        )

        self._add_field(
            form,
            0,
            "Intervalo entre teclas (ms):",
            self._interval_var,
        )

        self._add_field(
            form,
            1,
            "Duração de cada tecla (ms):",
            self._duration_var,
        )

        self._add_field(
            form,
            2,
            "Sequência (ex.: W,A,S,D):",
            self._sequence_var,
        )

        buttons = ctk.CTkFrame(
            outer,
            fg_color="transparent",
        )

        buttons.pack(
            fill="x",
            padx=22,
            pady=(18, 8),
        )

        buttons.grid_columnconfigure(
            0,
            weight=1,
        )

        buttons.grid_columnconfigure(
            1,
            weight=1,
        )

        ctk.CTkButton(
            buttons,
            text="Salvar configurações",
            command=self._save_settings,
        ).grid(
            row=0,
            column=0,
            padx=(0, 6),
            sticky="ew",
        )

        ctk.CTkButton(
            buttons,
            text="Restaurar padrões",
            fg_color="transparent",
            border_width=1,
            command=self._restore_defaults,
        ).grid(
            row=0,
            column=1,
            padx=(6, 0),
            sticky="ew",
        )

        ctk.CTkLabel(
            outer,
            text=(
                "F6 alterna o estado mesmo com a "
                "janela minimizada.\n"
                "O programa não registra outras teclas."
            ),
            justify="center",
            text_color=(
                "#666666",
                "#AAAAAA",
            ),
        ).pack(
            pady=(8, 12),
        )

        self._message_var = StringVar(
            value=(
                "Pronto. A automação "
                "não inicia sozinha."
            ),
        )

        ctk.CTkLabel(
            outer,
            textvariable=self._message_var,
            wraplength=440,
        ).pack(
            pady=(0, 16),
        )

        ctk.CTkLabel(
            outer,
            text="Log em tempo real",
            anchor="w",
            font=ctk.CTkFont(
                size=14,
                weight="bold",
            ),
        ).pack(
            fill="x",
            padx=22,
            pady=(0, 4),
        )

        self._log_box = ctk.CTkTextbox(
            outer,
            height=110,
            activate_scrollbars=True,
            wrap="word",
        )

        self._log_box.pack(
            fill="both",
            expand=True,
            padx=22,
            pady=(0, 16),
        )

        self._log_box.configure(
            state="disabled",
        )

    def _build_widgets(self) -> None:
        """Monta a interface com a identidade visual do nick ]BETANO."""

        bg = "#0E0F22"
        surface = "#17192D"
        surface_alt = "#20223A"
        orange = "#FF3D00"
        white = "#FFFFFF"
        muted = "#A7A9B8"
        green = "#31D17C"

        ctk.set_appearance_mode("Dark")
        self.configure(fg_color=bg)

        base_dir = Path(
            getattr(
                sys,
                "_MEIPASS",
                Path(__file__).resolve().parent.parent,
            ),
        )

        shell = ctk.CTkFrame(
            self,
            fg_color=bg,
            corner_radius=0,
        )
        shell.pack(fill="both", expand=True, padx=24, pady=20)

        header = ctk.CTkFrame(
            shell,
            fg_color="transparent",
        )
        header.pack(fill="x", pady=(0, 18))

        logo_path = base_dir / "assets" / "betano_logo.png"
        self._logo_image = None
        if logo_path.exists():
            logo = Image.open(logo_path)
            self._logo_image = ctk.CTkImage(
                light_image=logo,
                dark_image=logo,
                size=(42, 42),
            )

        logo_label = ctk.CTkLabel(
            header,
            text="" if self._logo_image else "B",
            image=self._logo_image,
            text_color=white,
            fg_color=orange,
            corner_radius=12,
            width=48,
            height=48,
        )
        logo_label.pack(side="left")

        brand = ctk.CTkFrame(header, fg_color="transparent")
        brand.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(
            brand,
            text="]BETANO",
            text_color=orange,
            font=ctk.CTkFont(size=25, weight="bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            brand,
            text="AUTOCLICK CONTROL",
            text_color=muted,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).pack(anchor="w")

        self._license_var = StringVar(value=self._license_text())
        ctk.CTkLabel(
            header,
            textvariable=self._license_var,
            text_color=muted,
            font=ctk.CTkFont(size=11),
            justify="right",
        ).pack(side="right", anchor="e")

        status_card = ctk.CTkFrame(
            shell,
            fg_color=surface,
            corner_radius=16,
            border_width=1,
            border_color="#2B2E49",
        )
        status_card.pack(fill="x", pady=(0, 14))

        status_top = ctk.CTkFrame(status_card, fg_color="transparent")
        status_top.pack(fill="x", padx=18, pady=(16, 4))
        ctk.CTkLabel(
            status_top,
            text="STATUS DA AUTOMAÇÃO",
            text_color=muted,
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(side="left")
        self._status_var = StringVar(value="INATIVO")
        self._status_label = ctk.CTkLabel(
            status_top,
            textvariable=self._status_var,
            text_color=green,
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self._status_label.pack(side="right")

        self._toggle_button = ctk.CTkButton(
            status_card,
            text="INICIAR AUTOMAÇÃO",
            command=self._toggle_from_button,
            height=46,
            corner_radius=10,
            fg_color=orange,
            hover_color="#D83200",
            text_color=white,
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        self._toggle_button.pack(fill="x", padx=18, pady=(8, 18))

        settings_card = ctk.CTkFrame(
            shell,
            fg_color=surface,
            corner_radius=16,
            border_width=1,
            border_color="#2B2E49",
        )
        settings_card.pack(fill="x", pady=(0, 14))
        ctk.CTkLabel(
            settings_card,
            text="CONFIGURAÇÕES",
            text_color=white,
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w", padx=18, pady=(16, 8))

        form = ctk.CTkFrame(settings_card, fg_color="transparent")
        form.pack(fill="x", padx=18)
        form.grid_columnconfigure(1, weight=1)

        self._interval_var = StringVar(value=str(self._settings.interval_ms))
        self._duration_var = StringVar(value=str(self._settings.press_duration_ms))
        self._sequence_var = StringVar(value=format_sequence(self._settings.sequence))

        self._add_field(form, 0, "Intervalo entre teclas (ms):", self._interval_var)
        self._add_field(form, 1, "Duração de cada tecla (ms):", self._duration_var)
        self._add_field(form, 2, "Sequência:", self._sequence_var)

        actions = ctk.CTkFrame(settings_card, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(10, 16))
        actions.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(
            actions,
            text="SALVAR",
            command=self._save_settings,
            height=34,
            fg_color=surface_alt,
            hover_color="#2A2D48",
        ).grid(row=0, column=0, padx=(0, 5), sticky="ew")
        ctk.CTkButton(
            actions,
            text="RESTAURAR PADRÕES",
            command=self._restore_defaults,
            height=34,
            fg_color="transparent",
            hover_color=surface_alt,
            border_width=1,
            border_color="#3B3F5C",
        ).grid(row=0, column=1, padx=(5, 0), sticky="ew")

        info = ctk.CTkFrame(shell, fg_color="transparent")
        info.pack(fill="x", pady=(0, 10))
        self._message_var = StringVar(
            value="Pronto. Pressione F6 ou Iniciar para ativar a automação."
        )
        ctk.CTkLabel(
            info,
            textvariable=self._message_var,
            text_color=muted,
            wraplength=560,
            justify="left",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            info,
            text="F6",
            text_color=orange,
            fg_color=surface_alt,
            corner_radius=6,
            font=ctk.CTkFont(size=12, weight="bold"),
            padx=10,
            pady=5,
        ).pack(side="right")

        ctk.CTkLabel(
            shell,
            text="LOG EM TEMPO REAL",
            text_color=white,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(fill="x", pady=(2, 6))

        self._log_box = ctk.CTkTextbox(
            shell,
            height=150,
            activate_scrollbars=True,
            wrap="word",
            fg_color=surface,
            border_width=1,
            border_color="#2B2E49",
            text_color="#D9DAE5",
        )
        self._log_box.pack(fill="both", expand=True)
        self._log_box.configure(state="disabled")

    def _license_text(self) -> str:
        """Retorna o prazo da automação em linguagem clara."""

        if self._user is None:
            return (
                "TEMPO DE AUTOMAÇÃO: "
                "sessão não identificada"
            )

        if self._remote_license is not None:
            info = self._remote_license

            if (
                getattr(info, "unlimited", False)
                or getattr(info, "status", "")
                == "ILIMITADO"
            ):
                return (
                    "TEMPO DE AUTOMAÇÃO: "
                    "ILIMITADO"
                )

            if getattr(
                info,
                "days_remaining",
                None,
            ) is None:
                return (
                    "TEMPO DE AUTOMAÇÃO: "
                    "aguardando ativação"
                )

            expiry = (
                info.expires_at.strftime(
                    "%d/%m/%Y",
                )
                if getattr(
                    info,
                    "expires_at",
                    None,
                )
                else "-"
            )

            return (
                "TEMPO DE AUTOMAÇÃO: "
                f"{info.days_remaining} dia(s) "
                f"restante(s) | expira em {expiry}"
            )

        info = AuthDatabase().license_info(
            self._user,
        )

        if info.status == "ILIMITADO":
            return (
                "TEMPO DE AUTOMAÇÃO: "
                "ILIMITADO"
            )

        if info.days_remaining is None:
            return (
                "TEMPO DE AUTOMAÇÃO: "
                "aguardando ativação"
            )

        expiry = (
            info.expires_at.strftime(
                "%d/%m/%Y",
            )
            if info.expires_at
            else "-"
        )

        return (
            "TEMPO DE AUTOMAÇÃO: "
            f"{info.days_remaining} dia(s) "
            f"restante(s) | expira em {expiry}"
        )

    @staticmethod
    def _add_field(
        parent: ctk.CTkFrame,
        row: int,
        label: str,
        variable: StringVar,
    ) -> None:
        ctk.CTkLabel(
            parent,
            text=label,
            anchor="w",
        ).grid(
            row=row,
            column=0,
            padx=(0, 12),
            pady=6,
            sticky="w",
        )

        ctk.CTkEntry(
            parent,
            textvariable=variable,
        ).grid(
            row=row,
            column=1,
            pady=6,
            sticky="ew",
        )

    def _initialize_engine(self) -> None:
        try:
            self._controller = (
                create_keyboard_controller()
            )

        except Exception as exc:
            self._message_var.set(
                f"Indisponível neste sistema: {exc}",
            )

            self._toggle_button.configure(
                state="disabled",
            )

            return

        self._engine = AutomationEngine(
            self._controller,
            self._settings,
            self._queue_error,
        )

        self._hotkey = GlobalHotkeyManager(
            lambda: self.after(
                0,
                self._toggle_from_hotkey,
            ),
        )

        try:
            self._hotkey.start()

        except GlobalHotkeyError as exc:
            self._message_var.set(
                str(exc),
            )

            LOGGER.warning(
                "F6 não foi registrado: %s",
                exc,
            )

        base_dir = Path(
            getattr(
                sys,
                "_MEIPASS",
                Path(__file__).resolve().parent.parent,
            ),
        )

        self._enter_match_monitor = EnterMatchMonitor(
            templates=[
                # Fluxo de entrada nos servidores do CrossFire.
                # Use recortes individuais das telas, sem a montagem IMAGENSJUNTAS.
                ButtonTemplate(
                    name="Agulhas Negras",
                    path=(
                        base_dir
                        / "assets"
                        / "agulhas_negras_template.png"
                    ),
                    confidence=0.86,
                    priority=1000,
                    navigation_stage="server",
                ),
                ButtonTemplate(
                    name="Canal 2",
                    path=(
                        base_dir
                        / "assets"
                        / "canal_2_template.png"
                    ),
                    confidence=0.84,
                    priority=1000,
                    navigation_stage="any",
                ),
                ButtonTemplate(
                    name="Canal cheio",
                    path=(
                        base_dir
                        / "assets"
                        / "canal_cheio_template.png"
                    ),
                    confidence=0.80,
                    priority=1100,
                    clickable=False,
                    navigation_stage="any",
                ),
                ButtonTemplate(
                    name="Tela de salas",
                    path=(
                        base_dir
                        / "assets"
                        / "salas_template.png"
                    ),
                    confidence=0.82,
                    priority=1200,
                    clickable=False,
                    terminal=True,
                    navigation_stage="any",
                ),
                # Promoção: estes recortes são opcionais. Se os recortes dos
                # botões não existirem, o monitor usa as coordenadas relativas
                # configuradas em EnterMatchMonitor, mas somente depois de
                # reconhecer a tela "Parabéns".
                ButtonTemplate(
                    name="Tela de promoção",
                    path=(
                        base_dir
                        / "assets"
                        / "promocao_template.png"
                    ),
                    confidence=0.80,
                    priority=2000,
                    clickable=False,
                    optional=True,
                    promotion_gate=True,
                    navigation_stage="any",
                ),
                ButtonTemplate(
                    name="OK promoção",
                    path=(
                        base_dir
                        / "assets"
                        / "promocao_ok_template.png"
                    ),
                    confidence=0.82,
                    priority=2100,
                    optional=True,
                    promotion_action="ok",
                    navigation_stage="any",
                ),
                ButtonTemplate(
                    name="Verificar Depois",
                    path=(
                        base_dir
                        / "assets"
                        / "verificar_depois_template.png"
                    ),
                    confidence=0.82,
                    priority=2090,
                    optional=True,
                    promotion_action="later",
                    navigation_stage="any",
                ),
                ButtonTemplate(
                    name="Tela OKUP",
                    path=(
                        base_dir
                        / "assets"
                        / "okup.png"
                    ),
                    confidence=0.82,
                    priority=1300,
                    navigation_stage="any",
                    # A captura completa da tela é usada como referência.
                    # Primeiro seleciona Não Salvar; depois confirma em OK.
                    click_points=(
                        (0.77, 0.83),
                        (0.90, 0.83),
                    ),
                ),
                ButtonTemplate(
                    name="Convite recebido",
                    path=(
                        base_dir
                        / "assets"
                        / "invite_guard_template.png"
                    ),
                    confidence=0.78,
                    priority=100,
                    clickable=False,
                    requires_invitation=True,
                ),
                ButtonTemplate(
                    name="Cancelar senha da sala",
                    path=(
                        base_dir
                        / "assets"
                        / "sala_cancel_template.png"
                    ),
                    confidence=0.82,
                    priority=10,
                ),
                ButtonTemplate(
                    name="Entrar na partida",
                    path=(
                        base_dir
                        / "assets"
                        / "enter_match_template.png"
                    ),
                    confidence=0.86,
                    priority=3,
                    requires_invitation=True,
                ),
                ButtonTemplate(
                    name="Pronto",
                    path=(
                        base_dir
                        / "assets"
                        / "pronto_template.png"
                    ),
                    confidence=0.86,
                    priority=2,
                    requires_invitation=True,
                ),
                ButtonTemplate(
                    name="Confirmar convite",
                    path=(
                        base_dir
                        / "assets"
                        / "confirma_template.png"
                    ),
                    confidence=0.80,
                    priority=1,
                    requires_invitation=True,
                ),
            ],
            on_status=lambda text: self._ui_queue.put(
                ("visual", text),
            ),
            # Ajuste fácil: valores normalizados (x, y) da tela. O segundo
            # botão é deliberadamente o inferior direito. Nunca há uma ação
            # configurada para "Verificar Recompensa de Patente".
            promotion_ok_relative=(0.50, 0.78),
            promotion_verify_later_relative=(0.82, 0.90),
        )

        self._message_var.set(
            (
                "Pronto. Pressione F6 ou "
                "Iniciar para ativar a automação."
            ),
        )

        self._append_log(
            "Aplicativo pronto; automação INATIVA.",
        )

    def _queue_error(
        self,
        error: Exception,
    ) -> None:
        self._ui_queue.put(
            ("error", error),
        )

    def _append_log(
        self,
        message: str,
    ) -> None:
        """Adiciona uma linha com horário ao log."""

        if self._log_box is None:
            return

        timestamp = datetime.now().strftime(
            "%H:%M:%S",
        )

        self._log_box.configure(
            state="normal",
        )

        self._log_box.insert(
            END,
            f"[{timestamp}] {message}\n",
        )

        self._log_box.see(
            END,
        )

        self._log_box.configure(
            state="disabled",
        )

    def _parse_form(self) -> Settings:
        try:
            interval = int(
                self._interval_var.get().strip(),
            )

            duration = int(
                self._duration_var.get().strip(),
            )

            sequence = parse_sequence_text(
                self._sequence_var.get(),
            )

            return Settings(
                interval_ms=interval,
                press_duration_ms=duration,
                sequence=sequence,
            )

        except (
            ValueError,
            SettingsValidationError,
        ) as exc:
            raise SettingsValidationError(
                str(exc),
            ) from exc

    def _save_settings(self) -> None:
        if self._engine is None:
            return

        try:
            settings = self._parse_form()

            self._engine.set_settings(
                settings,
            )

            self._settings_manager.save(
                settings,
            )

            self._settings = settings

            self._message_var.set(
                (
                    "Configurações salvas em "
                    f"{self._settings_manager.path}"
                ),
            )

        except (
            SettingsValidationError,
            RuntimeError,
            OSError,
        ) as exc:
            messagebox.showerror(
                "Configuração inválida",
                str(exc),
                parent=self,
            )

    def _restore_defaults(self) -> None:
        if (
            self._engine is not None
            and self._engine.is_running
        ):
            messagebox.showwarning(
                "Automação ativa",
                (
                    "Pare a automação antes "
                    "de restaurar os padrões."
                ),
                parent=self,
            )

            return

        defaults = Settings()

        self._interval_var.set(
            str(defaults.interval_ms),
        )

        self._duration_var.set(
            str(defaults.press_duration_ms),
        )

        self._sequence_var.set(
            format_sequence(
                defaults.sequence,
            ),
        )

        self._message_var.set(
            (
                "Padrões restaurados no formulário. "
                "Clique em salvar para persistir."
            ),
        )

    def _toggle_from_button(self) -> None:
        self._toggle()

    def _toggle_from_hotkey(self) -> None:
        if not self._closing:
            self._toggle()

    def _toggle(self) -> None:
        if self._engine is None:
            return

        if not self._engine.is_running:
            try:
                settings = self._parse_form()

                self._engine.set_settings(
                    settings,
                )

                self._settings_manager.save(
                    settings,
                )

                self._settings = settings

            except (
                SettingsValidationError,
                RuntimeError,
                OSError,
            ) as exc:
                messagebox.showerror(
                    "Não foi possível iniciar",
                    str(exc),
                    parent=self,
                )

                return

        was_running = self._engine.is_running

        self._engine.toggle()
        self._refresh_state()

        if (
            self._engine.is_running
            and not was_running
        ):
            self._append_log(
                (
                    "Automação ATIVADA; "
                    "detector visual iniciado."
                ),
            )

        elif (
            was_running
            and not self._engine.is_running
        ):
            self._append_log(
                (
                    "Automação INTERROMPIDA; "
                    "detector visual parado."
                ),
            )

    def _refresh_state(self) -> None:
        running = (
            self._engine is not None
            and self._engine.is_running
        )

        self._status_var.set(
            "ATIVO"
            if running
            else "INATIVO",
        )

        self._toggle_button.configure(
            text=(
                "Interromper automação"
                if running
                else "Iniciar automação"
            ),
        )

        if self._enter_match_monitor is None:
            return

        if (
            running
            and not self._visual_monitor_running
        ):
            try:
                self._enter_match_monitor.start()
                self._visual_monitor_running = True

            except VisualClickerError as exc:
                self._message_var.set(
                    f"Detector visual indisponível: {exc}",
                )

                LOGGER.warning(
                    "Detector visual não foi iniciado: %s",
                    exc,
                )

        elif (
            not running
            and self._visual_monitor_running
        ):
            self._enter_match_monitor.stop()
            self._visual_monitor_running = False

    def _poll_state(self) -> None:
        if self._closing:
            return

        self._refresh_state()

        try:
            while True:
                kind, payload = (
                    self._ui_queue.get_nowait()
                )

                if kind == "error":
                    self._message_var.set(
                        f"Automação interrompida: {payload}",
                    )

                    self._append_log(
                        f"ERRO: {payload}",
                    )

                elif (
                    kind == "visual"
                    and isinstance(payload, str)
                ):
                    self._message_var.set(
                        payload,
                    )

                    self._append_log(
                        payload,
                    )

        except queue.Empty:
            pass

        self.after(
            100,
            self._poll_state,
        )

    def _on_close(self) -> None:
        if self._closing:
            return

        self._closing = True

        try:
            if self._enter_match_monitor is not None:
                self._enter_match_monitor.stop()
                self._visual_monitor_running = False

            if self._hotkey is not None:
                self._hotkey.stop()

            if self._engine is not None:
                self._engine.close()

        finally:
            self.destroy()


def run() -> None:
    """Ponto de entrada da aplicação gráfica."""

    logging.basicConfig(
        filename=(
            Path.home()
            / "wasd_auto_toggle.log"
        ),
        level=logging.INFO,
        format=(
            "%(asctime)s "
            "%(levelname)s "
            "%(name)s: %(message)s"
        ),
    )

    if os.name != "nt":
        LOGGER.warning(
            (
                "O aplicativo foi iniciado fora do Windows; "
                "entrada e F6 não estarão disponíveis."
            ),
        )

    app = App()
    app.mainloop()

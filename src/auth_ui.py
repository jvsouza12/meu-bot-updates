"""Telas de login e painel administrativo do FF DO 100."""

from __future__ import annotations

import tkinter.messagebox as messagebox
import sys
from pathlib import Path
from tkinter import END, StringVar, ttk

import customtkinter as ctk
from PIL import Image

from .auth_db import (
    AuthDatabase,
    AuthError,
    ROLE_ADMIN,
    RULE_CREATION,
    RULE_FIRST_LOGIN,
    UserRecord,
    generate_access_key,
)
from .supabase_client import (
    SupabaseClient,
    SupabaseClientError,
)


class LoginWindow(ctk.CTk):
    """Tela de login com mensagem de erro e suporte ao Enter."""

    def __init__(
        self,
        database,
        on_success,
    ) -> None:
        super().__init__()

        self._database = database
        self._on_success = on_success

        self.title("Auto Click by ]BETANO - Login")
        self.geometry("460x500")
        self.resizable(False, False)

        bg = "#0E0F22"
        surface = "#17192D"
        orange = "#FF3D00"
        white = "#FFFFFF"
        muted = "#A7A9B8"
        self.configure(fg_color=bg)

        self.protocol(
            "WM_DELETE_WINDOW",
            self.destroy,
        )

        frame = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color=surface,
            border_width=1,
            border_color="#2B2E49",
        )

        frame.pack(
            fill="both",
            expand=True,
            padx=28,
            pady=28,
        )

        base_dir = Path(
            getattr(
                sys,
                "_MEIPASS",
                Path(__file__).resolve().parent.parent,
            ),
        )
        logo_path = base_dir / "assets" / "betano_logo.png"
        self._logo_image = None
        if logo_path.exists():
            logo = Image.open(logo_path)
            self._logo_image = ctk.CTkImage(
                light_image=logo,
                dark_image=logo,
                size=(58, 58),
            )

        ctk.CTkLabel(
            frame,
            text="" if self._logo_image else "B",
            image=self._logo_image,
            text_color=white,
            fg_color=orange,
            corner_radius=14,
            width=64,
            height=64,
        ).pack(pady=(26, 10))

        ctk.CTkLabel(
            frame,
            text="AUTO CLICK BY ]BETANO",
            text_color=orange,
            font=ctk.CTkFont(size=22, weight="bold"),
        ).pack(pady=(0, 4))

        ctk.CTkLabel(
            frame,
            text="Faça login para continuar",
            text_color=muted,
            font=ctk.CTkFont(size=12),
        ).pack(pady=(0, 18))

        self._login = ctk.CTkEntry(
            frame,
            placeholder_text="Login",
            width=280,
        )

        self._login.pack(
            pady=6,
        )

        self._password = ctk.CTkEntry(
            frame,
            placeholder_text="Senha",
            show="*",
            width=280,
        )

        self._password.pack(
            pady=6,
        )

        self._message = StringVar(
            value="",
        )

        ctk.CTkLabel(
            frame,
            textvariable=self._message,
            text_color="#D35454",
            wraplength=300,
        ).pack(
            pady=8,
        )

        ctk.CTkButton(
            frame,
            text="ENTRAR",
            width=280,
            height=40,
            fg_color=orange,
            hover_color="#D83200",
            text_color=white,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self._submit,
        ).pack(
            pady=4,
        )

        self.bind(
            "<Return>",
            lambda _event: self._submit(),
        )

        self._login.focus_set()

    def _submit(self) -> None:
        try:
            user = self._database.authenticate(
                self._login.get(),
                self._password.get(),
            )

        except AuthError as exc:
            self._message.set(
                str(exc),
            )

            self._password.delete(
                0,
                END,
            )

            return

        self._on_success(
            self,
            user,
        )


class UserEditor(ctk.CTkToplevel):
    """Editor completo de um usuário selecionado."""

    def __init__(
        self,
        panel: "AdminPanel",
        user: UserRecord,
    ) -> None:
        super().__init__(panel)

        self._panel = panel
        self._user = user

        self.title(
            f"Editar usuário - {user.login}",
        )

        self.geometry(
            "520x560",
        )

        self.resizable(
            False,
            False,
        )

        self.transient(panel)
        self.grab_set()

        ctk.CTkLabel(
            self,
            text=f"Editando: {user.login}",
            font=ctk.CTkFont(
                size=20,
                weight="bold",
            ),
        ).pack(
            pady=(20, 14),
        )

        self._login = ctk.CTkEntry(
            self,
            placeholder_text="Login",
            width=360,
        )

        self._login.insert(
            0,
            user.login,
        )

        self._login.pack(
            pady=6,
        )

        self._password = ctk.CTkEntry(
            self,
            placeholder_text=(
                "Nova senha "
                "(deixe vazio para manter)"
            ),
            show="*",
            width=360,
        )

        self._password.pack(
            pady=6,
        )

        self._key = ctk.CTkEntry(
            self,
            placeholder_text=(
                "Nova chave "
                "(vazio = não alterar)"
            ),
            width=360,
        )

        self._key.pack(
            pady=6,
        )

        row = ctk.CTkFrame(
            self,
            fg_color="transparent",
        )

        row.pack(
            pady=6,
        )

        self._days = ctk.CTkEntry(
            row,
            placeholder_text="Dias da licença",
            width=160,
        )

        if (
            user.expires_at
            and user.starts_at
        ):
            current_days = max(
                1,
                (
                    user.expires_at
                    - user.starts_at
                ).days,
            )

            self._days.insert(
                0,
                str(current_days),
            )

        self._days.pack(
            side="left",
            padx=4,
        )

        self._rule = ctk.CTkComboBox(
            row,
            values=[
                "No momento da criação",
                "No primeiro login",
            ],
            width=230,
        )

        self._rule.set(
            (
                "No primeiro login"
                if user.start_rule
                == RULE_FIRST_LOGIN
                else "No momento da criação"
            ),
        )

        self._rule.pack(
            side="left",
            padx=4,
        )

        self._unlimited = ctk.CTkCheckBox(
            self,
            text="Licença ilimitada",
        )

        if user.unlimited:
            self._unlimited.select()

        self._unlimited.pack(
            pady=8,
        )

        ctk.CTkButton(
            self,
            text="Salvar todas as alterações",
            command=self._save,
        ).pack(
            fill="x",
            padx=70,
            pady=(12, 6),
        )

        ctk.CTkButton(
            self,
            text="Adicionar dias",
            command=lambda: self._adjust(True),
        ).pack(
            fill="x",
            padx=70,
            pady=4,
        )

        ctk.CTkButton(
            self,
            text="Diminuir dias",
            command=lambda: self._adjust(False),
        ).pack(
            fill="x",
            padx=70,
            pady=4,
        )

        ctk.CTkButton(
            self,
            text="Gerar nova chave",
            command=self._generate_key,
        ).pack(
            fill="x",
            padx=70,
            pady=4,
        )

        ctk.CTkButton(
            self,
            text="Revogar chave",
            command=self._revoke_key,
        ).pack(
            fill="x",
            padx=70,
            pady=4,
        )

        ctk.CTkButton(
            self,
            text="Suspender / reativar",
            command=self._toggle_account,
        ).pack(
            fill="x",
            padx=70,
            pady=4,
        )

        ctk.CTkButton(
            self,
            text="Fechar",
            fg_color="transparent",
            border_width=1,
            command=self.destroy,
        ).pack(
            fill="x",
            padx=70,
            pady=(12, 4),
        )

    def _run(
        self,
        operation,
    ) -> bool:
        try:
            operation()
            self._panel._refresh()
            return True

        except (
            AuthError,
            ValueError,
        ) as exc:
            messagebox.showerror(
                "Operação não realizada",
                str(exc),
                parent=self,
            )

            return False

    def _save(self) -> None:
        def operation():
            new_login = self._login.get().strip()

            if new_login != self._user.login:
                self._panel._db.change_login(
                    self._panel._admin.id,
                    self._user.id,
                    new_login,
                )

            new_password = self._password.get()

            if new_password:
                self._panel._db.reset_password(
                    self._panel._admin.id,
                    self._user.id,
                    new_password,
                )

            new_key = self._key.get().strip()

            if new_key:
                self._panel._db.replace_key(
                    self._panel._admin.id,
                    self._user.id,
                    new_key,
                )

            unlimited = bool(
                self._unlimited.get(),
            )

            if unlimited:
                self._panel._db.update_license(
                    self._panel._admin.id,
                    self._user.id,
                    unlimited=True,
                )

            else:
                days_text = self._days.get().strip()

                if not days_text:
                    raise AuthError(
                        "Informe a quantidade de dias.",
                    )

                days = int(
                    days_text,
                )

                if days <= 0:
                    raise AuthError(
                        "Informe uma quantidade "
                        "positiva de dias.",
                    )

                rule = (
                    RULE_FIRST_LOGIN
                    if self._rule.get()
                    == "No primeiro login"
                    else RULE_CREATION
                )

                self._panel._db.update_license(
                    self._panel._admin.id,
                    self._user.id,
                    days=days,
                    start_rule=rule,
                )

        if self._run(operation):
            self.destroy()

    def _adjust(
        self,
        increase: bool,
    ) -> None:
        def operation():
            amount_text = self._days.get().strip()

            if not amount_text:
                raise AuthError(
                    "Informe a quantidade de dias.",
                )

            amount = int(
                amount_text,
            )

            if amount <= 0:
                raise AuthError(
                    "Informe uma quantidade "
                    "positiva de dias.",
                )

            delta = (
                amount
                if increase
                else -amount
            )

            self._panel._db.adjust_license_days(
                self._panel._admin.id,
                self._user.id,
                delta,
            )

        self._run(operation)

    def _generate_key(self) -> None:
        def operation():
            key = self._panel._db.replace_key(
                self._panel._admin.id,
                self._user.id,
            )

            messagebox.showinfo(
                "Nova chave",
                (
                    "Guarde esta chave agora:\n\n"
                    f"{key}"
                ),
                parent=self,
            )

        self._run(operation)

    def _revoke_key(self) -> None:
        self._run(
            lambda: self._panel._db.revoke_key(
                self._panel._admin.id,
                self._user.id,
            ),
        )

    def _toggle_account(self) -> None:
        users = self._panel._db.list_users(
            self._panel._admin.id,
        )

        user = next(
            item
            for item in users
            if item.id == self._user.id
        )

        self._run(
            lambda: self._panel._db.set_suspended(
                self._panel._admin.id,
                self._user.id,
                user.account_status == "active",
            ),
        )


class AdminPanel(ctk.CTk):
    """Painel exclusivo para administradores."""

    def __init__(
        self,
        database,
        admin: UserRecord,
        on_logout,
    ) -> None:
        super().__init__()

        self._db = database
        self._admin = admin
        self._on_logout = on_logout
        self._selected_id: str | None = None

        self.title(
            "Auto Click by ]BETANO - Painel administrativo",
        )

        self.geometry(
            "1120x700",
        )

        self.minsize(
            900,
            580,
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self._logout,
        )

        self._build()
        self._refresh()

    def _build(self) -> None:
        top = ctk.CTkFrame(
            self,
        )

        top.pack(
            fill="x",
            padx=16,
            pady=(16, 8),
        )

        ctk.CTkLabel(
            top,
            text=(
                "Auto Click by ]BETANO | "
                "Painel administrativo"
            ),
            font=ctk.CTkFont(
                size=22,
                weight="bold",
            ),
        ).pack(
            side="left",
            padx=14,
            pady=12,
        )

        ctk.CTkButton(
            top,
            text="Encerrar sessão",
            width=140,
            command=self._logout,
        ).pack(
            side="right",
            padx=14,
        )

        table_frame = ctk.CTkFrame(
            self,
        )

        table_frame.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=8,
        )

        columns = (
            "login",
            "role",
            "status",
            "license",
            "expires",
            "days",
            "key",
        )

        self._tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            height=12,
        )

        headings = {
            "login": "Login",
            "role": "Perfil",
            "status": "Conta",
            "license": "Licença",
            "expires": "Expiração",
            "days": "Dias",
            "key": "Chave",
        }

        for column in columns:
            self._tree.heading(
                column,
                text=headings[column],
            )

            self._tree.column(
                column,
                width=130,
                anchor="center",
            )

        self._tree.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        self._tree.bind(
            "<<TreeviewSelect>>",
            self._select,
        )

        self._tree.bind(
            "<Double-1>",
            self._open_editor,
        )

        form = ctk.CTkFrame(
            self,
        )

        form.pack(
            fill="x",
            padx=16,
            pady=8,
        )

        self._login = ctk.CTkEntry(
            form,
            placeholder_text="Login",
            width=150,
        )

        self._password = ctk.CTkEntry(
            form,
            placeholder_text=(
                "Senha inicial / nova senha"
            ),
            show="*",
            width=180,
        )

        self._key = ctk.CTkEntry(
            form,
            placeholder_text="Chave de acesso",
            width=180,
        )

        self._days = ctk.CTkEntry(
            form,
            placeholder_text="Dias",
            width=80,
        )

        self._rule = ctk.CTkComboBox(
            form,
            values=[
                "No momento da criação",
                "No primeiro login",
            ],
            width=180,
        )

        self._rule.set(
            "No momento da criação",
        )

        self._unlimited = ctk.CTkCheckBox(
            form,
            text="Ilimitado",
        )

        for widget in (
            self._login,
            self._password,
            self._key,
            self._days,
            self._rule,
            self._unlimited,
        ):
            widget.pack(
                side="left",
                padx=4,
                pady=10,
            )

        actions = ctk.CTkFrame(
            self,
        )

        actions.pack(
            fill="x",
            padx=16,
            pady=(0, 16),
        )

        buttons = [
            (
                "Criar usuário",
                self._create,
            ),
            (
                "Redefinir senha",
                self._reset_password,
            ),
            (
                "Gerar/substituir chave",
                self._replace_key,
            ),
            (
                "Revogar chave",
                self._revoke_key,
            ),
            (
                "Suspender/ativar",
                self._toggle_suspended,
            ),
            (
                "Adicionar dias",
                self._add_days,
            ),
            (
                "Ilimitado",
                self._set_unlimited,
            ),
            (
                "Minhas credenciais",
                self._change_own_credentials,
            ),
            (
                "Excluir usuário",
                self._delete,
            ),
        ]

        for text, command in buttons:
            ctk.CTkButton(
                actions,
                text=text,
                command=command,
                width=125,
            ).pack(
                side="left",
                padx=3,
                pady=8,
            )

        self._status = StringVar(
            value=(
                "Selecione um usuário para editar."
            ),
        )

        ctk.CTkLabel(
            self,
            textvariable=self._status,
            anchor="w",
        ).pack(
            fill="x",
            padx=20,
            pady=(0, 12),
        )

    def _selected(self) -> str:
        if self._selected_id is None:
            raise AuthError(
                "Selecione um usuário na tabela.",
            )

        return self._selected_id

    def _select(
        self,
        _event=None,
    ) -> None:
        selected = self._tree.selection()

        self._selected_id = (
            str(selected[0])
            if selected
            else None
        )

    def _open_editor(
        self,
        _event=None,
    ) -> None:
        selected = self._tree.selection()

        if not selected:
            return

        user_id = str(
            selected[0],
        )

        user = next(
            (
                item
                for item in self._db.list_users(
                    self._admin.id,
                )
                if item.id == user_id
            ),
            None,
        )

        if user is not None:
            UserEditor(
                self,
                user,
            )

    def _refresh(self) -> None:
        for item in self._tree.get_children():
            self._tree.delete(item)

        for user in self._db.list_users(
            self._admin.id,
        ):
            license_info = self._db.license_info(
                user,
            )

            expiry = (
                user.expires_at.strftime(
                    "%d/%m/%Y",
                )
                if user.expires_at
                else "-"
            )

            days = (
                "-"
                if license_info.days_remaining
                is None
                else str(
                    license_info.days_remaining,
                )
            )

            key = (
                "REVOGADA"
                if user.key_revoked
                else "ATIVA"
            )

            self._tree.insert(
                "",
                "end",
                iid=str(user.id),
                values=(
                    user.login,
                    (
                        "ADMIN"
                        if user.role == ROLE_ADMIN
                        else "USUÁRIO"
                    ),
                    user.account_status.upper(),
                    license_info.status,
                    expiry,
                    days,
                    key,
                ),
            )

    def _run(
        self,
        operation,
    ) -> None:
        try:
            operation()
            self._refresh()

        except AuthError as exc:
            messagebox.showerror(
                "Operação não realizada",
                str(exc),
                parent=self,
            )

    def _create(self) -> None:
        def operation():
            login = self._login.get().strip()
            password = self._password.get()

            key = (
                self._key.get().strip()
                or generate_access_key()
            )

            unlimited = bool(
                self._unlimited.get(),
            )

            days = (
                None
                if unlimited
                else int(
                    self._days.get().strip(),
                )
            )

            rule = (
                RULE_FIRST_LOGIN
                if self._rule.get()
                == "No primeiro login"
                else RULE_CREATION
            )

            self._db.create_user(
                self._admin.id,
                login,
                password,
                key,
                days,
                rule,
                unlimited,
            )

            self._status.set(
                (
                    "Usuário criado. "
                    f"Chave gerada: {key}"
                )
            )

        self._run(operation)

    def _reset_password(self) -> None:
        self._run(
            lambda: self._db.reset_password(
                self._admin.id,
                self._selected(),
                self._password.get(),
            ),
        )

        self._status.set(
            (
                "Senha redefinida; "
                "a senha antiga não é exibida."
            )
        )

    def _replace_key(self) -> None:
        def operation():
            key = self._db.replace_key(
                self._admin.id,
                self._selected(),
                self._key.get().strip()
                or None,
            )

            self._status.set(
                (
                    "Nova chave gerada "
                    f"(guarde agora): {key}"
                )
            )

        self._run(operation)

    def _revoke_key(self) -> None:
        self._run(
            lambda: self._db.revoke_key(
                self._admin.id,
                self._selected(),
            ),
        )

    def _toggle_suspended(self) -> None:
        user_id = self._selected()

        user = next(
            user
            for user in self._db.list_users(
                self._admin.id,
            )
            if user.id == user_id
        )

        self._run(
            lambda: self._db.set_suspended(
                self._admin.id,
                user_id,
                user.account_status == "active",
            ),
        )

    def _add_days(self) -> None:
        days = int(
            self._days.get().strip(),
        )

        self._run(
            lambda: self._db.update_license(
                self._admin.id,
                self._selected(),
                days=days,
                add_days=True,
            ),
        )

    def _set_unlimited(self) -> None:
        self._run(
            lambda: self._db.update_license(
                self._admin.id,
                self._selected(),
                unlimited=True,
            ),
        )

    def _change_own_credentials(self) -> None:
        def operation():
            new_password = (
                self._password.get().strip()
                or None
            )

            new_key = (
                self._key.get().strip()
                or None
            )

            generated = (
                self._db.change_own_credentials(
                    self._admin.id,
                    new_password,
                    new_key,
                )
            )

            self._status.set(
                "Credenciais administrativas "
                "atualizadas."
                + (
                    f" Nova chave: {generated}"
                    if generated
                    else ""
                )
            )

        self._run(operation)

    def _delete(self) -> None:
        try:
            user_id = self._selected()

            confirmed = messagebox.askyesno(
                "Confirmar exclusão",
                (
                    "Excluir este usuário e "
                    "seu histórico?"
                ),
                parent=self,
            )

            if confirmed:
                self._db.delete_user(
                    self._admin.id,
                    user_id,
                )

                self._selected_id = None
                self._refresh()

        except AuthError as exc:
            messagebox.showerror(
                "Operação não realizada",
                str(exc),
                parent=self,
            )

    def _logout(self) -> None:
        self.destroy()
        self._on_logout()


def run_login() -> None:
    """Abre login e encaminha cada perfil."""

    try:
        database = SupabaseClient()

    except SupabaseClientError:
        database = AuthDatabase()

    def success(
        login_window: LoginWindow,
        user: UserRecord,
    ) -> None:
        login_window.destroy()

        if user.role == ROLE_ADMIN:
            AdminPanel(
                database,
                user,
                run_login,
            ).mainloop()

        else:
            from .interface import App

            remote_license = None

            try:
                remote_license = database.license_info(
                    user,
                )

            except Exception:
                pass

            App(
                user,
                remote_license,
            ).mainloop()

    LoginWindow(
        database,
        success,
    ).mainloop()

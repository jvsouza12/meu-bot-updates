"""Cliente remoto do Supabase para o FF DO 100."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .auth_db import (
    ACCOUNT_ACTIVE,
    AuthError,
    ROLE_ADMIN,
    UserRecord,
    from_db_time,
)


DEFAULT_SUPABASE_URL = "https://uabfgbmdjuuzcsfvjgge.supabase.co"
# Esta é a chave pública anon do projeto. Ela pode ser distribuída no EXE.
# Nunca coloque aqui a service_role ou uma chave sb_secret_...
DEFAULT_SUPABASE_ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVhYmZnYm1kanV1emNzZnZqZ2dlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTMwMjM4MjksImV4cCI6MjEwODU5OTgyOX0."
    "XnLe8P0e9eOj5bN61FNJ-jVg41qhfMRSm4k-1KFr7sk"
)
DEFAULT_CREATE_USER_FUNCTION = "bright-action"
DEFAULT_LOGIN_FUNCTION = "hyper-responder"
DEFAULT_LIST_USERS_FUNCTION = "swift-endpoint"
DEFAULT_UPDATE_USER_FUNCTION = "swift-function"
DEFAULT_ADJUST_LICENSE_FUNCTION = "quick-processor"
DEFAULT_SUSPEND_USER_FUNCTION = "clever-action"
DEFAULT_DELETE_USER_FUNCTION = "rapid-responder"


class SupabaseClientError(AuthError):
    """Erro esperado de comunicação ou autenticação remota."""


@dataclass(frozen=True)
class RemoteLicense:
    status: str
    starts_at: datetime | None
    expires_at: datetime | None
    days_remaining: int | None
    unlimited: bool
    key_revoked: bool


@dataclass(frozen=True)
class RemoteLoginResult:
    user: UserRecord
    license: RemoteLicense
    access_token: str
    refresh_token: str | None


class SupabaseClient:
    """Cliente das Edge Functions remotas do Supabase."""

    def __init__(
        self,
        base_url: str | None = None,
        anon_key: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        config = self._read_config()

        self.base_url = (
            base_url
            or os.environ.get("SUPABASE_URL")
            or config.get("supabase_url")
            or DEFAULT_SUPABASE_URL
        ).rstrip("/")

        self.anon_key = (
            anon_key
            or os.environ.get("SUPABASE_ANON_KEY")
            or os.environ.get("SUPABASE_PUBLISHABLE_KEY")
            or config.get("supabase_anon_key")
            or config.get("anon_key")
            or DEFAULT_SUPABASE_ANON_KEY
        )

        if not self.anon_key:
            raise SupabaseClientError(
                "Chave anon do Supabase não configurada. "
                "Configure o arquivo supabase.json."
            )

        self.login_function = os.environ.get(
            "FFDO_LOGIN_FUNCTION",
            config.get("login_function", DEFAULT_LOGIN_FUNCTION),
        )
        self.create_user_function = os.environ.get(
            "FFDO_CREATE_USER_FUNCTION",
            config.get("create_user_function", DEFAULT_CREATE_USER_FUNCTION),
        )
        self.list_users_function = os.environ.get(
            "FFDO_LIST_USERS_FUNCTION",
            config.get("list_users_function", DEFAULT_LIST_USERS_FUNCTION),
        )
        self.update_user_function = os.environ.get(
            "FFDO_UPDATE_USER_FUNCTION",
            config.get("update_user_function", DEFAULT_UPDATE_USER_FUNCTION),
        )
        self.adjust_license_function = os.environ.get(
            "FFDO_ADJUST_LICENSE_FUNCTION",
            config.get(
                "adjust_license_function",
                DEFAULT_ADJUST_LICENSE_FUNCTION,
            ),
        )
        self.suspend_user_function = os.environ.get(
            "FFDO_SUSPEND_USER_FUNCTION",
            config.get(
                "suspend_user_function",
                DEFAULT_SUSPEND_USER_FUNCTION,
            ),
        )
        self.delete_user_function = os.environ.get(
            "FFDO_DELETE_USER_FUNCTION",
            config.get("delete_user_function", DEFAULT_DELETE_USER_FUNCTION),
        )

        self.timeout = timeout
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._last_login: RemoteLoginResult | None = None
        self._licenses: dict[str, RemoteLicense] = {}

    @staticmethod
    def config_path() -> Path:
        if os.name == "nt":
            root = Path(
                os.environ.get(
                    "APPDATA",
                    Path.home() / "AppData" / "Roaming",
                )
            )
        else:
            root = Path(
                os.environ.get(
                    "XDG_CONFIG_HOME",
                    Path.home() / ".config",
                )
            )

        return root / "FF DO 100" / "supabase.json"

    @classmethod
    def _read_config(cls) -> dict[str, str]:
        try:
            path = cls.config_path()
            if not path.exists():
                return {}

            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {}

            return {
                str(key): str(value)
                for key, value in data.items()
                if value is not None
            }
        except (OSError, ValueError, TypeError):
            return {}

    @classmethod
    def write_public_config(
        cls,
        anon_key: str,
        base_url: str = DEFAULT_SUPABASE_URL,
    ) -> Path:
        anon_key = anon_key.strip()
        if not anon_key:
            raise SupabaseClientError(
                "A chave anon não pode estar vazia."
            )

        path = cls.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "supabase_url": base_url.rstrip("/"),
                    "supabase_anon_key": anon_key,
                    "login_function": DEFAULT_LOGIN_FUNCTION,
                    "create_user_function": DEFAULT_CREATE_USER_FUNCTION,
                    "list_users_function": DEFAULT_LIST_USERS_FUNCTION,
                    "update_user_function": DEFAULT_UPDATE_USER_FUNCTION,
                    "adjust_license_function": DEFAULT_ADJUST_LICENSE_FUNCTION,
                    "suspend_user_function": DEFAULT_SUSPEND_USER_FUNCTION,
                    "delete_user_function": DEFAULT_DELETE_USER_FUNCTION,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def _url(self, function_name: str) -> str:
        return f"{self.base_url}/functions/v1/{function_name}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "apikey": self.anon_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        return headers

    def _post(
        self,
        function_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not function_name:
            raise SupabaseClientError(
                "Nome da Edge Function não configurado."
            )

        try:
            response = requests.post(
                self._url(function_name),
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise SupabaseClientError(
                "O Supabase demorou demais para responder."
            ) from exc
        except requests.ConnectionError as exc:
            raise SupabaseClientError(
                "Não foi possível conectar ao Supabase. "
                "Verifique a internet."
            ) from exc
        except requests.RequestException as exc:
            raise SupabaseClientError(
                "Erro de comunicação com o Supabase."
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            text = response.text.strip()
            raise SupabaseClientError(
                text[:300]
                if text
                else "O Supabase retornou uma resposta inválida."
            ) from exc

        if not isinstance(data, dict):
            raise SupabaseClientError(
                "Resposta inesperada do Supabase."
            )

        if not response.ok:
            message = (
                data.get("error")
                or data.get("message")
                or data.get("msg")
            )

            if response.status_code == 401:
                message = message or (
                    "Sessão expirada. Faça login novamente."
                )
            elif response.status_code == 403:
                message = message or (
                    "Você não possui permissão para esta operação."
                )
            elif response.status_code == 404:
                message = message or (
                    "Edge Function não encontrada."
                )

            raise SupabaseClientError(
                str(
                    message
                    or f"Supabase retornou HTTP {response.status_code}."
                )
            )

        return data

    def _require_admin_session(self) -> None:
        if not self._access_token:
            raise SupabaseClientError(
                "Faça login como administrador antes de executar "
                "esta operação."
            )

    def authenticate(
        self,
        login: str,
        password: str,
    ) -> UserRecord:
        login = login.strip()
        if not login or not password:
            raise SupabaseClientError(
                "Informe o login e a senha."
            )

        data = self._post(
            self.login_function,
            {"login": login, "password": password},
        )

        raw_user = data.get("user")
        raw_license = data.get("license")
        token = data.get("access_token")

        if not isinstance(raw_user, dict):
            raise SupabaseClientError(
                "A resposta de login não contém o usuário."
            )
        if not isinstance(raw_license, dict):
            raise SupabaseClientError(
                "A resposta de login não contém a licença."
            )
        if not isinstance(token, str) or not token:
            raise SupabaseClientError(
                "A resposta de login não contém um token válido."
            )

        user = UserRecord(
            id=str(raw_user.get("id", "")),
            login=str(raw_user.get("login") or login),
            role=str(raw_user.get("role", "user")),
            account_status=str(
                raw_user.get("account_status", ACCOUNT_ACTIVE)
            ),
            created_at=(
                from_db_time(raw_user.get("created_at"))
                or datetime.now().astimezone()
            ),
            start_rule=str(
                raw_license.get("start_rule", "first_login")
            ),
            starts_at=from_db_time(raw_license.get("starts_at")),
            expires_at=from_db_time(raw_license.get("expires_at")),
            unlimited=bool(raw_license.get("unlimited", False)),
            key_revoked=bool(raw_license.get("key_revoked", True)),
            last_login_at=from_db_time(
                raw_user.get("last_login_at")
            ),
        )

        raw_days = raw_license.get("days_remaining")
        try:
            days_remaining = (
                int(raw_days) if raw_days is not None else None
            )
        except (TypeError, ValueError):
            days_remaining = None

        license_info = RemoteLicense(
            status=str(raw_license.get("status", "ATIVO")),
            starts_at=user.starts_at,
            expires_at=user.expires_at,
            days_remaining=days_remaining,
            unlimited=user.unlimited,
            key_revoked=user.key_revoked,
        )

        self._access_token = token
        self._refresh_token = (
            str(data["refresh_token"])
            if data.get("refresh_token")
            else None
        )
        self._last_login = RemoteLoginResult(
            user=user,
            license=license_info,
            access_token=token,
            refresh_token=self._refresh_token,
        )

        return user

    def license_info(self, user: UserRecord) -> RemoteLicense:
        if (
            self._last_login
            and str(self._last_login.user.id) == str(user.id)
        ):
            return self._last_login.license

        if str(user.id) in self._licenses:
            return self._licenses[str(user.id)]

        return self._license_from_user(user)

    def create_user(
        self,
        actor_id,
        login: str,
        password: str,
        access_key: str | None,
        days: int | None,
        start_rule: str,
        unlimited: bool = False,
    ) -> dict[str, Any]:
        """Cria usuário e garante que a chave exibida é a remota."""

        self._require_admin_session()

        result = self._post(
            self.create_user_function,
            {
                "login": str(login).strip(),
                "password": str(password),
                "days": days,
                "unlimited": bool(unlimited),
                "start_rule": start_rule,
            },
        )

        user_id = result.get("user_id")
        if not user_id:
            raise SupabaseClientError(
                "O usuário foi criado, mas a Edge Function não retornou "
                "o user_id."
            )

        # O auth_ui.py antigo gera uma chave local antes de chamar este
        # método. Neste caso, grava essa mesma chave no Supabase através
        # da swift-function e guarda a string corretamente em access_key.
        if access_key and str(access_key).strip():
            remote_key = self.replace_key(
                actor_id=actor_id,
                user_id=str(user_id),
                new_key=str(access_key).strip(),
            )
            result["access_key"] = remote_key
            result["key_revoked"] = False
        else:
            remote_key = result.get("access_key")
            if not isinstance(remote_key, str) or not remote_key.strip():
                raise SupabaseClientError(
                    "O usuário foi criado, mas nenhuma chave foi retornada."
                )
            result["access_key"] = remote_key.strip()

        return result

    def list_users(self, actor_id=None) -> list[UserRecord]:
        self._require_admin_session()
        data = self._post(self.list_users_function, {})
        raw_users = data.get("users", [])

        if not isinstance(raw_users, list):
            raise SupabaseClientError(
                "A resposta de usuários do Supabase é inválida."
            )

        result: list[UserRecord] = []
        for item in raw_users:
            if not isinstance(item, dict):
                continue

            license_data = self._extract_license(item)
            user = self._user_from_remote(item, license_data)
            result.append(user)
            self._licenses[str(user.id)] = (
                self._license_from_remote(license_data, user)
            )

        return result

    def update_user(
        self,
        user_id: str,
        login: str | None = None,
        password: str | None = None,
        days: int | None = None,
        unlimited: bool | None = None,
        start_rule: str | None = None,
    ) -> dict[str, Any]:
        self._require_admin_session()

        payload: dict[str, Any] = {
            "action": "update",
            "user_id": str(user_id),
        }

        for key, value in (
            ("login", login),
            ("password", password),
            ("days", days),
            ("unlimited", unlimited),
            ("start_rule", start_rule),
        ):
            if value is not None:
                payload[key] = value

        return self._post(self.update_user_function, payload)

    def reset_password(
        self,
        actor_id,
        user_id,
        new_password: str,
    ) -> dict[str, Any]:
        if not new_password:
            raise SupabaseClientError(
                "Informe a nova senha."
            )
        return self.update_user(
            str(user_id),
            password=new_password,
        )

    def change_login(
        self,
        actor_id,
        user_id,
        new_login: str,
    ) -> dict[str, Any]:
        new_login = new_login.strip()
        if not new_login:
            raise SupabaseClientError(
                "Informe o novo login."
            )
        return self.update_user(
            str(user_id),
            login=new_login,
        )

    def update_license(
        self,
        actor_id,
        user_id,
        days: int | None = None,
        unlimited: bool = False,
        start_rule: str | None = None,
        add_days: bool = False,
    ) -> dict[str, Any]:
        if add_days and days is not None:
            return self.adjust_license_days(
                actor_id,
                str(user_id),
                days,
            )

        return self.update_user(
            str(user_id),
            days=days,
            unlimited=unlimited,
            start_rule=start_rule,
        )

    def adjust_license_days(
        self,
        actor_id,
        user_id: str,
        delta_days: int,
    ) -> dict[str, Any]:
        self._require_admin_session()
        if not isinstance(delta_days, int) or delta_days == 0:
            raise SupabaseClientError(
                "A quantidade de dias deve ser um inteiro diferente de zero."
            )

        return self._post(
            self.adjust_license_function,
            {
                "user_id": str(user_id),
                "delta_days": delta_days,
            },
        )

    def set_suspended(
        self,
        actor_id,
        user_id: str,
        suspended: bool,
    ) -> dict[str, Any]:
        self._require_admin_session()
        return self._post(
            self.suspend_user_function,
            {
                "user_id": str(user_id),
                "suspended": bool(suspended),
            },
        )

    def delete_user(self, actor_id, user_id) -> dict[str, Any]:
        self._require_admin_session()
        return self._post(
            self.delete_user_function,
            {"user_id": str(user_id)},
        )

    def replace_key(
        self,
        actor_id,
        user_id: str,
        new_key: str | None = None,
    ) -> str:
        """Gera ou grava uma chave e retorna a chave completa."""

        self._require_admin_session()
        payload: dict[str, Any] = {
            "action": "replace_key",
            "user_id": str(user_id),
        }

        if new_key and str(new_key).strip():
            payload["new_key"] = str(new_key).strip()

        data = self._post(
            self.update_user_function,
            payload,
        )
        access_key = data.get("access_key")

        if not isinstance(access_key, str) or not access_key.strip():
            raise SupabaseClientError(
                "A Edge Function não retornou a nova chave."
            )

        return access_key.strip()

    def revoke_key(
        self,
        actor_id,
        user_id: str,
    ) -> dict[str, Any]:
        self._require_admin_session()
        return self._post(
            self.update_user_function,
            {
                "action": "revoke_key",
                "user_id": str(user_id),
            },
        )

    def change_own_credentials(
        self,
        actor_id,
        new_password: str | None = None,
        new_key: str | None = None,
    ) -> str | None:
        if not new_password and not new_key:
            raise SupabaseClientError(
                "Informe uma nova senha ou uma nova chave."
            )

        if new_password:
            self.update_user(
                str(actor_id),
                password=new_password,
            )

        if new_key:
            return self.replace_key(
                actor_id,
                str(actor_id),
                new_key,
            )

        return None

    @staticmethod
    def _extract_license(item: dict[str, Any]) -> dict[str, Any]:
        relation = item.get("licenses")
        if relation is None:
            relation = item.get("license")

        if isinstance(relation, list):
            return (
                relation[0]
                if relation and isinstance(relation[0], dict)
                else {}
            )
        if isinstance(relation, dict):
            return relation
        return {}

    @staticmethod
    def _user_from_remote(
        item: dict[str, Any],
        license_data: dict[str, Any],
    ) -> UserRecord:
        return UserRecord(
            id=str(item.get("id", "")),
            login=str(item.get("login", "")),
            role=str(item.get("role", "user")),
            account_status=str(
                item.get("account_status", ACCOUNT_ACTIVE)
            ),
            created_at=(
                from_db_time(item.get("created_at"))
                or datetime.now().astimezone()
            ),
            start_rule=str(
                license_data.get("start_rule", "first_login")
            ),
            starts_at=from_db_time(license_data.get("starts_at")),
            expires_at=from_db_time(license_data.get("expires_at")),
            unlimited=bool(license_data.get("unlimited", False)),
            key_revoked=bool(
                license_data.get("key_revoked", True)
            ),
            last_login_at=from_db_time(
                item.get("last_login_at")
            ),
        )

    @staticmethod
    def _license_from_remote(
        data: dict[str, Any],
        user: UserRecord,
    ) -> RemoteLicense:
        if user.unlimited:
            return RemoteLicense(
                "ILIMITADO",
                user.starts_at,
                None,
                None,
                True,
                user.key_revoked,
            )

        raw_days = data.get("days_remaining")
        try:
            days = int(raw_days) if raw_days is not None else None
        except (TypeError, ValueError):
            days = None

        if days is None and user.expires_at:
            seconds = (
                user.expires_at - datetime.now().astimezone()
            ).total_seconds()
            days = max(0, int(seconds // 86400) + 1)

        if days is None:
            status = "AGUARDANDO ATIVAÇÃO"
        elif days <= 0:
            status = "EXPIRADO"
        else:
            status = "ATIVO"

        return RemoteLicense(
            status,
            user.starts_at,
            user.expires_at,
            days,
            False,
            user.key_revoked,
        )

    @staticmethod
    def _license_from_user(user: UserRecord) -> RemoteLicense:
        return SupabaseClient._license_from_remote({}, user)

    def sign_out(self) -> None:
        self._access_token = None
        self._refresh_token = None
        self._last_login = None
        self._licenses.clear()

    @property
    def access_token(self) -> str | None:
        return self._access_token

    @property
    def is_admin(self) -> bool:
        return bool(
            self._last_login
            and self._last_login.user.role == ROLE_ADMIN
        )

"""Banco de dados, autenticação e licenças do FF DO 100."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt


ADMIN_LOGIN = "FF100"
ADMIN_PASSWORD = "adminff100"
ADMIN_ACCESS_KEY = "ffdo100"

ROLE_ADMIN = "admin"
ROLE_USER = "user"

ACCOUNT_ACTIVE = "active"
ACCOUNT_SUSPENDED = "suspended"

RULE_CREATION = "creation"
RULE_FIRST_LOGIN = "first_login"


class AuthError(RuntimeError):
    """Erro de autenticação ou de operação administrativa."""


@dataclass(frozen=True)
class UserRecord:
    id: int
    login: str
    role: str
    account_status: str
    created_at: datetime
    start_rule: str
    starts_at: datetime | None
    expires_at: datetime | None
    unlimited: bool
    key_revoked: bool
    last_login_at: datetime | None


@dataclass(frozen=True)
class LicenseInfo:
    status: str
    expires_at: datetime | None
    days_remaining: int | None


def utc_now() -> datetime:
    """Retorna o horário atual em UTC."""

    return datetime.now(
        timezone.utc
    ).replace(
        microsecond=0
    )


def to_db_time(
    value: datetime | None,
) -> str | None:
    """Converte data para texto ISO."""

    if value is None:
        return None

    return value.astimezone(
        timezone.utc
    ).isoformat()


def from_db_time(
    value: str | None,
) -> datetime | None:
    """Converte texto ISO para datetime."""

    if not value:
        return None

    return datetime.fromisoformat(
        value
    ).astimezone(
        timezone.utc
    )


def key_fingerprint(value: str) -> str:
    """Gera uma impressão digital da chave."""

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


def hash_secret(value: str) -> str:
    """Cria hash bcrypt para senha ou chave."""

    return bcrypt.hashpw(
        value.encode("utf-8"),
        bcrypt.gensalt(rounds=12),
    ).decode("ascii")


def verify_secret(
    value: str,
    stored_hash: str,
) -> bool:
    """Confere senha ou chave contra o hash salvo."""

    try:
        return bcrypt.checkpw(
            value.encode("utf-8"),
            stored_hash.encode("ascii"),
        )

    except (
        ValueError,
        TypeError,
    ):
        return False


def generate_access_key() -> str:
    """Gera uma chave de acesso aleatória."""

    token = secrets.token_urlsafe(
        18
    )

    return (
        "FF-"
        + token
        .replace("-", "A")
        .replace("_", "B")
    )


class AuthDatabase:
    """Camada de persistência e regras de autenticação."""

    def __init__(
        self,
        path: Path | None = None,
    ) -> None:
        self.path = (
            Path(path)
            if path is not None
            else self.default_path()
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._failed: dict[
            str,
            list[datetime],
        ] = {}

        self._init_schema()
        self._ensure_initial_admin()

    @staticmethod
    def default_path() -> Path:
        """Retorna o caminho persistente do banco."""

        if os.name == "nt":
            root = Path(
                os.environ.get(
                    "APPDATA",
                    Path.home()
                    / "AppData"
                    / "Roaming",
                )
            )

            return (
                root
                / "FF DO 100"
                / "auth.db"
            )

        root = Path(
            os.environ.get(
                "XDG_DATA_HOME",
                Path.home()
                / ".local"
                / "share",
            )
        )

        return (
            root
            / "ff-do-100"
            / "auth.db"
        )

    def _connect(self) -> sqlite3.Connection:
        """Abre uma conexão SQLite."""

        connection = sqlite3.connect(
            self.path,
            timeout=10,
        )

        connection.row_factory = sqlite3.Row

        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        return connection

    def _init_schema(self) -> None:
        """Cria as tabelas necessárias."""

        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    login TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    key_hash TEXT NOT NULL,
                    key_fingerprint TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL
                        CHECK(role IN ('admin','user')),
                    account_status TEXT NOT NULL
                        DEFAULT 'active'
                        CHECK(account_status IN ('active','suspended')),
                    created_at TEXT NOT NULL,
                    start_rule TEXT NOT NULL
                        CHECK(start_rule IN ('creation','first_login')),
                    license_days INTEGER,
                    starts_at TEXT,
                    expires_at TEXT,
                    unlimited INTEGER NOT NULL
                        DEFAULT 0
                        CHECK(unlimited IN (0,1)),
                    key_revoked INTEGER NOT NULL
                        DEFAULT 0
                        CHECK(key_revoked IN (0,1)),
                    key_created_at TEXT NOT NULL,
                    last_login_at TEXT
                );

                CREATE TABLE IF NOT EXISTS license_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    old_expires_at TEXT,
                    new_expires_at TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    actor_user_id INTEGER,
                    action TEXT NOT NULL,
                    target_user_id INTEGER,
                    details TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(actor_user_id)
                        REFERENCES users(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY(target_user_id)
                        REFERENCES users(id)
                        ON DELETE SET NULL
                );

                CREATE INDEX IF NOT EXISTS idx_users_login
                    ON users(login);

                CREATE INDEX IF NOT EXISTS idx_audit_created
                    ON audit_log(created_at);
                """
            )

            columns = {
                row["name"]
                for row in db.execute(
                    "PRAGMA table_info(users)"
                )
            }

            if "license_days" not in columns:
                db.execute(
                    "ALTER TABLE users "
                    "ADD COLUMN license_days INTEGER"
                )

    def _ensure_initial_admin(self) -> None:
        """Cria o administrador inicial uma única vez."""

        with self._connect() as db:
            existing = db.execute(
                "SELECT id FROM users WHERE login = ?",
                (ADMIN_LOGIN,),
            ).fetchone()

            if existing:
                return

            now = utc_now()

            db.execute(
                """
                INSERT INTO users (
                    login,
                    password_hash,
                    key_hash,
                    key_fingerprint,
                    role,
                    account_status,
                    created_at,
                    start_rule,
                    license_days,
                    starts_at,
                    expires_at,
                    unlimited,
                    key_revoked,
                    key_created_at
                )
                VALUES (
                    ?,
                    ?,
                    ?,
                    ?,
                    'admin',
                    'active',
                    ?,
                    'creation',
                    NULL,
                    ?,
                    NULL,
                    1,
                    0,
                    ?
                )
                """,
                (
                    ADMIN_LOGIN,
                    hash_secret(
                        ADMIN_PASSWORD
                    ),
                    hash_secret(
                        ADMIN_ACCESS_KEY
                    ),
                    key_fingerprint(
                        ADMIN_ACCESS_KEY
                    ),
                    to_db_time(now),
                    to_db_time(now),
                    to_db_time(now),
                ),
            )

            self._audit(
                db,
                None,
                "initial_admin_created",
                None,
                "Administrador inicial criado.",
            )

    @staticmethod
    def _audit(
        db: sqlite3.Connection,
        actor_id: int | None,
        action: str,
        target_id: int | None,
        details: str = "",
    ) -> None:
        """Registra ação administrativa."""

        db.execute(
            """
            INSERT INTO audit_log (
                actor_user_id,
                action,
                target_user_id,
                details,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                actor_id,
                action,
                target_id,
                details[:500],
                to_db_time(
                    utc_now()
                ),
            ),
        )

    @staticmethod
    def _validate_login(login: str) -> str:
        """Valida o formato do login."""

        login = login.strip()

        valid = (
            3 <= len(login) <= 64
            and all(
                char.isalnum()
                or char in "._-"
                for char in login
            )
        )

        if not valid:
            raise AuthError(
                "O login deve conter de 3 a 64 "
                "caracteres alfanuméricos, ponto, "
                "hífen ou sublinhado."
            )

        return login

    @staticmethod
    def _validate_secret(
        value: str,
        label: str,
    ) -> str:
        """Valida senha ou chave."""

        if (
            not isinstance(value, str)
            or len(value) < 6
            or len(value) > 256
        ):
            raise AuthError(
                f"A {label} deve ter entre "
                "6 e 256 caracteres."
            )

        return value

    def _check_rate_limit(
        self,
        login: str,
    ) -> None:
        """Limita tentativas repetidas de login."""

        now = utc_now()

        recent = [
            item
            for item in self._failed.get(
                login.lower(),
                [],
            )
            if now - item < timedelta(
                minutes=5
            )
        ]

        self._failed[
            login.lower()
        ] = recent

        if len(recent) >= 5:
            raise AuthError(
                "Muitas tentativas. Aguarde "
                "alguns minutos e tente novamente."
            )

    def authenticate(
        self,
        login: str,
        password: str,
    ) -> UserRecord:
        """Autentica o usuário."""

        login = login.strip()

        self._check_rate_limit(
            login
        )

        with self._connect() as db:
            row = db.execute(
                """
                SELECT *
                FROM users
                WHERE login = ?
                COLLATE NOCASE
                """,
                (login,),
            ).fetchone()

            valid = bool(
                row
                and verify_secret(
                    password,
                    row["password_hash"],
                )
            )

            if not valid:
                self._failed.setdefault(
                    login.lower(),
                    [],
                ).append(
                    utc_now()
                )

                raise AuthError(
                    "Login ou senha inválidos."
                )

            if (
                row["account_status"]
                == ACCOUNT_SUSPENDED
            ):
                raise AuthError(
                    "Login ou senha inválidos."
                )

            now = utc_now()

            starts_at = from_db_time(
                row["starts_at"]
            )

            expires_at = from_db_time(
                row["expires_at"]
            )

            if (
                row["start_rule"]
                == RULE_FIRST_LOGIN
                and starts_at is None
            ):
                starts_at = now

                if not row["unlimited"]:
                    days = int(
                        row["license_days"]
                        or 1
                    )

                    expires_at = (
                        now
                        + timedelta(
                            days=days
                        )
                    )

                db.execute(
                    """
                    UPDATE users
                    SET
                        starts_at = ?,
                        expires_at = ?,
                        last_login_at = ?
                    WHERE id = ?
                    """,
                    (
                        to_db_time(starts_at),
                        to_db_time(expires_at),
                        to_db_time(now),
                        row["id"],
                    ),
                )

                self._audit(
                    db,
                    row["id"],
                    "first_login_license_started",
                    row["id"],
                )

            else:
                if (
                    not row["unlimited"]
                    and expires_at
                    and now >= expires_at
                ):
                    raise AuthError(
                        "Sua licença de automação expirou. "
                        "Procure o administrador para renovar "
                        "o acesso."
                    )

                db.execute(
                    """
                    UPDATE users
                    SET last_login_at = ?
                    WHERE id = ?
                    """,
                    (
                        to_db_time(now),
                        row["id"],
                    ),
                )

            self._failed.pop(
                login.lower(),
                None,
            )

            row = db.execute(
                "SELECT * FROM users WHERE id = ?",
                (row["id"],),
            ).fetchone()

            return self._record(row)

    @staticmethod
    def _record(
        row: sqlite3.Row,
    ) -> UserRecord:
        """Converte linha do banco em usuário."""

        return UserRecord(
            id=row["id"],
            login=row["login"],
            role=row["role"],
            account_status=row["account_status"],
            created_at=(
                from_db_time(
                    row["created_at"]
                )
                or utc_now()
            ),
            start_rule=row["start_rule"],
            starts_at=from_db_time(
                row["starts_at"]
            ),
            expires_at=from_db_time(
                row["expires_at"]
            ),
            unlimited=bool(
                row["unlimited"]
            ),
            key_revoked=bool(
                row["key_revoked"]
            ),
            last_login_at=from_db_time(
                row["last_login_at"]
            ),
        )

    def license_info(
        self,
        user: UserRecord,
    ) -> LicenseInfo:
        """Calcula o status atual da licença."""

        if (
            user.account_status
            == ACCOUNT_SUSPENDED
        ):
            return LicenseInfo(
                "SUSPENSO",
                user.expires_at,
                self._remaining(
                    user.expires_at
                ),
            )

        if user.unlimited:
            return LicenseInfo(
                "ILIMITADO",
                None,
                None,
            )

        if user.starts_at is None:
            return LicenseInfo(
                "AGUARDANDO ATIVAÇÃO",
                user.expires_at,
                None,
            )

        remaining = self._remaining(
            user.expires_at
        )

        if (
            remaining is None
            or remaining <= 0
        ):
            return LicenseInfo(
                "EXPIRADO",
                user.expires_at,
                0,
            )

        if remaining <= 3:
            return LicenseInfo(
                "EXPIRANDO",
                user.expires_at,
                remaining,
            )

        return LicenseInfo(
            "ATIVO",
            user.expires_at,
            remaining,
        )

    @staticmethod
    def _remaining(
        expires_at: datetime | None,
    ) -> int | None:
        """Calcula dias restantes usando a data real."""

        if expires_at is None:
            return None

        seconds = (
            expires_at - utc_now()
        ).total_seconds()

        return max(
            0,
            int(
                (seconds + 86399)
                // 86400
            ),
        )

    def _require_admin(
        self,
        actor_id: int,
    ) -> None:
        """Confirma permissão administrativa."""

        with self._connect() as db:
            row = db.execute(
                """
                SELECT role, account_status
                FROM users
                WHERE id = ?
                """,
                (actor_id,),
            ).fetchone()

            if (
                not row
                or row["role"] != ROLE_ADMIN
                or row["account_status"]
                != ACCOUNT_ACTIVE
            ):
                raise AuthError(
                    "Permissão administrativa necessária."
                )

    def list_users(
        self,
        actor_id: int,
    ) -> list[UserRecord]:
        """Lista todos os usuários."""

        self._require_admin(
            actor_id
        )

        with self._connect() as db:
            rows = db.execute(
                """
                SELECT *
                FROM users
                ORDER BY login COLLATE NOCASE
                """
            )

            return [
                self._record(row)
                for row in rows
            ]

    def create_user(
        self,
        actor_id: int,
        login: str,
        password: str,
        access_key: str,
        days: int | None,
        start_rule: str,
        unlimited: bool = False,
    ) -> UserRecord:
        """Cria um usuário comum."""

        self._require_admin(
            actor_id
        )

        login = self._validate_login(
            login
        )

        password = self._validate_secret(
            password,
            "senha",
        )

        access_key = self._validate_secret(
            access_key,
            "chave",
        )

        if start_rule not in (
            RULE_CREATION,
            RULE_FIRST_LOGIN,
        ):
            raise AuthError(
                "Regra de início inválida."
            )

        if (
            not unlimited
            and (
                days is None
                or days <= 0
                or days > 36500
            )
        ):
            raise AuthError(
                "Informe uma quantidade "
                "de dias positiva."
            )

        now = utc_now()

        starts_at = (
            now
            if start_rule == RULE_CREATION
            else None
        )

        expires_at = (
            starts_at
            + timedelta(days=days)
            if starts_at and not unlimited
            else None
        )

        try:
            with self._connect() as db:
                cursor = db.execute(
                    """
                    INSERT INTO users (
                        login,
                        password_hash,
                        key_hash,
                        key_fingerprint,
                        role,
                        account_status,
                        created_at,
                        start_rule,
                        license_days,
                        starts_at,
                        expires_at,
                        unlimited,
                        key_revoked,
                        key_created_at
                    )
                    VALUES (
                        ?,
                        ?,
                        ?,
                        ?,
                        'user',
                        'active',
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        ?,
                        0,
                        ?
                    )
                    """,
                    (
                        login,
                        hash_secret(password),
                        hash_secret(access_key),
                        key_fingerprint(access_key),
                        to_db_time(now),
                        start_rule,
                        days,
                        to_db_time(starts_at),
                        to_db_time(expires_at),
                        int(unlimited),
                        to_db_time(now),
                    ),
                )

                self._audit(
                    db,
                    actor_id,
                    "user_created",
                    cursor.lastrowid,
                    f"login={login}",
                )

                row = db.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (cursor.lastrowid,),
                ).fetchone()

                return self._record(row)

        except sqlite3.IntegrityError as exc:
            raise AuthError(
                "Login ou chave já cadastrados."
            ) from exc

    def update_license(
        self,
        actor_id: int,
        user_id: int,
        days: int | None = None,
        unlimited: bool = False,
        start_rule: str | None = None,
        new_expiration: datetime | None = None,
        add_days: bool = False,
    ) -> UserRecord:
        """Define, altera ou renova uma licença."""

        self._require_admin(
            actor_id
        )

        if (
            not unlimited
            and days is not None
            and (
                days <= 0
                or days > 36500
            )
        ):
            raise AuthError(
                "A quantidade de dias "
                "deve ser positiva."
            )

        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

            if not row:
                raise AuthError(
                    "Usuário não encontrado."
                )

            old_expiration = from_db_time(
                row["expires_at"]
            )

            now = utc_now()

            rule = (
                start_rule
                or row["start_rule"]
            )

            if unlimited:
                starts_at = from_db_time(
                    row["starts_at"]
                )
                expires_at = None

            elif new_expiration:
                starts_at = (
                    from_db_time(
                        row["starts_at"]
                    )
                    or now
                )
                expires_at = new_expiration

            elif add_days and days:
                base = (
                    old_expiration
                    if old_expiration
                    and old_expiration > now
                    else now
                )

                starts_at = (
                    from_db_time(
                        row["starts_at"]
                    )
                    or now
                )

                expires_at = (
                    base
                    + timedelta(
                        days=days
                    )
                )

            elif days:
                starts_at = (
                    from_db_time(
                        row["starts_at"]
                    )
                    if rule == RULE_FIRST_LOGIN
                    else now
                )

                expires_at = (
                    None
                    if starts_at is None
                    else starts_at
                    + timedelta(
                        days=days
                    )
                )

            else:
                starts_at = from_db_time(
                    row["starts_at"]
                )

                expires_at = old_expiration

            db.execute(
                """
                UPDATE users
                SET
                    start_rule = ?,
                    license_days = ?,
                    starts_at = ?,
                    expires_at = ?,
                    unlimited = ?
                WHERE id = ?
                """,
                (
                    rule,
                    days,
                    to_db_time(starts_at),
                    to_db_time(expires_at),
                    int(unlimited),
                    user_id,
                ),
            )

            db.execute(
                """
                INSERT INTO license_history (
                    user_id,
                    action,
                    old_expires_at,
                    new_expires_at,
                    note,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    "license_updated",
                    to_db_time(old_expiration),
                    to_db_time(expires_at),
                    "Alteração administrativa.",
                    to_db_time(now),
                ),
            )

            self._audit(
                db,
                actor_id,
                "license_updated",
                user_id,
                f"unlimited={int(unlimited)}",
            )

            return self._record(
                db.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            )

    def adjust_license_days(
        self,
        actor_id: int,
        user_id: int,
        delta_days: int,
    ) -> UserRecord:
        """Adiciona ou remove dias da licença."""

        self._require_admin(
            actor_id
        )

        if (
            delta_days == 0
            or abs(delta_days) > 36500
        ):
            raise AuthError(
                "A alteração de dias é inválida."
            )

        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

            if not row:
                raise AuthError(
                    "Usuário não encontrado."
                )

            if row["unlimited"]:
                raise AuthError(
                    "Uma licença ilimitada não possui "
                    "dias para ajustar."
                )

            now = utc_now()

            current_expiration = (
                from_db_time(
                    row["expires_at"]
                )
                or now
            )

            new_expiration = max(
                now,
                current_expiration
                + timedelta(
                    days=delta_days
                ),
            )

            original_start = (
                from_db_time(
                    row["starts_at"]
                )
                or now
            )

            new_license_days = max(
                1,
                (
                    new_expiration
                    - original_start
                ).days,
            )

            db.execute(
                """
                UPDATE users
                SET
                    starts_at = COALESCE(
                        starts_at,
                        ?
                    ),
                    expires_at = ?,
                    license_days = ?
                WHERE id = ?
                """,
                (
                    to_db_time(now),
                    to_db_time(new_expiration),
                    new_license_days,
                    user_id,
                ),
            )

            db.execute(
                """
                INSERT INTO license_history (
                    user_id,
                    action,
                    old_expires_at,
                    new_expires_at,
                    note,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    "license_days_adjusted",
                    to_db_time(current_expiration),
                    to_db_time(new_expiration),
                    f"Alteração de dias: {delta_days}",
                    to_db_time(now),
                ),
            )

            self._audit(
                db,
                actor_id,
                "license_days_adjusted",
                user_id,
                f"delta={delta_days}",
            )

            return self._record(
                db.execute(
                    "SELECT * FROM users WHERE id = ?",
                    (user_id,),
                ).fetchone()
            )

    def set_suspended(
        self,
        actor_id: int,
        user_id: int,
        suspended: bool,
    ) -> None:
        """Suspende ou reativa usuário comum."""

        self._require_admin(
            actor_id
        )

        with self._connect() as db:
            row = db.execute(
                "SELECT role FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

            if (
                not row
                or row["role"] == ROLE_ADMIN
            ):
                raise AuthError(
                    "A conta administrativa inicial "
                    "não pode ser suspensa."
                )

            status = (
                ACCOUNT_SUSPENDED
                if suspended
                else ACCOUNT_ACTIVE
            )

            db.execute(
                """
                UPDATE users
                SET account_status = ?
                WHERE id = ?
                """,
                (
                    status,
                    user_id,
                ),
            )

            self._audit(
                db,
                actor_id,
                (
                    "account_suspended"
                    if suspended
                    else "account_reactivated"
                ),
                user_id,
            )

    def reset_password(
        self,
        actor_id: int,
        user_id: int,
        new_password: str,
    ) -> None:
        """Redefine uma senha."""

        self._require_admin(
            actor_id
        )

        new_password = self._validate_secret(
            new_password,
            "senha",
        )

        with self._connect() as db:
            db.execute(
                """
                UPDATE users
                SET password_hash = ?
                WHERE id = ?
                """,
                (
                    hash_secret(
                        new_password
                    ),
                    user_id,
                ),
            )

            self._audit(
                db,
                actor_id,
                "password_reset",
                user_id,
            )

    def change_login(
        self,
        actor_id: int,
        user_id: int,
        new_login: str,
    ) -> None:
        """Altera o login de um usuário."""

        self._require_admin(
            actor_id
        )

        new_login = self._validate_login(
            new_login
        )

        with self._connect() as db:
            row = db.execute(
                "SELECT role FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()

            if not row:
                raise AuthError(
                    "Usuário não encontrado."
                )

            if (
                row["role"] == ROLE_ADMIN
                and user_id != actor_id
            ):
                raise AuthError(
                    "A conta administrativa só pode "
                    "ser alterada pelo próprio administrador."
                )

            try:
                db.execute(
                    """
                    UPDATE users
                    SET login = ?
                    WHERE id = ?
                    """,
                    (
                        new_login,
                        user_id,
                    ),
                )

            except sqlite3.IntegrityError as exc:
                raise AuthError(
                    "Esse login já está cadastrado."
                ) from exc

            self._audit(
                db,
                actor_id,
                "login_changed",
                user_id,
                f"login={new_login}",
            )

    def replace_key(
        self,
        actor_id: int,
        user_id: int,
        new_key: str | None = None,
    ) -> str:
        """Gera ou substitui uma chave."""

        self._require_admin(
            actor_id
        )

        new_key = (
            new_key
            or generate_access_key()
        )

        new_key = self._validate_secret(
            new_key,
            "chave",
        )

        now = utc_now()

        try:
            with self._connect() as db:
                db.execute(
                    """
                    UPDATE users
                    SET
                        key_hash = ?,
                        key_fingerprint = ?,
                        key_revoked = 0,
                        key_created_at = ?
                    WHERE id = ?
                    """,
                    (
                        hash_secret(new_key),
                        key_fingerprint(new_key),
                        to_db_time(now),
                        user_id,
                    ),
                )

                self._audit(
                    db,
                    actor_id,
                    "access_key_replaced",
                    user_id,
                )

                return new_key

        except sqlite3.IntegrityError as exc:
            raise AuthError(
                "Essa chave já está cadastrada."
            ) from exc

    def revoke_key(
        self,
        actor_id: int,
        user_id: int,
    ) -> None:
        """Revoga a chave de acesso."""

        self._require_admin(
            actor_id
        )

        with self._connect() as db:
            db.execute(
                """
                UPDATE users
                SET key_revoked = 1
                WHERE id = ?
                """,
                (user_id,),
            )

            self._audit(
                db,
                actor_id,
                "access_key_revoked",
                user_id,
            )

    def delete_user(
        self,
        actor_id: int,
        user_id: int,
    ) -> None:
        """Exclui usuário comum."""

        self._require_admin(
            actor_id
        )

        with self._connect() as db:
            row = db.execute(
                """
                SELECT role, login
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()

            if (
                not row
                or row["role"] == ROLE_ADMIN
            ):
                raise AuthError(
                    "A conta administrativa "
                    "não pode ser excluída."
                )

            db.execute(
                "DELETE FROM users WHERE id = ?",
                (user_id,),
            )

            self._audit(
                db,
                actor_id,
                "user_deleted",
                None,
                f"login={row['login']}",
            )

    def change_own_credentials(
        self,
        actor_id: int,
        new_password: str | None = None,
        new_key: str | None = None,
    ) -> str | None:
        """Permite ao administrador alterar suas credenciais."""

        self._require_admin(
            actor_id
        )

        if (
            new_password is None
            and new_key is None
        ):
            raise AuthError(
                "Informe uma nova senha ou chave."
            )

        with self._connect() as db:
            generated_key = None

            if new_password is not None:
                new_password = self._validate_secret(
                    new_password,
                    "senha",
                )

                db.execute(
                    """
                    UPDATE users
                    SET password_hash = ?
                    WHERE id = ?
                    """,
                    (
                        hash_secret(
                            new_password
                        ),
                        actor_id,
                    ),
                )

            if new_key is not None:
                new_key = self._validate_secret(
                    new_key,
                    "chave",
                )

                now = utc_now()

                try:
                    db.execute(
                        """
                        UPDATE users
                        SET
                            key_hash = ?,
                            key_fingerprint = ?,
                            key_revoked = 0,
                            key_created_at = ?
                        WHERE id = ?
                        """,
                        (
                            hash_secret(new_key),
                            key_fingerprint(new_key),
                            to_db_time(now),
                            actor_id,
                        ),
                    )

                except sqlite3.IntegrityError as exc:
                    raise AuthError(
                        "Essa chave já está cadastrada."
                    ) from exc

                generated_key = new_key

            self._audit(
                db,
                actor_id,
                "own_credentials_changed",
                actor_id,
            )

            return generated_key

    def key_status(
        self,
        user_id: int,
    ) -> str:
        """Retorna o status da chave."""

        with self._connect() as db:
            row = db.execute(
                """
                SELECT key_revoked
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()

            if (
                not row
                or row["key_revoked"]
            ):
                return "REVOGADA"

            return "ATIVA"

    def license_history(
        self,
        actor_id: int,
        user_id: int,
    ) -> list[sqlite3.Row]:
        """Retorna o histórico da licença."""

        self._require_admin(
            actor_id
        )

        with self._connect() as db:
            return list(
                db.execute(
                    """
                    SELECT
                        action,
                        old_expires_at,
                        new_expires_at,
                        note,
                        created_at
                    FROM license_history
                    WHERE user_id = ?
                    ORDER BY id DESC
                    """,
                    (user_id,),
                )
            )

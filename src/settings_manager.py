"""Modelos, validação e persistência das configurações do aplicativo."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .keymap import normalize_key_token

LOGGER = logging.getLogger(__name__)

MIN_INTERVAL_MS = 20
MAX_INTERVAL_MS = 60_000
MIN_PRESS_DURATION_MS = 1
MAX_PRESS_DURATION_MS = 5_000
MAX_SEQUENCE_LENGTH = 32


class SettingsValidationError(ValueError):
    """Erro de validação de uma configuração informada pelo usuário."""


@dataclass(frozen=True)
class Settings:
    """Configuração validada usada pelo motor de automação."""

    interval_ms: int = 500
    press_duration_ms: int = 100
    sequence: tuple[str, ...] = ("W", "A", "S", "D")

    def __post_init__(self) -> None:
        validate_settings(self)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "Settings":
        """Cria configurações a partir de um dicionário JSON."""

        if not isinstance(data, dict):
            raise SettingsValidationError("O arquivo de configurações deve conter um objeto JSON.")

        try:
            sequence_value = data.get("sequence", ("W", "A", "S", "D"))
            if isinstance(sequence_value, str):
                sequence = tuple(
                    item.strip() for item in sequence_value.replace(";", ",").split(",") if item.strip()
                )
            else:
                sequence = tuple(sequence_value)
            return cls(
                interval_ms=int(data.get("interval_ms", 500)),
                press_duration_ms=int(data.get("press_duration_ms", 100)),
                sequence=sequence,
            )
        except (TypeError, ValueError, SettingsValidationError) as exc:
            if isinstance(exc, SettingsValidationError):
                raise
            raise SettingsValidationError("Os valores do arquivo de configurações são inválidos.") from exc

    def to_mapping(self) -> dict[str, Any]:
        """Retorna uma estrutura serializável em JSON."""

        result = asdict(self)
        result["sequence"] = list(self.sequence)
        return result


def validate_settings(settings: Settings) -> None:
    """Valida limites de segurança e consistência da configuração."""

    if not isinstance(settings.interval_ms, int) or isinstance(settings.interval_ms, bool):
        raise SettingsValidationError("O intervalo deve ser um número inteiro em milissegundos.")
    if not MIN_INTERVAL_MS <= settings.interval_ms <= MAX_INTERVAL_MS:
        raise SettingsValidationError(
            f"O intervalo deve estar entre {MIN_INTERVAL_MS} e {MAX_INTERVAL_MS} ms."
        )

    if not isinstance(settings.press_duration_ms, int) or isinstance(settings.press_duration_ms, bool):
        raise SettingsValidationError("A duração deve ser um número inteiro em milissegundos.")
    if not MIN_PRESS_DURATION_MS <= settings.press_duration_ms <= MAX_PRESS_DURATION_MS:
        raise SettingsValidationError(
            f"A duração deve estar entre {MIN_PRESS_DURATION_MS} e {MAX_PRESS_DURATION_MS} ms."
        )
    if settings.press_duration_ms > settings.interval_ms:
        raise SettingsValidationError(
            "A duração não pode ser maior que o intervalo entre pressionamentos."
        )

    if not isinstance(settings.sequence, tuple):
        raise SettingsValidationError("A sequência deve ser uma tupla de teclas.")
    if not 1 <= len(settings.sequence) <= MAX_SEQUENCE_LENGTH:
        raise SettingsValidationError(
            f"A sequência deve conter entre 1 e {MAX_SEQUENCE_LENGTH} teclas."
        )
    for key in settings.sequence:
        try:
            normalize_key_token(key)
        except ValueError as exc:
            raise SettingsValidationError(str(exc)) from exc


def default_config_path() -> Path:
    """Calcula um local por usuário, sem exigir privilégios de administrador."""

    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return root / "WASD Auto Toggle" / "settings.json"

    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "wasd-auto-toggle" / "settings.json"


class SettingsManager:
    """Carrega e salva configurações em JSON usando escrita atômica."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_config_path()

    def load(self) -> Settings:
        if not self.path.exists():
            return Settings()

        try:
            with self.path.open("r", encoding="utf-8") as file:
                return Settings.from_mapping(json.load(file))
        except (OSError, json.JSONDecodeError, SettingsValidationError) as exc:
            LOGGER.warning("Não foi possível carregar %s; usando padrões: %s", self.path, exc)
            return Settings()

    def save(self, settings: Settings) -> None:
        validate_settings(settings)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix="settings-", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(settings.to_mapping(), file, ensure_ascii=False, indent=2)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self.path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise

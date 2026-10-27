from __future__ import annotations

import json

import pytest

from src.keymap import format_sequence, parse_sequence_text
from src.settings_manager import Settings, SettingsManager, SettingsValidationError


def test_default_settings_are_valid() -> None:
    settings = Settings()
    assert settings.interval_ms == 500
    assert settings.press_duration_ms == 100
    assert settings.sequence == ("W", "A", "S", "D")


def test_parse_sequence_accepts_common_separators() -> None:
    assert parse_sequence_text(" w, a; s d ") == ("W", "A", "S", "D")
    assert format_sequence(("W", "A", "S", "D")) == "W,A,S,D"


def test_invalid_values_are_rejected() -> None:
    with pytest.raises(SettingsValidationError):
        Settings(interval_ms=10, press_duration_ms=100, sequence=("W",))
    with pytest.raises(SettingsValidationError):
        Settings(interval_ms=100, press_duration_ms=101, sequence=("W",))
    with pytest.raises(SettingsValidationError):
        Settings(interval_ms=100, press_duration_ms=10, sequence=("NOT_A_KEY",))


def test_settings_are_saved_and_loaded_atomically(tmp_path) -> None:
    path = tmp_path / "config" / "settings.json"
    manager = SettingsManager(path)
    expected = Settings(interval_ms=750, press_duration_ms=80, sequence=("W", "A"))

    manager.save(expected)

    assert path.exists()
    assert manager.load() == expected
    assert json.loads(path.read_text(encoding="utf-8"))["sequence"] == ["W", "A"]


def test_corrupt_file_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not-json", encoding="utf-8")
    assert SettingsManager(path).load() == Settings()

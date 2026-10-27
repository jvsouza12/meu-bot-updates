"""Mapeamento das teclas aceitas pelo WASD Auto Toggle.

O projeto não captura o teclado inteiro. Este módulo apenas valida a sequência
configurada e traduz nomes de teclas para códigos virtuais do Windows quando
necessário.
"""

from __future__ import annotations

import re


SPECIAL_KEYS: dict[str, int] = {
    "SPACE": 0x20,
    "ENTER": 0x0D,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "ALT": 0x12,
    "CAPSLOCK": 0x14,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
}

_KEY_TOKEN_RE = re.compile(r"^[A-Z0-9]+$")


def normalize_key_token(token: str) -> str:
    """Normaliza e valida um token de tecla.

    São aceitas letras, dígitos, F1-F24 e os nomes listados em ``SPECIAL_KEYS``.
    Cada item da sequência representa uma única tecla, não uma combinação.
    """

    if not isinstance(token, str):
        raise ValueError("Cada tecla deve ser um texto.")

    normalized = token.strip().upper()
    if not normalized:
        raise ValueError("A sequência contém uma tecla vazia.")

    if len(normalized) == 1 and (normalized.isalpha() or normalized.isdigit()):
        return normalized

    if normalized in SPECIAL_KEYS:
        return normalized

    if re.fullmatch(r"F(?:[1-9]|1[0-9]|2[0-4])", normalized):
        return normalized

    if not _KEY_TOKEN_RE.fullmatch(normalized):
        raise ValueError(f"Tecla inválida: {token!r}.")

    raise ValueError(
        f"Tecla não suportada: {token!r}. Use letras, dígitos, F1-F24 ou uma tecla especial."
    )


def parse_sequence_text(text: str) -> tuple[str, ...]:
    """Converte ``W,A,S,D`` ou ``W A S D`` em uma sequência normalizada."""

    if not isinstance(text, str):
        raise ValueError("A sequência deve ser um texto.")

    raw_tokens = [part for part in re.split(r"[;,\s]+", text.strip()) if part]
    if not raw_tokens:
        raise ValueError("Informe pelo menos uma tecla na sequência.")
    if len(raw_tokens) > 32:
        raise ValueError("A sequência pode conter no máximo 32 teclas.")

    return tuple(normalize_key_token(token) for token in raw_tokens)


def format_sequence(sequence: tuple[str, ...] | list[str]) -> str:
    """Formata a sequência para exibição e edição na interface."""

    return ",".join(sequence)


def virtual_key_code(token: str) -> int:
    """Retorna o virtual-key code do Windows correspondente ao token."""

    normalized = normalize_key_token(token)

    if len(normalized) == 1:
        return ord(normalized)

    if normalized.startswith("F") and normalized[1:].isdigit():
        return 0x70 + int(normalized[1:]) - 1

    return SPECIAL_KEYS[normalized]

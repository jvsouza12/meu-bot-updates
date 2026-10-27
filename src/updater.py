"""Atualização do aplicativo por GitHub Releases, sem exigir acesso ao código-fonte."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path


GITHUB_OWNER = "jvsouza12"
GITHUB_REPOSITORY = "meu-bot-updates"
GITHUB_API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPOSITORY}/releases/latest"
)


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    download_url: str
    sha256: str = ""


class UpdateError(RuntimeError):
    """Erro controlado durante a consulta ou instalação de atualização."""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = value.lstrip("vV").split(".")
    result: list[int] = []

    for part in parts:
        number = "".join(
            character
            for character in part
            if character.isdigit()
        )
        result.append(int(number or "0"))

    return tuple(result)


def is_newer(current: str, available: str) -> bool:
    return _version_tuple(available) > _version_tuple(current)


def fetch_latest_release(
    timeout: int = 15,
) -> ReleaseInfo | None:
    request = urllib.request.Request(
        GITHUB_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "AUTO-By-BETANO-Updater",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            payload = json.loads(
                response.read().decode("utf-8"),
            )

    except Exception as exc:
        raise UpdateError(
            f"Não foi possível consultar atualizações: {exc}",
        ) from exc

    tag = str(
        payload.get(
            "tag_name",
            "",
        ),
    ).strip()

    version = tag.lstrip("vV")

    assets = payload.get("assets") or []

    executable = next(
        (
            asset
            for asset in assets
            if str(
                asset.get(
                    "name",
                    "",
                ),
            ).lower().endswith(".exe")
        ),
        None,
    )

    if not version or executable is None:
        return None

    return ReleaseInfo(
        version=version,
        download_url=str(
            executable.get(
                "browser_download_url",
                "",
            ),
        ),
        sha256=str(
            payload.get(
                "body",
                "",
            ),
        ).strip(),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(
            lambda: stream.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def install_update(
    release: ReleaseInfo,
    progress=None,
) -> None:
    if not release.download_url:
        raise UpdateError(
            "A Release não possui um download válido.",
        )

    current_executable = Path(
        sys.executable,
    ).resolve()

    if (
        not getattr(
            sys,
            "frozen",
            False,
        )
        or current_executable.suffix.lower() != ".exe"
    ):
        raise UpdateError(
            "A atualização automática funciona somente "
            "na versão .exe publicada.",
        )

    temporary_directory = Path(
        tempfile.mkdtemp(
            prefix="auto-betano-update-",
        ),
    )

    downloaded = temporary_directory / current_executable.name

    request = urllib.request.Request(
        release.download_url,
        headers={
            "User-Agent": "AUTO-By-BETANO-Updater",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=120,
        ) as response:
            total = int(
                response.headers.get(
                    "Content-Length",
                    "0",
                )
                or "0",
            )

            received = 0

            with downloaded.open("wb") as target:
                while True:
                    block = response.read(
                        1024 * 1024,
                    )

                    if not block:
                        break

                    target.write(block)
                    received += len(block)

                    if progress is not None and total:
                        progress(
                            min(
                                100,
                                int(
                                    received * 100 / total,
                                ),
                            ),
                        )

        if downloaded.stat().st_size < 1024 * 1024:
            raise UpdateError(
                "O arquivo baixado parece incompleto.",
            )

        expected = ""

        for line in release.sha256.splitlines():
            if line.upper().startswith("SHA256:"):
                expected = line.split(
                    ":",
                    1,
                )[1].strip().lower()
                break

        if (
            expected
            and _sha256(downloaded).lower() != expected
        ):
            raise UpdateError(
                "A verificação de segurança do download falhou.",
            )

        replacement = current_executable.with_name(
            f"{current_executable.stem}.new.exe",
        )

        downloaded.replace(replacement)

        script = temporary_directory / "apply_update.cmd"

        script.write_text(
            "@echo off\n"
            "timeout /t 2 /nobreak >nul\n"
            f'del /f /q "{current_executable}"\n'
            f'move /y "{replacement}" "{current_executable}"\n'
            f'start "" "{current_executable}"\n'
            'del "%~f0"\n',
            encoding="utf-8",
        )

        subprocess.Popen(
            [
                "cmd.exe",
                "/c",
                str(script),
            ],
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0,
            ),
        )

    except UpdateError:
        raise

    except Exception as exc:
        raise UpdateError(
            f"Falha ao baixar a atualização: {exc}",
        ) from exc

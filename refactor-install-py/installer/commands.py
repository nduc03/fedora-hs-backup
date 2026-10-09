"""One argv-only command runner shared by core modules and hooks."""

import shlex
import subprocess
from pathlib import Path

from .common import InstallError


class CommandRunner:
    def __init__(self, cwd: Path):
        self.cwd = cwd

    def run(self, argv: list[str], *, privileged: bool = False,
            check: bool = True) -> subprocess.CompletedProcess[str]:
        command = (["sudo"] if privileged else []) + [str(argument) for argument in argv]
        try:
            result = subprocess.run(command, cwd=self.cwd, text=True, encoding="utf-8",
                                    capture_output=True, check=False)
        except OSError as error:
            raise InstallError(f"Không chạy được lệnh {command[0]}: {error}") from error
        if check and result.returncode:
            detail = result.stderr.strip() or result.stdout.strip()
            raise InstallError(f"Lệnh thất bại ({result.returncode}): {shlex.join(command)}\n{detail}")
        return result

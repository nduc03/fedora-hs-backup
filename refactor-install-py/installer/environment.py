"""Read dotenv assignments as literal data, never as shell code."""

import os
import re
from pathlib import Path

from .common import InstallError, within

ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
IGNORED_DIRECTORIES = {"__dbg_template__", "__pycache__", ".git"}


def literal_value(value: str) -> str:
    if not value or value[0] not in "\"'":
        return re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
    quote = value[0]
    position = 1
    while position < len(value):
        if quote == '"' and value[position] == "\\":
            position += 2
            continue
        if value[position] == quote:
            trailing = value[position + 1:].strip()
            if trailing and not trailing.startswith("#"):
                raise ValueError("Unexpected text after quote")
            return value[1:position]
        position += 1
    raise ValueError("Unclosed quote")


def read_env(path: Path) -> dict[str, str]:
    result = {}
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = ASSIGNMENT.fullmatch(line)
        if not match:
            raise InstallError(f"{path}:{number}: cần phép gán KEY=value.")
        try:
            result[match[1]] = literal_value(match[2])
        except ValueError as error:
            raise InstallError(f"{path}:{number}: giá trị .env không hợp lệ.") from error
    return result


def load_environment(service_dir: Path, variables: dict[str, str], *, home: Path | None = None,
                     inherited: dict[str, str] | None = None) -> dict[str, str]:
    result = dict(os.environ if inherited is None else inherited)
    global_env = (home or Path.home()) / "hs-info.env"
    if global_env.is_file():
        result.update(read_env(global_env))
    local_files = sorted(service_dir.rglob("ctv.env"), key=lambda path: path.relative_to(service_dir).as_posix())
    for path in local_files:
        relative = path.relative_to(service_dir)
        if not IGNORED_DIRECTORIES.intersection(relative.parts):
            result.update(read_env(within(service_dir, relative.as_posix())))
    result.update(variables)
    return result

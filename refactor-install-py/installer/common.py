"""Errors, path validation and output helpers."""

import os
import tempfile
from pathlib import Path, PureWindowsPath


class InstallError(Exception):
    """An expected configuration or installation failure."""


def within(root: Path, relative: str) -> Path:
    """Resolve a relative path, including symlinks, inside its declared root."""
    part = Path(relative)
    windows = PureWindowsPath(relative)
    if not relative or part.is_absolute() or windows.drive or "\\" in relative:
        raise InstallError(f"Đường dẫn phải tương đối: {relative!r}")
    if ".." in part.parts:
        raise InstallError(f"Đường dẫn không được chứa '..': {relative!r}")
    base = root.resolve()
    result = (base / part).resolve()
    if not result.is_relative_to(base) or result == base:
        raise InstallError(f"Đường dẫn thoát khỏi thư mục cho phép: {relative!r}")
    return result


def write_text(path: Path, content: str, mode: int = 0o600) -> None:
    """Write UTF-8/LF atomically; only set permissions on the new file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        if os.name == "posix":
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

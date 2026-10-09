"""Single-pass %NAME% substitution, matching variable names without case sensitivity. Inspired by the Windows batch/cmd variable expansion."""

import re
from collections.abc import Mapping

from ..common import InstallError
from .base import RenderResult

VARIABLE = re.compile(r"%([A-Za-z_][A-Za-z0-9_]*)%")


class LegacyEngine:
    def render(self, text: str, variables: Mapping[str, str]) -> RenderResult:
        normalized = {}
        for name, value in variables.items():
            key = name.upper()
            if key in normalized and normalized[key] != value:
                raise InstallError(f"Engine legacy: biến {key} có nhiều giá trị khác nhau do tên trùng hoa/thường.")
            normalized[key] = value
        missing = set()

        def replace(match: re.Match[str]) -> str:
            key = match[1].upper()
            if key in normalized:
                return normalized[key]
            missing.add(key)
            return match[0]

        return RenderResult(VARIABLE.sub(replace, text), tuple(sorted(missing)))

"""Single-pass $VAR/${VAR} substitution with the original envsubst semantics."""

import re
from collections.abc import Mapping

from .base import RenderResult

VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
PASSWORD_HASH = re.compile(r"\$(?:1|2[abxy]|apr1|argon2[a-z]*|5|6)\$[A-Za-z0-9./$=+,-]+")


class ShellEngine:
    def render(self, text: str, variables: Mapping[str, str]) -> RenderResult:
        missing = set()

        def replace(match: re.Match[str]) -> str:
            name = match[1] or match[2]
            if name in variables:
                return variables[name]
            missing.add(name)
            return match[0]

        fragments = []
        position = 0
        for password in PASSWORD_HASH.finditer(text):
            fragments.append(VARIABLE.sub(replace, text[position:password.start()]))
            fragments.append(password[0])
            position = password.end()
        fragments.append(VARIABLE.sub(replace, text[position:]))
        return RenderResult("".join(fragments), tuple(sorted(missing)))

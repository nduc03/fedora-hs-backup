"""Single-pass, envsubst-style substitution and staged template outputs."""

import re
from dataclasses import dataclass
from pathlib import Path

from .common import InstallError, within, write_text
from .context import InstallContext
from .traefik import inject_labels

VARIABLE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")
PASSWORD_HASH = re.compile(r"\$(?:1|2[abxy]|apr1|argon2[a-z]*|5|6)\$[A-Za-z0-9./$=+,-]+")


def substitute(text: str, variables: dict[str, str]) -> tuple[str, tuple[str, ...]]:
    """Replace known names once, preserving hashes, unknowns and shell operators."""
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
    return "".join(fragments), tuple(sorted(missing))


@dataclass(frozen=True)
class RenderedFile:
    relative: str
    staged: Path
    unresolved: tuple[str, ...]


@dataclass(frozen=True)
class RenderedTemplates:
    main: RenderedFile
    extras: tuple[RenderedFile, ...]


def render_templates(context: InstallContext, staging: Path) -> RenderedTemplates:
    filename = f"{context.service_name}.{context.config.file_type}"
    relative = filename + (".template" if context.config.use_template else "")
    source = within(context.service_dir, relative)
    if not source.is_file():
        raise InstallError(f"Thiếu Quadlet đầu vào: {source}")

    def render(input_file: Path, output_name: str, main: bool = False) -> RenderedFile:
        text = input_file.read_text(encoding="utf-8-sig")
        unresolved = ()
        if context.config.use_template:
            text, unresolved = substitute(text, context.variables)
            if main:
                text = inject_labels(text, context)
        target = within(staging, output_name)
        write_text(target, text)
        return RenderedFile(output_name, target, unresolved)

    main = render(source, filename, main=True)
    extras = []
    outputs = {within(context.service_dir, filename)}
    if context.config.use_template:
        for extra in context.config.extra_template_files:
            input_file = within(context.service_dir, extra)
            if input_file == source:
                raise InstallError("extra_template_files không được chứa template chính.")
            output_name = extra[:-len(".template")]
            target = within(context.service_dir, output_name)
            if target in outputs:
                raise InstallError(f"Đầu ra template trùng lặp: {output_name}")
            outputs.add(target)
            if not input_file.is_file():
                raise InstallError(f"Thiếu template phụ: {input_file}")
            extras.append(render(input_file, output_name))
    return RenderedTemplates(main, tuple(extras))


def publish_templates(context: InstallContext, rendered: RenderedTemplates, *, debug: bool) -> None:
    root = within(context.service_dir, "__dbg_template__") if debug else context.service_dir
    files = (rendered.main, *rendered.extras) if debug else rendered.extras
    for item in files:
        target = within(root, item.relative)
        mode = 0o600 if debug or target.suffix == ".env" else 0o644
        write_text(target, item.staged.read_text(encoding="utf-8"), mode=mode)
    if debug:
        write_text(within(root, ".gitignore"), "*\n")

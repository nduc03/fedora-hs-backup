"""Resolve the TOML selector and instantiate one engine per render operation."""

import importlib
import re
from typing import cast

from ..common import InstallError
from .base import RenderResult, TemplateEngine

BUILTIN_ENGINES = {
    "shell": "installer.engines.shell:ShellEngine",
    "legacy": "installer.engines.legacy:LegacyEngine",
}
ENGINE_TARGET = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*")


def validate_engine_selector(selector: object) -> str:
    if not isinstance(selector, str) or (selector not in BUILTIN_ENGINES and not ENGINE_TARGET.fullmatch(selector)):
        raise InstallError("template_engine cần 'shell', 'legacy' hoặc 'package.module:EngineClass'.")
    return selector


def load_engine(selector: str) -> TemplateEngine:
    selector = validate_engine_selector(selector)
    module_name, class_name = BUILTIN_ENGINES.get(selector, selector).split(":")
    try:
        module = importlib.import_module(module_name)
        engine_class = getattr(module, class_name)
        if not isinstance(engine_class, type):
            raise InstallError(f"Template engine phải là class: {selector}")
        engine = engine_class()
        if not callable(getattr(engine, "render", None)):
            raise InstallError(f"Template engine thiếu phương thức render(text, variables): {selector}")
        return cast(TemplateEngine, engine)
    except InstallError:
        raise
    except (Exception, SystemExit) as error:
        raise InstallError(f"Không nạp được template engine {selector}: {type(error).__name__}.") from error


def validate_render_result(result: object) -> RenderResult:
    if not isinstance(result, RenderResult) or not isinstance(result.text, str) or not isinstance(result.unresolved, tuple) \
            or any(not isinstance(name, str) or not name for name in result.unresolved):
        raise InstallError("Engine.render phải trả RenderResult(text: str, unresolved: tuple[str, ...]).")
    return result

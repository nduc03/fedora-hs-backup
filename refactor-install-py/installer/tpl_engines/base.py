"""The contract shared by built-in and imported template engines."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RenderResult:
    text: str
    unresolved: tuple[str, ...] = ()


class TemplateEngine(Protocol):
    def render(self, text: str, variables: Mapping[str, str]) -> RenderResult:
        """Render text without modifying variables or performing installation actions."""
        ...

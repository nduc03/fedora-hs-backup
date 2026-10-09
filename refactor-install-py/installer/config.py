"""Typed service settings loaded from install.toml."""

import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .common import InstallError, within

VARIABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
UNIT_NAME = re.compile(r"^[A-Za-z0-9_.@:-]+\.service$")


@dataclass(frozen=True)
class ServiceConfig:
    rootless: bool = True
    use_template: bool = True
    file_type: str = "container"
    use_traefik_labels: bool = False
    enable_public_domain: bool = False
    mount_dirs: tuple[str, ...] = ()
    config_dirs: tuple[str, ...] = ()
    extra_template_files: tuple[str, ...] = ()
    service_data_dir: str | None = None
    container_uid: int = 1000
    container_gid: int = 1000
    systemd_units: tuple[str, ...] = ()
    variables: dict[str, str] = field(default_factory=dict)
    hooks: dict[str, tuple[str, ...]] = field(default_factory=dict)


def hook_target(service_dir: Path, entrypoint: str) -> tuple[Path, str]:
    filename, separator, function = entrypoint.rpartition(":")
    if not separator or not filename.endswith(".py") or not VARIABLE_NAME.fullmatch(function):
        raise InstallError(f"Hook cần dạng 'hooks/pre_install.py:run': {entrypoint!r}")
    return within(service_dir, filename), function


def load_config(service_dir: Path) -> ServiceConfig:
    path = within(service_dir, "install.toml")
    if not path.is_file():
        raise InstallError(f"Thiếu {path}. Bộ cài không tự đọc install.sh.")
    try:
        with path.open("rb") as stream:
            raw = tomllib.load(stream)
    except tomllib.TOMLDecodeError as error:
        # Do not include the source document: it may contain credentials.
        raise InstallError(f"TOML không hợp lệ trong {path}.") from error
    unknown = set(raw) - {item.name for item in fields(ServiceConfig)}
    if unknown:
        raise InstallError(f"Tùy chọn không được hỗ trợ: {', '.join(sorted(unknown))}")
    for key in ("rootless", "use_template", "use_traefik_labels", "enable_public_domain"):
        if key in raw and type(raw[key]) is not bool:
            raise InstallError(f"{key} phải là boolean TOML.")
    if raw.get("file_type", "container") not in ("container", "quadlets"):
        raise InstallError("file_type chỉ nhận 'container' hoặc 'quadlets'.")
    for key in ("mount_dirs", "config_dirs", "extra_template_files", "systemd_units"):
        values = raw.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise InstallError(f"{key} phải là danh sách chuỗi không rỗng.")
        if len(values) != len(set(values)):
            raise InstallError(f"{key} có phần tử trùng lặp.")
        raw[key] = tuple(values)
        for value in values:
            if key == "systemd_units":
                if not UNIT_NAME.fullmatch(value):
                    raise InstallError(f"Unit systemd không hợp lệ: {value!r}")
            else:
                within(service_dir, value)
                if key == "extra_template_files" and not value.endswith(".template"):
                    raise InstallError(f"Template phụ phải có đuôi .template: {value!r}")
    if raw.get("file_type") == "quadlets" and not raw["systemd_units"]:
        raise InstallError("file_type='quadlets' cần khai báo systemd_units rõ ràng.")
    for key in ("container_uid", "container_gid"):
        value = raw.get(key, 1000)
        if type(value) is not int or value < 0:
            raise InstallError(f"{key} phải là số nguyên không âm.")
    if "service_data_dir" in raw and (not isinstance(raw["service_data_dir"], str) or not raw["service_data_dir"]):
        raise InstallError("service_data_dir phải là chuỗi không rỗng.")
    variables = raw.get("variables", {})
    if not isinstance(variables, dict):
        raise InstallError("variables phải là bảng TOML.")
    converted = {}
    for key, value in variables.items():
        if not VARIABLE_NAME.fullmatch(key) or type(value) not in (str, int, float, bool):
            raise InstallError(f"Biến không hợp lệ trong [variables]: {key!r}")
        converted[key] = str(value).lower() if isinstance(value, bool) else str(value)
    raw["variables"] = converted
    hooks = raw.get("hooks", {})
    if not isinstance(hooks, dict) or set(hooks) - {"pre_install", "post_install"}:
        raise InstallError("[hooks] chỉ hỗ trợ pre_install và post_install.")
    for stage, entries in hooks.items():
        if not isinstance(entries, list) or any(not isinstance(entry, str) for entry in entries):
            raise InstallError(f"hooks.{stage} phải là danh sách entrypoint.")
        for entry in entries:
            hook_target(service_dir, entry)
    raw["hooks"] = {stage: tuple(entries) for stage, entries in hooks.items()}
    return ServiceConfig(**raw)

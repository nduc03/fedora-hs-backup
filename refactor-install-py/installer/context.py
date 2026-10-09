"""Runtime context, service resolution and host addresses."""

import ipaddress
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .commands import CommandRunner
from .common import InstallError, within
from .config import ServiceConfig


def resolve_service(root: Path, name: str) -> tuple[Path, str]:
    if name in (".", "..") or "/" in name or "\\" in name:
        raise InstallError("Tên service phải là tên một thư mục con.")
    directory = within(root, name)
    if not directory.is_dir():
        raise InstallError(f"Không tìm thấy thư mục service: {directory}")
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")
    if not normalized:
        raise InstallError("Tên service rỗng sau khi chuẩn hóa.")
    return directory, normalized


def discover_addresses(runner: CommandRunner) -> tuple[str, str]:
    routes = json.loads(runner.run(["ip", "-j", "-4", "route", "show", "default"]).stdout)
    device = next((route["dev"] for route in routes if "dev" in route), None)
    if not device:
        raise InstallError("Không tìm thấy interface có IPv4 default route.")
    interfaces = json.loads(runner.run(["ip", "-j", "address", "show", "dev", device]).stdout)
    addresses = [item.get("local", "") for interface in interfaces for item in interface.get("addr_info", [])]
    ipv4 = next((address for address in addresses if isinstance(ipaddress.ip_address(address), ipaddress.IPv4Address)), "")
    ula = next((address for address in addresses if ":" in address and ipaddress.ip_address(address) in ipaddress.ip_network("fc00::/7")), "::1")
    if not ipv4:
        raise InstallError(f"Interface {device} không có địa chỉ IPv4.")
    return ipv4, ula


@dataclass
class InstallContext:
    config: ServiceConfig
    service_dir: Path
    service_name: str
    service_data_dir: Path
    install_location: Path
    host_ipv4: str
    host_ula_ipv6: str
    variables: dict[str, str]
    runner: CommandRunner
    log: Callable[[str], None] = print

    @property
    def systemctl_argv(self) -> list[str]:
        return ["systemctl", "--user"] if self.config.rootless else ["systemctl"]

    @property
    def systemd_units(self) -> tuple[str, ...]:
        return self.config.systemd_units or (f"{self.service_name}.service",)


def build_context(config: ServiceConfig, service_dir: Path, service_name: str,
                  variables: dict[str, str], runner: CommandRunner, *, debug: bool = False,
                  home: Path | None = None) -> InstallContext:
    home = (home or Path.home()).resolve()
    if config.service_data_dir:
        value = config.service_data_dir
        if value == "~" or value.startswith("~/"):
            data_dir = home / value[2:] if value != "~" else home
        else:
            path = Path(value)
            data_dir = path if path.is_absolute() else within(service_dir, value)
    else:
        data_dir = home / "container-data" / service_name
    data_dir = data_dir.resolve()
    ipv4 = variables.get("HOST_IPV4", "")
    ula = variables.get("HOST_ULA_IPV6", "").strip("[]")
    if (not ipv4 or not ula) and sys.platform.startswith("linux"):
        try:
            detected_ipv4, detected_ula = discover_addresses(runner)
            ipv4 = ipv4 or detected_ipv4
            ula = ula or detected_ula
        except (InstallError, ValueError, KeyError, TypeError) as error:
            if not debug and not ipv4:
                raise InstallError("Không dò được địa chỉ host; hãy đặt HOST_IPV4 trong env hoặc [variables].") from error
    if not ipv4 and not debug:
        raise InstallError("Cần HOST_IPV4 trong env hoặc [variables].")
    ula = ula or "::1"
    try:
        if ipv4:
            ipv4 = str(ipaddress.IPv4Address(ipv4))
        ula = str(ipaddress.IPv6Address(ula))
    except ValueError as error:
        raise InstallError("HOST_IPV4 hoặc HOST_ULA_IPV6 không phải địa chỉ IP hợp lệ.") from error
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    if config.rootless and not config_home.is_absolute():
        raise InstallError("XDG_CONFIG_HOME phải là đường dẫn tuyệt đối.")
    location = config_home / "containers/systemd" if config.rootless else Path("/etc/containers/systemd")
    mapping = dict(variables)
    mapping.update(SCRIPT_DIR=str(service_dir), SCRIPT_DIR_NAME=service_dir.name,
                   SERVICE_DIR=str(service_dir), SERVICE_NAME=service_name,
                   SERVICE_DATA_DIR=str(data_dir), INSTALL_LOCATION=str(location),
                   HOST_ULA_IPV6=f"[{ula}]", SUDO="" if config.rootless else "sudo",
                   SYSTEMCTL_CMD="systemctl --user" if config.rootless else "sudo systemctl")
    if ipv4:
        mapping["HOST_IPV4"] = ipv4
    return InstallContext(config, service_dir, service_name, data_dir, location, ipv4, ula, mapping, runner)

"""Shared install command and the ordered installation pipeline."""

import argparse
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

from . import adguard
from .commands import CommandRunner
from .common import InstallError
from .config import ServiceConfig, load_config
from .context import InstallContext, build_context, resolve_service
from .environment import load_environment
from .filesystem import prepare_directories, validate_directories
from .hooks import run_hooks, validate_hooks
from .quadlet import install_quadlets, installation_sources
from .systemd import update_services
from .templates import publish_templates, render_templates


def validate_execution(config: ServiceConfig) -> None:
    if not sys.platform.startswith("linux"):
        raise InstallError("Cài đặt thật cần Linux/Podman/systemd. Dùng --dbg-templ để chỉ render.")
    if os.geteuid() == 0:
        raise InstallError("Hãy chạy bằng tài khoản thường, không dùng sudo ./install.py. Bộ cài tự gọi sudo khi cần.")
    required = ["podman", "systemctl"]
    if not config.rootless or config.mount_dirs or config.config_dirs:
        required.append("sudo")
    missing = [name for name in required if shutil.which(name) is None]
    if missing:
        raise InstallError(f"Thiếu lệnh cần thiết: {', '.join(missing)}")


def preflight(context: InstallContext, *, skip_adguard_dns: bool = False) -> None:
    validate_hooks(context)
    validate_directories(context)
    if context.config.enable_public_domain and not skip_adguard_dns:
        adguard.validate_settings(context)
    help_text = context.runner.run(["podman", "quadlet", "install", "--help"]).stdout
    if "--reload-systemd" not in help_text:
        raise InstallError("Podman cần hỗ trợ 'quadlet install --reload-systemd=false'.")
    if context.config.file_type == "quadlets":
        version = context.runner.run(["podman", "--version"]).stdout
        match = re.search(r"\b(\d+)\.(\d+)", version)
        if not match or (int(match[1]), int(match[2])) < (5, 8):
            raise InstallError("Bundle .quadlets cần Podman 5.8 trở lên.")


def run_pipeline(context: InstallContext, *, debug: bool, allow_unresolved: bool) -> None:
    stage = "render template"
    try:
        with tempfile.TemporaryDirectory(prefix=f"{context.service_name}-install-") as temporary:
            staging = Path(temporary)
            context.log(f">>> Render template cho {context.service_name}...")
            rendered = render_templates(context, staging)
            extras = {item.relative: item.staged for item in rendered.extras}
            sources = installation_sources(context, rendered.main.staged, extras)
            unresolved = [item for item in (rendered.main, *rendered.extras) if item.unresolved]
            for item in unresolved:
                context.log(f"[WARNING] {item.relative}: biến chưa khai báo: {', '.join(item.unresolved)}")
            if debug:
                publish_templates(context, rendered, debug=True)
                context.log(f">>> Debug hoàn tất: {context.service_dir / '__dbg_template__'}")
                return
            if unresolved and not allow_unresolved:
                if not sys.stdin.isatty() or input("Giữ nguyên các biến này và tiếp tục? (y/N) ").strip().lower() != "y":
                    raise InstallError("Dừng do biến chưa khai báo; dùng --allow-unresolved nếu muốn giữ nguyên.")
            stage = "kiểm tra trước cài đặt"
            skip_adguard_dns = adguard.is_bootstrap_service(rendered.main.staged.read_text(encoding="utf-8"))
            preflight(context, skip_adguard_dns=skip_adguard_dns)
            stage = "xuất template phụ"
            publish_templates(context, rendered, debug=False)
            stage = "chuẩn bị thư mục dữ liệu/quyền"
            context.log(">>> Chuẩn bị thư mục dữ liệu và config...")
            prepare_directories(context)
            stage = "pre_install"
            run_hooks(context, "pre_install")
            stage = "cài Quadlet"
            context.log(">>> Snapshot và cài Quadlet...")
            changed = install_quadlets(context, sources, staging)
            stage = "cập nhật systemd"
            context.log(">>> Definition thay đổi: reload/restart." if changed else ">>> Definition không đổi: kiểm tra trạng thái unit.")
            update_services(context, changed)
            stage = "post_install"
            run_hooks(context, "post_install")
            if context.config.enable_public_domain:
                if skip_adguard_dns:
                    context.log(">>> Bỏ qua DNS rewrite: service dùng image AdGuard Home (bootstrap).")
                else:
                    stage = "DNS AdGuard"
                    adguard.register_rewrites(context)
            context.log(">>> Hoàn tất.")
            prefix = " ".join(context.systemctl_argv)
            if not context.config.rootless:
                prefix = "sudo " + prefix
            for unit in context.systemd_units:
                context.log(f"Kiểm tra trạng thái: {prefix} status {unit}")
    except (InstallError, OSError, ValueError) as error:
        raise InstallError(f"Bước '{stage}' thất bại: {error}") from error


def main(argv: list[str] | None = None) -> int:
    # Windows redirected streams may otherwise use an ANSI code page for Vietnamese logs.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Bộ cài Quadlet Python dùng chung (Python >= 3.11).")
    parser.add_argument("service", help="Tên thư mục service trong services-root.")
    parser.add_argument("--services-root", type=Path, help="Gốc chứa service; mặc định là home của tài khoản hiện tại.")
    parser.add_argument("--dbg-templ", action="store_true", help="Chỉ render vào __dbg_template__, không cài đặt hoặc chạy hook.")
    parser.add_argument("--allow-unresolved", action="store_true", help="Giữ biến chưa khai báo khi cài thật, không hỏi xác nhận.")
    arguments = parser.parse_args(argv)
    previous_directory = Path.cwd()
    try:
        root = (arguments.services_root or Path.home()).expanduser().resolve()
        service_dir, service_name = resolve_service(root, arguments.service)
        config = load_config(service_dir)
        if not arguments.dbg_templ:
            validate_execution(config)
        os.chdir(service_dir)
        runner = CommandRunner(service_dir)
        variables = load_environment(service_dir, config.variables)
        context = build_context(config, service_dir, service_name, variables, runner, debug=arguments.dbg_templ)
        print(f">>> Thư mục service: {service_dir}")
        run_pipeline(context, debug=arguments.dbg_templ, allow_unresolved=arguments.allow_unresolved)
        return 0
    except (InstallError, OSError, ValueError, UnicodeError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n[ERROR] Đã hủy theo yêu cầu người dùng.", file=sys.stderr)
        return 130
    finally:
        os.chdir(previous_directory)

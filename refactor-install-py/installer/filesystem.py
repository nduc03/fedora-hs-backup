"""Container data directories, copying and Podman namespace ownership."""

import os

from .common import InstallError, within
from .context import InstallContext


def namespace_ownership(context: InstallContext, target) -> None:
    if not context.config.rootless:
        return
    runner = context.runner
    host_owner = runner.run(["stat", "-c", "%u:%g", str(target)]).stdout.strip()
    container_owner = runner.run(["podman", "unshare", "stat", "-c", "%u:%g", str(target)]).stdout.strip()
    desired = f"{context.config.container_uid}:{context.config.container_gid}"
    if container_owner == desired:
        return
    host_identity = f"{os.getuid()}:{os.getgid()}"
    if host_owner != host_identity:
        runner.run(["chown", "-R", host_identity, str(target)], privileged=True)
    runner.run(["podman", "unshare", "chown", "-R", desired, str(target)])


def validate_directories(context: InstallContext) -> None:
    for relative in (*context.config.mount_dirs, *context.config.config_dirs):
        target = within(context.service_data_dir, relative)
        if target.exists() and not target.is_dir():
            raise InstallError(f"Đích dữ liệu không phải thư mục: {target}")
    for relative in context.config.config_dirs:
        source = within(context.service_dir, relative)
        target = within(context.service_data_dir, relative)
        if source.exists() and not source.is_dir():
            raise InstallError(f"Nguồn config không phải thư mục: {source}")
        if source.is_relative_to(target) or target.is_relative_to(source):
            raise InstallError(f"Nguồn và đích config không được lồng nhau: {relative}")
        for root, directory in ((context.service_dir, source), (context.service_data_dir, target)):
            if directory.is_dir():
                for child in directory.rglob("*"):
                    if child.is_symlink():
                        within(root, child.relative_to(root).as_posix())


def prepare_directories(context: InstallContext) -> None:
    validate_directories(context)
    runner = context.runner
    privileged = not context.config.rootless
    runner.run(["mkdir", "-p", str(context.service_data_dir)], privileged=privileged)
    for relative in context.config.mount_dirs:
        target = within(context.service_data_dir, relative)
        runner.run(["mkdir", "-p", str(target)], privileged=privileged)
        namespace_ownership(context, target)
    for relative in context.config.config_dirs:
        target = within(context.service_data_dir, relative)
        source = within(context.service_dir, relative)
        runner.run(["mkdir", "-p", str(target)], privileged=privileged)
        if source.is_dir():
            if context.config.rootless:
                runner.run(["chown", "-R", f"{os.getuid()}:{os.getgid()}", str(target)], privileged=True)
            runner.run(["cp", "-r", f"{source}/.", f"{target}/"], privileged=privileged)
            runner.run(["find", str(target), "-type", "d", "-exec", "chmod", "755", "{}", "+"], privileged=privileged)
            runner.run(["find", str(target), "-type", "f", "-exec", "chmod", "644", "{}", "+"], privileged=privileged)
        else:
            context.log(f"[WARNING] Không có nguồn config {source}; bỏ qua copy.")
        namespace_ownership(context, target)

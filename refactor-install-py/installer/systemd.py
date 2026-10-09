"""Only reload/restart on definition changes; start inactive unchanged units."""

from .common import InstallError
from .context import InstallContext


def update_services(context: InstallContext, changed: bool) -> None:
    prefix = context.systemctl_argv
    privileged = not context.config.rootless
    if changed:
        context.runner.run([*prefix, "daemon-reload"], privileged=privileged)
        for unit in context.systemd_units:
            context.runner.run([*prefix, "restart", unit], privileged=privileged)
        return
    for unit in context.systemd_units:
        result = context.runner.run([*prefix, "is-active", "--quiet", unit], privileged=privileged, check=False)
        if result.returncode in (3, 4):
            context.runner.run([*prefix, "start", unit], privileged=privileged)
        elif result.returncode:
            raise InstallError(f"Không kiểm tra được trạng thái {unit}: {result.stderr.strip()}")

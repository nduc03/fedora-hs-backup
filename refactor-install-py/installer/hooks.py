"""Load configured service-local hook files only during real installation."""

import hashlib
import importlib.util
import sys

from .common import InstallError
from .config import hook_target
from .context import InstallContext


def validate_hooks(context: InstallContext) -> None:
    for entries in context.config.hooks.values():
        for entry in entries:
            path, _ = hook_target(context.service_dir, entry)
            if not path.is_file():
                raise InstallError(f"Thiếu module hook: {path}")


def run_hooks(context: InstallContext, stage: str) -> None:
    for entry in context.config.hooks.get(stage, ()):
        path, function_name = hook_target(context.service_dir, entry)
        module_name = "_quadlet_hook_" + hashlib.sha256(str(path).encode()).hexdigest()
        original_path = list(sys.path)
        try:
            # Service-local helpers may be imported from the hook; the installer remains available.
            sys.path.insert(0, str(context.service_dir))
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                raise InstallError(f"Không import được hook: {path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            function = getattr(module, function_name, None)
            if not callable(function):
                raise InstallError(f"Hook không có callable {function_name}: {path}")
            function(context)
        except (Exception, SystemExit) as error:
            raise InstallError(f"Hook {stage} thất bại ({entry}): {error}") from error
        finally:
            sys.modules.pop(module_name, None)
            sys.path[:] = original_path

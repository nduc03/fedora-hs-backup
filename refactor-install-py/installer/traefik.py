"""Automatic labels for the primary service's Container section."""

import re

from .common import InstallError
from .context import InstallContext
from .quadlet import parse_bundle


def domain_value(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", value):
        raise InstallError("PRIVATE_DOMAIN/PUBLIC_DOMAIN phải là tên miền, không phải URL.")
    return value


def labels(context: InstallContext) -> str:
    name = context.service_name
    lan = domain_value(context.variables.get("PRIVATE_DOMAIN") or "hs.lan")
    lines = ["Network=traefik.network", "Label=traefik.enable=true",
             f"Label=traefik.http.routers.{name}.rule=Host(`{name}.{lan}`)",
             f"Label=traefik.http.routers.{name}.entrypoints=websecure",
             f"Label=traefik.http.routers.{name}.tls=true"]
    if context.config.enable_public_domain:
        public = domain_value(context.variables.get("PUBLIC_DOMAIN", ""))
        lines.extend([f"Label=traefik.http.routers.{name}-le.rule=Host(`{name}.{public}`)",
                      f"Label=traefik.http.routers.{name}-le.entrypoints=websecure",
                      f"Label=traefik.http.routers.{name}-le.tls.certresolver=leresolver"])
    return "\n".join(lines)


def inject_labels(text: str, context: InstallContext) -> str:
    if not context.config.use_traefik_labels:
        return text
    injection = labels(context)

    def inject(block: str) -> str:
        result, count = re.subn(r"(?m)^[ \t]*\[Container\][ \t]*$",
                                lambda match: match[0] + "\n" + injection, block)
        if count != 1:
            raise InstallError("Auto-label Traefik cần đúng một section [Container] chính.")
        return result

    if context.config.file_type == "container":
        return inject(text)
    members = parse_bundle(text)
    primary = f"{context.service_name}.container"
    if primary not in {member.filename for member in members}:
        raise InstallError(f"Auto-label Traefik cần '# FileName={context.service_name}' cho container chính.")
    # Other containers keep their own routing, rather than claiming the primary router name.
    return "\n---\n".join(inject(member.text) if member.filename == primary else member.text for member in members)

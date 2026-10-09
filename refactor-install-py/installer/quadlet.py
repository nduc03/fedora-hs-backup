"""Quadlet definitions, scoped snapshots and installation rollback."""

import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .common import InstallError, within, write_text
from .context import InstallContext

RESOURCE_TYPES = {"Container": "container", "Network": "network", "Volume": "volume",
                  "Pod": "pod", "Image": "image", "Build": "build", "Kube": "kube", "Artifact": "artifact"}
BUNDLE_SEPARATOR = re.compile(r"(?m)^[ \t]*---[ \t]*\r?$")
FILE_NAME = re.compile(r"(?m)^[ \t]*#[ \t]*FileName=[ \t]*([^\r\n]+?)[ \t]*$")
RESOURCE_SECTION = re.compile(r"(?m)^\s*\[(Container|Network|Volume|Pod|Image|Build|Kube|Artifact)\]\s*$")


@dataclass(frozen=True)
class Member:
    filename: str
    text: str


def parse_bundle(text: str) -> list[Member]:
    members = []
    for block in BUNDLE_SEPARATOR.split(text):
        if not block.strip():
            continue
        names = FILE_NAME.findall(block)
        types = RESOURCE_SECTION.findall(block)
        if len(names) != 1 or len(types) != 1:
            raise InstallError("Mỗi phần .quadlets cần một '# FileName=<name>' và một section tài nguyên.")
        name = names[0]
        if not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*", name) or ".." in name:
            raise InstallError(f"FileName trong bundle không hợp lệ: {name!r}")
        extension = RESOURCE_TYPES[types[0]]
        # Podman always appends the resource extension to FileName, then trims the block.
        members.append(Member(f"{name}.{extension}", block.strip()))
    if not members or len({member.filename for member in members}) != len(members):
        raise InstallError("Bundle rỗng hoặc có FileName trùng lặp.")
    return members


@dataclass(frozen=True)
class InstallSource:
    path: Path
    filenames: tuple[str, ...]


def installation_sources(context: InstallContext, main: Path,
                         extras: dict[str, Path]) -> list[InstallSource]:
    if context.config.file_type == "quadlets":
        names = tuple(member.filename for member in parse_bundle(main.read_text(encoding="utf-8")))
    else:
        text = main.read_text(encoding="utf-8")
        if RESOURCE_SECTION.findall(text) != ["Container"]:
            raise InstallError("File .container cần đúng một section [Container].")
        names = (main.name,)
    sources = []
    for extension in ("network", "volume"):
        filename = f"{context.service_name}.{extension}"
        source = extras.get(filename, within(context.service_dir, filename))
        if source.is_file():
            if filename in names:
                raise InstallError(f"Quadlet phụ trùng với bundle: {filename}")
            if RESOURCE_SECTION.findall(source.read_text(encoding="utf-8")) != [extension.title()]:
                raise InstallError(f"Section tài nguyên không hợp lệ trong {filename}.")
            sources.append(InstallSource(source, (filename,)))
    return sources + [InstallSource(main, names)]


@dataclass(frozen=True)
class Snapshot:
    content: str | None
    mode: int = 0o644


def snapshot(context: InstallContext, filename: str) -> Snapshot:
    path = within(context.install_location, filename)
    if not path.exists():
        return Snapshot(None)
    content = context.runner.run(["cat", str(path)], privileged=not context.config.rootless).stdout
    return Snapshot(content, stat.S_IMODE(path.stat().st_mode))


def install_quadlets(context: InstallContext, sources: list[InstallSource], staging: Path) -> bool:
    filenames = [filename for source in sources for filename in source.filenames]
    if len(filenames) != len(set(filenames)):
        raise InstallError("Các nguồn cài đặt có tên Quadlet trùng nhau.")
    privileged = not context.config.rootless
    context.runner.run(["mkdir", "-p", str(context.install_location)], privileged=privileged)
    backups = {name: snapshot(context, name) for name in filenames}
    try:
        for source in sources:
            text = source.path.read_text(encoding="utf-8")
            expected = ({member.filename: member.text for member in parse_bundle(text)}
                        if source.path.suffix == ".quadlets" else {source.path.name: text})
            if all(backups[name].content == expected[name] for name in source.filenames):
                # Preserve timestamps too: rewriting identical definitions makes systemd
                # report NeedDaemonReload=yes even when the service need not restart.
                continue
            # Preserve the old installer's workaround, scoped to the definitions in this run.
            for filename in source.filenames:
                destination = within(context.install_location, filename)
                context.runner.run(["rm", "-f", str(destination)], privileged=privileged)
            context.runner.run(["podman", "quadlet", "install", "--replace", "--reload-systemd=false",
                                str(source.path)], privileged=privileged)
        current = {name: snapshot(context, name) for name in filenames}
        missing = [name for name, item in current.items() if item.content is None]
        if missing:
            raise InstallError(f"Podman không tạo các definition dự kiến: {', '.join(missing)}")
        return any(current[name].content != backups[name].content for name in filenames)
    except (Exception, KeyboardInterrupt) as error:
        context.log(">>> Cài Quadlet thất bại; đang khôi phục definition trước lần chạy này...")
        failures = []
        for name, backup in backups.items():
            destination = within(context.install_location, name)
            try:
                if backup.content is None:
                    context.runner.run(["rm", "-f", str(destination)], privileged=privileged)
                else:
                    saved = within(staging, f"backup/{name}")
                    write_text(saved, backup.content)
                    context.runner.run(["install", "-m", f"{backup.mode:04o}", str(saved), str(destination)],
                                       privileged=privileged)
            except (InstallError, OSError) as restore_error:
                failures.append(f"{name}: {restore_error}")
        if failures:
            # Keep recovery data outside TemporaryDirectory so CLI cleanup cannot destroy it.
            recovery = Path(tempfile.mkdtemp(prefix=f"{context.service_name}-quadlet-recovery-"))
            for name, backup in backups.items():
                if backup.content is not None:
                    write_text(within(recovery, name), backup.content)
            raise InstallError(f"{error}\nKhôi phục chưa hoàn tất: {'; '.join(failures)}\nBackup: {recovery}") from error
        if isinstance(error, KeyboardInterrupt):
            raise
        raise InstallError(f"Cài Quadlet thất bại; đã khôi phục definition. {error}") from error

import shutil
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from installer.common import InstallError
from installer.config import ServiceConfig
from installer.context import build_context
from installer.quadlet import parse_bundle

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class FakeRunner:
    """A local filesystem simulation; never invokes a process or a real service."""

    def __init__(self, destination: Path, cwd: Path):
        self.destination = destination
        self.cwd = cwd
        self.calls = []
        self.install_count = 0
        self.fail_install_on = None
        self.fail_restore = False
        self.host_owner = "1000:1000"
        self.namespace_owner = "0:0"
        self.status = {}

    def run(self, argv, *, privileged=False, check=True):
        argv = list(map(str, argv))
        self.calls.append((argv, privileged, check))
        stdout = ""
        code = 0
        if argv[0] == "cat":
            stdout = Path(argv[1]).read_text(encoding="utf-8")
        elif argv[0] == "mkdir":
            Path(argv[-1]).mkdir(parents=True, exist_ok=True)
        elif argv[0] == "rm":
            Path(argv[-1]).unlink(missing_ok=True)
        elif argv[0] == "install":
            if self.fail_restore:
                raise InstallError("simulated restore failure")
            shutil.copyfile(argv[-2], argv[-1])
        elif argv[:4] == ["podman", "quadlet", "install", "--help"]:
            stdout = "--replace --reload-systemd"
        elif argv == ["podman", "--version"]:
            stdout = "podman version 6.1.3"
        elif argv[:3] == ["podman", "quadlet", "install"]:
            self.install_count += 1
            if self.install_count == self.fail_install_on:
                # Simulate a partial bundle installation before the error.
                source = Path(argv[-1])
                if source.suffix == ".quadlets":
                    first = parse_bundle(source.read_text(encoding="utf-8"))[0]
                    (self.destination / first.filename).write_text(first.text, encoding="utf-8")
                raise InstallError("simulated Podman failure")
            source = Path(argv[-1])
            if source.suffix == ".quadlets":
                for member in parse_bundle(source.read_text(encoding="utf-8")):
                    (self.destination / member.filename).write_text(member.text, encoding="utf-8")
            else:
                shutil.copyfile(source, self.destination / source.name)
        elif argv[0] == "stat":
            stdout = self.host_owner
        elif argv[:3] == ["podman", "unshare", "stat"]:
            stdout = self.namespace_owner
        elif argv[0] == "systemctl" and "is-active" in argv:
            code = self.status.get(argv[-1], 0)
        return subprocess.CompletedProcess(argv, code, stdout, "simulated stderr" if code else "")


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="quadlet-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.service = self.root / "services with spaces" / "demo"
        shutil.copytree(EXAMPLES / "demo", self.service,
                        ignore=shutil.ignore_patterns("__dbg_template__", "__pycache__"))
        self.destination = self.root / "installed definitions"
        self.runner = FakeRunner(self.destination, self.service)

    def context(self, **overrides):
        variables = {"HOST_IPV4": "192.0.2.10", "HOST_ULA_IPV6": "fd00::10",
                     "PRIVATE_DOMAIN": "hs.lan", "PUBLIC_DOMAIN": "example.test"}
        variables.update(overrides.pop("variables", {}))
        config = replace(ServiceConfig(), **overrides)
        context = build_context(config, self.service, "demo", variables, self.runner, home=self.home)
        context.install_location = self.destination
        context.variables["INSTALL_LOCATION"] = str(self.destination)
        context.log = lambda message: None
        return context

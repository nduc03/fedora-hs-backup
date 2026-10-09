import base64
import io
import json
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from installer.adguard import register_rewrites
from installer.commands import CommandRunner
from installer.common import InstallError
from installer.filesystem import namespace_ownership, prepare_directories
from installer.hooks import run_hooks, validate_hooks
from installer.quadlet import InstallSource, install_quadlets, installation_sources
from installer.systemd import update_services

from helpers import ServiceTest


class CommandTests(ServiceTest):
    def test_argv_cwd_privilege_and_no_shell(self):
        runner = CommandRunner(self.service)
        with patch("installer.commands.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "ok", "")) as process:
            runner.run(["echo", "a; $(command)"])
            self.assertEqual(process.call_args.args[0], ["echo", "a; $(command)"])
            self.assertEqual(process.call_args.kwargs["cwd"], self.service)
            self.assertNotIn("shell", process.call_args.kwargs)
            runner.run(["systemctl", "restart", "demo.service"], privileged=True)
            self.assertEqual(process.call_args.args[0][0], "sudo")

    def test_command_failure_and_unchecked_status(self):
        runner = CommandRunner(self.service)
        with patch("installer.commands.subprocess.run", return_value=subprocess.CompletedProcess([], 3, "", "down")):
            with self.assertRaises(InstallError):
                runner.run(["command"])
            self.assertEqual(runner.run(["command"], check=False).returncode, 3)
        with patch("installer.commands.subprocess.run", side_effect=FileNotFoundError("missing")):
            with self.assertRaises(InstallError):
                runner.run(["missing"])


class FilesystemTests(ServiceTest):
    def test_namespace_owner_already_matches_does_not_chown(self):
        context = self.context(container_uid=123, container_gid=456)
        self.runner.namespace_owner = "123:456"
        namespace_ownership(context, self.home)
        self.assertFalse(any("chown" in call[0] for call in self.runner.calls))

    def test_host_identity_and_configured_namespace_ids(self):
        context = self.context(container_uid=123, container_gid=456)
        self.runner.host_owner = "999:999"
        with patch("installer.filesystem.os.getuid", return_value=2000, create=True), patch("installer.filesystem.os.getgid", return_value=3000, create=True):
            namespace_ownership(context, self.home)
        self.assertIn((["chown", "-R", "2000:3000", str(self.home)], True, True), self.runner.calls)
        self.assertIn((["podman", "unshare", "chown", "-R", "123:456", str(self.home)], False, True), self.runner.calls)

    def test_matching_host_does_not_reset_owner(self):
        context = self.context()
        with patch("installer.filesystem.os.getuid", return_value=1000, create=True), patch("installer.filesystem.os.getgid", return_value=1000, create=True):
            namespace_ownership(context, self.home)
        self.assertFalse(any(argv[0] == "chown" for argv, _, _ in self.runner.calls))
        self.assertTrue(any(argv[:3] == ["podman", "unshare", "chown"] for argv, _, _ in self.runner.calls))

    def test_rootful_uses_privilege_and_skips_unshare(self):
        prepare_directories(self.context(rootless=False, mount_dirs=("data",), config_dirs=("config",)))
        self.assertTrue(all(privileged for _, privileged, _ in self.runner.calls))
        self.assertFalse(any(argv[0] == "podman" for argv, _, _ in self.runner.calls))
        cp = next(argv for argv, _, _ in self.runner.calls if argv[0] == "cp")
        self.assertEqual(cp[2], f"{self.service / 'config'}/.")

    def test_rootless_config_resets_host_owner_before_copy(self):
        with patch("installer.filesystem.os.getuid", return_value=2000, create=True), patch("installer.filesystem.os.getgid", return_value=3000, create=True):
            prepare_directories(self.context(config_dirs=("config",)))
        calls = [argv for argv, _, _ in self.runner.calls]
        self.assertLess(next(index for index, argv in enumerate(calls) if argv[0] == "chown"),
                        next(index for index, argv in enumerate(calls) if argv[0] == "cp"))

    def test_config_source_and_target_cannot_overlap(self):
        context = self.context(config_dirs=("config",))
        context.service_data_dir = self.service
        with self.assertRaisesRegex(InstallError, "lồng nhau"):
            prepare_directories(context)
        self.assertEqual(self.runner.calls, [])

    def test_config_symlink_cannot_escape_declared_root(self):
        link = self.service / "config/outside"
        try:
            link.symlink_to(self.home, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this host")
        with self.assertRaises(InstallError):
            prepare_directories(self.context(config_dirs=("config",)))
        self.assertEqual(self.runner.calls, [])


class HookTests(ServiceTest):
    def test_service_helper_import_and_context(self):
        (self.service / "service_utils.py").write_text("VALUE='helper'\n")
        (self.service / "hooks/custom.py").write_text("from service_utils import VALUE\ndef run(ctx):\n    ctx.variables['RESULT'] = VALUE + ':' + ctx.service_name\n")
        self.addCleanup(lambda: __import__("sys").modules.pop("service_utils", None))
        context = self.context(hooks={"pre_install": ("hooks/custom.py:run",)})
        validate_hooks(context)
        run_hooks(context, "pre_install")
        self.assertEqual(context.variables["RESULT"], "helper:demo")

    def test_missing_hook_callable_or_exception(self):
        for content in ("OTHER=1\n", "def run(ctx):\n    raise RuntimeError('hook failed')\n", "def run(ctx):\n    raise SystemExit(0)\n"):
            (self.service / "hooks/custom.py").write_text(content)
            context = self.context(hooks={"pre_install": ("hooks/custom.py:run",)})
            with self.subTest(content=content), self.assertRaisesRegex(InstallError, "Hook pre_install thất bại"):
                run_hooks(context, "pre_install")
        with self.assertRaisesRegex(InstallError, "Thiếu module hook"):
            validate_hooks(self.context(hooks={"pre_install": ("hooks/missing.py:run",)}))

    def test_hook_import_path_is_restored(self):
        import sys
        original = list(sys.path)
        run_hooks(self.context(hooks={"pre_install": ("hooks/pre_install.py:run",)}), "pre_install")
        self.assertEqual(sys.path, original)


class QuadletTests(ServiceTest):
    def source(self, filename="demo.container", text="[Container]\nImage=new\n"):
        stage = self.root / "staged"
        stage.mkdir(exist_ok=True)
        path = stage / filename
        path.write_text(text)
        return stage, path

    def test_new_and_unchanged_definitions(self):
        context = self.context()
        stage, path = self.source()
        sources = installation_sources(context, path, {})
        self.assertTrue(install_quadlets(context, sources, stage))
        commands = [argv for argv, _, _ in self.runner.calls if argv[:3] == ["podman", "quadlet", "install"]]
        self.assertTrue(all("--reload-systemd=false" in argv for argv in commands))
        original_stat = (self.destination / "demo.container").stat()
        self.runner.calls.clear()
        self.assertFalse(install_quadlets(context, sources, stage))
        self.assertEqual(self.runner.install_count, 1)
        current_stat = (self.destination / "demo.container").stat()
        self.assertEqual(current_stat.st_mtime_ns, original_stat.st_mtime_ns)
        self.assertEqual(current_stat.st_ino, original_stat.st_ino)
        self.assertFalse(any(argv[0] == "rm" for argv, _, _ in self.runner.calls))

    def test_network_only_change_is_detected(self):
        context = self.context()
        stage, path = self.source()
        network = self.service / "demo.network"
        network.write_text("[Network]\nSubnet=192.0.2.0/24\n")
        sources = installation_sources(context, path, {})
        install_quadlets(context, sources, stage)
        self.runner.calls.clear()
        network.write_text("[Network]\nSubnet=198.51.100.0/24\n")
        self.assertTrue(install_quadlets(context, sources, stage))
        installs = [argv for argv, _, _ in self.runner.calls if argv[:3] == ["podman", "quadlet", "install"]]
        self.assertEqual(len(installs), 1)
        self.assertEqual(Path(installs[0][-1]).name, "demo.network")

    def test_failure_restores_all_old_definitions_and_keeps_unrelated_files(self):
        context = self.context()
        stage, main = self.source()
        (self.service / "demo.network").write_text("[Network]\nnew\n")
        self.destination.mkdir()
        originals = {"demo.container": "[Container]\nImage=old\n", "demo.network": "[Network]\nold\n", "unrelated.container": "leave alone\n"}
        for name, content in originals.items():
            (self.destination / name).write_text(content)
        self.runner.fail_install_on = 2
        with self.assertRaisesRegex(InstallError, "đã khôi phục"):
            install_quadlets(context, installation_sources(context, main, {}), stage)
        for name, content in originals.items():
            self.assertEqual((self.destination / name).read_text(), content)
        self.assertFalse(any("unrelated.container" in " ".join(argv) for argv, _, _ in self.runner.calls))

    def test_partial_bundle_failure_restores_old_and_removes_new(self):
        context = self.context(file_type="quadlets", systemd_units=("demo.service", "worker.service"))
        text = "# FileName=demo\n[Container]\nImage=new\n---\n# FileName=worker\n[Container]\nImage=busybox\n"
        stage, main = self.source("demo.quadlets", text)
        self.destination.mkdir()
        (self.destination / "demo.container").write_text("old definition\n")
        self.runner.fail_install_on = 1
        with self.assertRaises(InstallError):
            install_quadlets(context, installation_sources(context, main, {}), stage)
        self.assertEqual((self.destination / "demo.container").read_text(), "old definition\n")
        self.assertFalse((self.destination / "worker.container").exists())

    def test_successful_bundle_tracks_all_members(self):
        context = self.context(file_type="quadlets", systemd_units=("demo.service", "worker.service"))
        stage, main = self.source("demo.quadlets", "# FileName=demo\n[Container]\n---\n# FileName=worker\n[Container]\n")
        sources = installation_sources(context, main, {})
        self.assertEqual(sources[0].filenames, ("demo.container", "worker.container"))
        self.assertTrue(install_quadlets(context, sources, stage))
        self.assertFalse(install_quadlets(context, sources, stage))
        self.assertEqual(self.runner.install_count, 1)

    def test_interruption_also_restores_definitions(self):
        context = self.context()
        stage, main = self.source()
        self.destination.mkdir()
        (self.destination / "demo.container").write_text("old\n")
        real_run = self.runner.run

        def interrupted(argv, **kwargs):
            if argv[:3] == ["podman", "quadlet", "install"]:
                raise KeyboardInterrupt()
            return real_run(argv, **kwargs)

        with patch.object(self.runner, "run", side_effect=interrupted), self.assertRaises(KeyboardInterrupt):
            install_quadlets(context, installation_sources(context, main, {}), stage)
        self.assertEqual((self.destination / "demo.container").read_text(), "old\n")

    def test_restore_failure_retains_backup_outside_staging(self):
        context = self.context()
        stage, main = self.source()
        self.destination.mkdir()
        (self.destination / "demo.container").write_text("old\n")
        self.runner.fail_install_on = 1
        self.runner.fail_restore = True
        recovery = self.root / "recovery"
        with patch("tempfile.mkdtemp", return_value=str(recovery)):
            with self.assertRaisesRegex(InstallError, "Backup:"):
                install_quadlets(context, installation_sources(context, main, {}), stage)
        self.assertEqual((recovery / "demo.container").read_text(), "old\n")

    def test_rootful_install_and_restore_commands_use_sudo(self):
        context = self.context(rootless=False)
        stage, main = self.source()
        install_quadlets(context, installation_sources(context, main, {}), stage)
        self.assertTrue(all(privileged for _, privileged, _ in self.runner.calls))

    def test_companion_collision_and_bad_sections_fail_before_commands(self):
        context = self.context(file_type="quadlets", systemd_units=("demo.service",))
        stage, main = self.source("demo.quadlets", "# FileName=demo\n[Network]\n")
        (self.service / "demo.network").write_text("[Network]\n")
        with self.assertRaises(InstallError):
            installation_sources(context, main, {})
        self.assertEqual(self.runner.calls, [])


class SystemdTests(ServiceTest):
    def test_changed_reloads_once_and_restarts_selected_units(self):
        update_services(self.context(systemd_units=("demo.service", "worker.service")), True)
        self.assertEqual([argv for argv, _, _ in self.runner.calls], [
            ["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "restart", "demo.service"],
            ["systemctl", "--user", "restart", "worker.service"]])

    def test_unchanged_only_starts_down_units(self):
        self.runner.status["worker.service"] = 3
        update_services(self.context(systemd_units=("demo.service", "worker.service")), False)
        calls = [argv for argv, _, _ in self.runner.calls]
        self.assertFalse(any("restart" in argv or "daemon-reload" in argv for argv in calls))
        self.assertEqual(calls[-1], ["systemctl", "--user", "start", "worker.service"])

    def test_status_failure_stops_instead_of_starting(self):
        self.runner.status["demo.service"] = 1
        with self.assertRaises(InstallError):
            update_services(self.context(), False)
        self.assertEqual(len(self.runner.calls), 1)

    def test_rootful_systemd_has_no_user_flag(self):
        update_services(self.context(rootless=False), True)
        self.assertTrue(all(privileged and "--user" not in argv for argv, privileged, _ in self.runner.calls))


class AdGuardTests(ServiceTest):
    def dns_context(self, **overrides):
        variables = {"ADGUARD_USERNAME": "admin", "ADGUARD_PASSWORD": "private:password"}
        variables.update(overrides)
        return self.context(variables=variables, enable_public_domain=True)

    def test_existing_ipv4_and_equivalent_ipv6_are_not_added(self):
        existing = [{"domain": "DEMO.example.test", "answer": "192.0.2.10"},
                    {"domain": "demo.example.test", "answer": "fd00:0:0:0:0:0:0:10"}]
        with patch("installer.adguard.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(existing).encode())) as request:
            register_rewrites(self.dns_context())
        self.assertEqual(request.call_count, 1)
        message = request.call_args.args[0]
        self.assertEqual(message.get_method(), "GET")
        self.assertEqual(message.headers["Authorization"], "Basic " + base64.b64encode(b"admin:private:password").decode())
        self.assertEqual(request.call_args.kwargs["timeout"], 30)

    def test_adds_missing_ipv4_and_ula_with_json(self):
        with patch("installer.adguard.urllib.request.urlopen", side_effect=[io.BytesIO(b"[]"), io.BytesIO(b""), io.BytesIO(b"")]) as request:
            register_rewrites(self.dns_context())
        bodies = [json.loads(call.args[0].data) for call in request.call_args_list[1:]]
        self.assertEqual(bodies, [{"domain": "demo.example.test", "answer": "192.0.2.10"},
                                 {"domain": "demo.example.test", "answer": "fd00::10"}])
        self.assertTrue(all(call.args[0].get_method() == "POST" for call in request.call_args_list[1:]))

    def test_fallback_link_local_and_global_ipv6_are_skipped(self):
        for ipv6 in ("::1", "fe80::1", "2001:db8::1"):
            with self.subTest(ipv6=ipv6), patch("installer.adguard.urllib.request.urlopen", side_effect=[io.BytesIO(b"[]"), io.BytesIO(b"")]) as request:
                register_rewrites(self.dns_context(HOST_ULA_IPV6=ipv6))
            self.assertEqual(request.call_count, 2)

    def test_invalid_response_and_network_errors_stop_without_leaking_credentials(self):
        for content in (b"bad json", b"{}", b'[{}]'):
            with self.subTest(content=content), patch("installer.adguard.urllib.request.urlopen", return_value=io.BytesIO(content)), self.assertRaises(InstallError):
                register_rewrites(self.dns_context())
        for error in (urllib.error.URLError("private:password"), urllib.error.HTTPError("url", 401, "private:password", {}, None)):
            with patch("installer.adguard.urllib.request.urlopen", side_effect=error), self.assertRaises(InstallError) as caught:
                register_rewrites(self.dns_context())
            self.assertNotIn("private:password", str(caught.exception))

    def test_missing_credentials_fail_before_request(self):
        with patch("installer.adguard.urllib.request.urlopen") as request, self.assertRaises(InstallError):
            register_rewrites(self.context(enable_public_domain=True))
        request.assert_not_called()

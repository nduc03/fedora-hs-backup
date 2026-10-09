import contextlib
import io
import os
import shutil
from pathlib import Path
from unittest.mock import Mock, patch

from installer.cli import main, preflight, run_pipeline, validate_execution
from installer.common import InstallError
from installer.config import load_config
from installer.context import build_context

from helpers import EXAMPLES, ServiceTest


class CliTests(ServiceTest):
    def test_cli_reconfigures_ansi_output_for_vietnamese(self):
        buffer = io.BytesIO()
        output = io.TextIOWrapper(buffer, encoding="cp1252")
        with patch("installer.cli.Path.home", return_value=self.home), contextlib.redirect_stdout(output):
            code = main(["demo", "--services-root", str(self.service.parent), "--dbg-templ"])
            output.flush()
            text = buffer.getvalue().decode("utf-8")
        self.assertEqual(code, 0)
        self.assertIn("Thư mục service", text)
        output.close()

    def test_debug_sample_does_not_import_hooks_or_run_installation(self):
        # Even module-level hook side effects must not run during a preview.
        (self.service / "hooks/pre_install.py").write_text("raise RuntimeError('must never import during preview')\n")
        original = Path.cwd()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch("installer.cli.Path.home", return_value=self.home))
            operations = [stack.enter_context(patch(f"installer.cli.{name}")) for name in
                          ("validate_execution", "preflight", "prepare_directories", "run_hooks", "install_quadlets", "update_services")]
            dns = stack.enter_context(patch("installer.cli.adguard.register_rewrites"))
            process = stack.enter_context(patch("installer.commands.subprocess.run"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            code = main(["demo", "--services-root", str(self.service.parent), "--dbg-templ"])
        self.assertEqual(code, 0)
        self.assertEqual(Path.cwd(), original)
        for operation in (*operations, dns, process):
            operation.assert_not_called()
        output = self.service / "__dbg_template__"
        self.assertTrue((output / "demo.container").is_file())
        self.assertTrue((output / "demo.env").is_file())
        self.assertTrue((output / "config/app.conf").is_file())
        self.assertFalse((self.service / "demo.env").exists())
        self.assertFalse((self.service / "config/app.conf").exists())

    def test_default_root_is_home_not_current_directory(self):
        with patch("installer.cli.Path.home", return_value=self.service.parent), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["demo", "--dbg-templ"]), 0)

    def test_bundle_example_debug(self):
        shutil.copytree(EXAMPLES / "stack", self.service.parent / "stack")
        with patch("installer.cli.Path.home", return_value=self.home), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["stack", "--services-root", str(self.service.parent), "--dbg-templ"]), 0)
        self.assertTrue((self.service.parent / "stack/__dbg_template__/stack.quadlets").is_file())

    def test_no_template_debug_still_returns_before_install(self):
        (self.service / "install.toml").write_text('use_template=false\n[variables]\nHOST_IPV4="192.0.2.10"\nHOST_ULA_IPV6="::1"\n')
        (self.service / "demo.container").write_text("[Container]\nImage=$UNCHANGED\n")
        with patch("installer.cli.Path.home", return_value=self.home), patch("installer.cli.install_quadlets") as install, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["demo", "--services-root", str(self.service.parent), "--dbg-templ"]), 0)
        install.assert_not_called()
        self.assertIn("$UNCHANGED", (self.service / "__dbg_template__/demo.container").read_text())

    def test_missing_config_returns_error_and_restores_cwd(self):
        (self.service / "install.toml").unlink()
        original = Path.cwd()
        with contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(["demo", "--services-root", str(self.service.parent), "--dbg-templ"]), 1)
        self.assertIn("install.toml", error.getvalue())
        self.assertEqual(Path.cwd(), original)

    def test_linux_and_standard_user_required_for_real_install(self):
        config = load_config(self.service)
        with patch("installer.cli.sys.platform", "win32"), self.assertRaisesRegex(InstallError, "Linux"):
            validate_execution(config)
        with patch("installer.cli.sys.platform", "linux"), patch("installer.cli.os.geteuid", return_value=0, create=True), self.assertRaisesRegex(InstallError, "tài khoản thường"):
            validate_execution(config)

    def test_missing_command_and_unsupported_podman_are_rejected(self):
        with patch("installer.cli.sys.platform", "linux"), patch("installer.cli.os.geteuid", return_value=1000, create=True), patch("installer.cli.shutil.which", return_value=None), self.assertRaisesRegex(InstallError, "Thiếu lệnh"):
            validate_execution(self.context().config)
        context = self.context()
        context.runner = Mock()
        context.runner.run.return_value.stdout = "old help"
        with self.assertRaisesRegex(InstallError, "reload-systemd"):
            preflight(context)

    def test_bundle_version_checked_before_mutation(self):
        context = self.context(file_type="quadlets", systemd_units=("demo.service",))
        context.runner = Mock()
        context.runner.run.side_effect = [Mock(stdout="--reload-systemd"), Mock(stdout="podman version 5.7.0")]
        with self.assertRaisesRegex(InstallError, "5.8"):
            preflight(context)

    def test_unresolved_noninteractive_aborts_before_publishing_or_installing(self):
        context = self.context(extra_template_files=("config/app.conf.template",))
        with patch("installer.cli.sys.stdin.isatty", return_value=False), self.assertRaisesRegex(InstallError, "biến chưa khai báo"):
            run_pipeline(context, debug=False, allow_unresolved=False)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse((self.service / "config/app.conf").exists())

    def test_interactive_unresolved_decline_and_accept(self):
        for answer in ("n", "y"):
            context = self.context()
            self.runner.calls.clear()
            with patch("installer.cli.sys.stdin.isatty", return_value=True), patch("builtins.input", return_value=answer):
                if answer == "n":
                    with self.assertRaises(InstallError):
                        run_pipeline(context, debug=False, allow_unresolved=False)
                    self.assertEqual(self.runner.calls, [])
                else:
                    run_pipeline(context, debug=False, allow_unresolved=False)
                    self.assertTrue((self.destination / "demo.container").is_file())

    def test_complete_pipeline_hook_order_and_unchanged_second_run(self):
        (self.service / "hooks/pre_install.py").write_text("def run(ctx):\n    assert (ctx.service_dir / 'config/app.conf').is_file()\n    ctx.runner.run(['record', 'pre'])\n")
        (self.service / "hooks/post_install.py").write_text("def run(ctx):\n    ctx.runner.run(['record', 'post'])\n")
        context = self.context(extra_template_files=("config/app.conf.template",),
                               variables={"IMAGE": "nginx", "APP_MESSAGE": "hello"},
                               hooks={"pre_install": ("hooks/pre_install.py:run",), "post_install": ("hooks/post_install.py:run",)})
        run_pipeline(context, debug=False, allow_unresolved=False)
        calls = [argv for argv, _, _ in self.runner.calls]
        before = calls.index(["record", "pre"])
        install = next(index for index, argv in enumerate(calls) if argv[:3] == ["podman", "quadlet", "install"] and "--replace" in argv)
        restart = calls.index(["systemctl", "--user", "restart", "demo.service"])
        after = calls.index(["record", "post"])
        self.assertLess(before, install)
        self.assertLess(install, restart)
        self.assertLess(restart, after)
        self.runner.calls.clear()
        run_pipeline(context, debug=False, allow_unresolved=False)
        self.assertFalse(any("restart" in argv or "daemon-reload" in argv for argv, _, _ in self.runner.calls))

    def test_hook_failure_stops_before_quadlet_install(self):
        (self.service / "hooks/pre_install.py").write_text("def run(ctx):\n    raise RuntimeError('failure')\n")
        context = self.context(hooks={"pre_install": ("hooks/pre_install.py:run",)})
        with self.assertRaisesRegex(InstallError, "pre_install"):
            run_pipeline(context, debug=False, allow_unresolved=True)
        self.assertEqual(self.runner.install_count, 0)
        self.assertFalse(any(argv[0] == "systemctl" for argv, _, _ in self.runner.calls))

    def test_dns_credentials_preflight_before_publishing(self):
        context = self.context(enable_public_domain=True, extra_template_files=("config/app.conf.template",))
        with self.assertRaisesRegex(InstallError, "ADGUARD_USERNAME"):
            run_pipeline(context, debug=False, allow_unresolved=True)
        self.assertFalse((self.service / "config/app.conf").exists())
        self.assertEqual(self.runner.install_count, 0)

import contextlib
import io
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from installer.cli import main, run_pipeline
from installer.common import InstallError
from installer.config import load_config
from installer.tpl_engines import RenderResult, load_engine
from installer.tpl_engines.legacy import LegacyEngine
from installer.tpl_engines.shell import ShellEngine
from installer.templates import render_templates

from helpers import EXAMPLES, ServiceTest


class LegacyEngineTests(unittest.TestCase):
    def test_case_insensitive_tokens_and_variable_keys(self):
        result = LegacyEngine().render("%var_name% %VAR_NAME% %Var_Name% %OTHER%",
                                       {"VAR_NAME": "value", "other": "lowercase key"})
        self.assertEqual(result, RenderResult("value value value lowercase key"))

    def test_unknown_empty_single_pass_and_literal_dollars(self):
        text = "%VALUE% %EMPTY% %unknown% %UNKNOWN% $VALUE ${VALUE} $2b$10$salt"
        result = LegacyEngine().render(text, {"VALUE": "%OTHER%/$HOME/\\path", "EMPTY": "", "OTHER": "wrong"})
        self.assertEqual(result.text, "%OTHER%/$HOME/\\path  %unknown% %UNKNOWN% $VALUE ${VALUE} $2b$10$salt")
        self.assertEqual(result.unresolved, ("UNKNOWN",))

    def test_native_percent_specifiers_and_non_variable_tokens(self):
        text = "%n %i 100% %9% %bad-name% %%NAME%%"
        self.assertEqual(LegacyEngine().render(text, {"NAME": "ok"}),
                         RenderResult("%n %i 100% %9% %bad-name% %ok%"))

    def test_conflicting_case_aliases_are_rejected_without_values(self):
        with self.assertRaises(InstallError) as caught:
            LegacyEngine().render("%name%", {"NAME": "secret-one", "name": "secret-two"})
        self.assertIn("NAME", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(LegacyEngine().render("%name%", {"NAME": "same", "name": "same"}), RenderResult("same"))


class EngineFactoryTests(ServiceTest):
    def plugin(self, source):
        directory = self.root / "plugin modules with spaces"
        directory.mkdir(exist_ok=True)
        module_name = "example_template_plugin"
        (directory / f"{module_name}.py").write_text(source, encoding="utf-8")
        self.addCleanup(lambda: sys.modules.pop(module_name, None))
        return directory, module_name

    def test_default_aliases_and_explicit_class(self):
        self.assertIsInstance(load_engine("shell"), ShellEngine)
        self.assertIsInstance(load_engine("legacy"), LegacyEngine)
        self.assertIsInstance(load_engine("installer.engines.legacy:LegacyEngine"), LegacyEngine)
        (self.service / "install.toml").write_text("")
        self.assertEqual(load_config(self.service).template_engine, "shell")

    def test_toml_accepts_module_class_and_rejects_invalid_selectors(self):
        for selector in ("legacy", "installer.engines.legacy:LegacyEngine", "my_engines.jinja:JinjaEngine"):
            (self.service / "install.toml").write_text(f'template_engine="{selector}"')
            self.assertEqual(load_config(self.service).template_engine, selector)
        for value in ('""', '"unknown"', '"../engine.py:Engine"', 'false', '5', '[]'):
            with self.subTest(value=value), self.assertRaisesRegex(InstallError, "template_engine"):
                (self.service / "install.toml").write_text(f"template_engine={value}")
                load_config(self.service)
        with self.assertRaisesRegex(InstallError, "phải là class"):
            load_engine("os:system")

    def test_import_missing_class_constructor_and_contract_errors(self):
        directory, name = self.plugin('''
class NoRender:
    pass
class NeedsArguments:
    def __init__(self, argument): pass
    def render(self, text, variables): pass
class Stops:
    def __init__(self): raise SystemExit(0)
''')
        with patch.object(sys, "path", [str(directory), *sys.path]):
            for selector in ("example_missing_engine:Engine", f"{name}:Missing", f"{name}:NoRender",
                             f"{name}:NeedsArguments", f"{name}:Stops"):
                with self.subTest(selector=selector), self.assertRaises(InstallError):
                    load_engine(selector)

    def test_external_class_is_loaded_once_and_shared_by_main_and_extras(self):
        directory, name = self.plugin(r'''
import re
from installer.engines import RenderResult
class AngleEngine:
    created = 0
    rendered = 0
    def __init__(self):
        type(self).created += 1
    def render(self, text, variables):
        type(self).rendered += 1
        assert variables['IMAGE'] == 'nginx'
        return RenderResult(re.sub(r'\[\[([A-Z_]+)\]\]', lambda match: variables[match[1]], text))
''')
        (self.service / "demo.container.template").write_text("[Container]\nImage=[[IMAGE]]\n")
        (self.service / "message.template").write_text("[[APP_MESSAGE]]")
        (self.service / "install.toml").write_text(f'template_engine="{name}:AngleEngine"')
        self.assertEqual(load_config(self.service).template_engine, f"{name}:AngleEngine")
        context = self.context(template_engine=f"{name}:AngleEngine", extra_template_files=("message.template",),
                               variables={"IMAGE": "nginx", "APP_MESSAGE": "custom-engine"})
        with patch.object(sys, "path", [str(directory), *sys.path]):
            rendered = render_templates(context, self.root / "stage")
        self.assertEqual(rendered.main.staged.read_text(), "[Container]\nImage=nginx\n")
        self.assertEqual(rendered.extras[0].staged.read_text(), "custom-engine")
        engine_class = sys.modules[name].AngleEngine
        self.assertEqual(engine_class.created, 1)
        self.assertEqual(engine_class.rendered, 2)

    def test_explicit_injection_and_read_only_variables(self):
        (self.service / "demo.container.template").write_text("[Container]\nImage=provided\n")
        context = self.context(template_engine="not_installed.engine:Engine")

        class InjectedEngine:
            def render(self, text, variables):
                with self_test.assertRaises(TypeError):
                    variables["SERVICE_NAME"] = "wrong"
                return RenderResult(text, ("UNKNOWN",))

        self_test = self
        with patch("installer.templates.load_engine") as factory:
            rendered = render_templates(context, self.root / "stage", engine=InjectedEngine())
        factory.assert_not_called()
        self.assertEqual(rendered.main.unresolved, ("UNKNOWN",))
        self.assertEqual(context.variables["SERVICE_NAME"], "demo")

    def test_render_errors_include_file_and_engine_without_secrets(self):
        for result in ("plain string", RenderResult(1), RenderResult("text", ["UNKNOWN"]),
                       RenderResult("text", (5,))):
            engine = Mock()
            engine.render.return_value = result
            with self.subTest(result=result), self.assertRaisesRegex(InstallError, "RenderResult"):
                render_templates(self.context(), self.root / "stage", engine=engine)
        for error in (ValueError("secret-value"), SystemExit("secret-value")):
            engine = Mock()
            engine.render.side_effect = error
            with self.assertRaises(InstallError) as caught:
                render_templates(self.context(), self.root / "stage", engine=engine)
            self.assertIn("demo.container.template", str(caught.exception))
            self.assertIn("shell", str(caught.exception))
            self.assertNotIn("secret-value", str(caught.exception))

    def test_disabled_templates_do_not_load_engine(self):
        (self.service / "demo.container").write_text("[Container]\nImage=%IMAGE% $IMAGE\n")
        context = self.context(use_template=False, template_engine="not_installed.engine:Engine")
        with patch("installer.templates.load_engine") as factory:
            rendered = render_templates(context, self.root / "stage")
        factory.assert_not_called()
        self.assertEqual(rendered.main.staged.read_text(), "[Container]\nImage=%IMAGE% $IMAGE\n")


class EnginePipelineTests(ServiceTest):
    def test_unknown_engine_stops_before_installation(self):
        with self.assertRaisesRegex(InstallError, "render template"):
            run_pipeline(self.context(template_engine="not_installed.engine:Engine"), debug=False, allow_unresolved=False)
        self.assertEqual(self.runner.calls, [])

    def test_legacy_unknown_warns_and_blocks_real_install(self):
        (self.service / "demo.container.template").write_text("[Container]\nImage=%Unknown_Image%\n")
        context = self.context(template_engine="legacy")
        context.log = Mock()
        with patch("installer.cli.sys.stdin.isatty", return_value=False), self.assertRaisesRegex(InstallError, "biến chưa khai báo"):
            run_pipeline(context, debug=False, allow_unresolved=False)
        context.log.assert_any_call("[WARNING] demo.container: biến chưa khai báo: UNKNOWN_IMAGE")
        self.assertEqual(self.runner.calls, [])

    def test_legacy_render_preserves_adguard_bootstrap_skip(self):
        (self.service / "demo.container.template").write_text("[Container]\nImage=%image%\n")
        context = self.context(template_engine="legacy", enable_public_domain=True,
                               variables={"IMAGE": "docker.io/adguard/adguardhome:latest"})
        with patch("installer.adguard.urllib.request.urlopen") as request:
            run_pipeline(context, debug=False, allow_unresolved=False)
        request.assert_not_called()
        self.assertTrue((self.destination / "demo.container").is_file())

    def test_legacy_sample_debug_uses_toml_and_does_not_install(self):
        shutil.copytree(EXAMPLES / "legacy", self.service.parent / "legacy",
                        ignore=shutil.ignore_patterns("__dbg_template__", "__pycache__"))
        with patch("installer.cli.Path.home", return_value=self.home), \
                patch("installer.cli.preflight") as preflight, \
                patch("installer.cli.run_hooks") as hooks, \
                patch("installer.commands.subprocess.run") as process, \
                contextlib.redirect_stdout(io.StringIO()):
            code = main(["legacy", "--services-root", str(self.service.parent), "--dbg-templ"])
        self.assertEqual(code, 0)
        preflight.assert_not_called()
        hooks.assert_not_called()
        process.assert_not_called()
        output = self.service.parent / "legacy/__dbg_template__"
        main_text = (output / "legacy.container").read_text(encoding="utf-8")
        self.assertIn("Image=docker.io/library/nginx:alpine", main_text)
        self.assertIn("ContainerName=legacy", main_text)
        extra_text = (output / "config/message.txt").read_text(encoding="utf-8")
        self.assertIn("$HOME và %another_var%", extra_text)
        self.assertIn("Tên service: legacy", extra_text)

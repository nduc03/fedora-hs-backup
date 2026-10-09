import json
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

from installer.common import InstallError
from installer.context import build_context, discover_addresses, resolve_service
from installer.quadlet import parse_bundle
from installer.templates import publish_templates, render_templates, substitute
from installer.traefik import inject_labels

from helpers import EXAMPLES, ServiceTest


class SubstitutionTests(ServiceTest):
    def test_var_braces_unknown_empty_and_single_pass(self):
        text, missing = substitute("$A ${A} ${A}tail $MISSING ${EMPTY}", {"A": "$B", "EMPTY": ""})
        self.assertEqual(text, "$B $B $Btail $MISSING ")
        self.assertEqual(missing, ("MISSING",))

    def test_envsubst_style_dollars_operators_and_command_text(self):
        text = "$$A $$$A $9 ${A:-default} $(command) `command` \\$A %service_dir%"
        output, missing = substitute(text, {"A": "ok"})
        self.assertEqual(output, "$ok $$ok $9 ${A:-default} $(command) `command` \\ok %service_dir%")
        self.assertEqual(missing, ())

    def test_password_hashes_are_not_variables(self):
        text = "bcrypt=$2b$10$salt sha=$6$salt$hash argon=$argon2id$v=19$m=64,t=2,p=1$salt$hash $REAL"
        output, missing = substitute(text, {"salt": "WRONG", "hash": "WRONG"})
        self.assertEqual(output, text)
        self.assertEqual(missing, ("REAL",))


class ContextTests(ServiceTest):
    def test_service_with_spaces_and_name_sanitization(self):
        directory = self.service.parent / "My Service (v1.0)!"
        directory.mkdir()
        path, name = resolve_service(self.service.parent, directory.name)
        self.assertEqual(path, directory.resolve())
        self.assertEqual(name, "My-Service-v1-0")
        for name in ("../demo", str(self.service), "..", "!!!"):
            if name == "!!!":
                (self.service.parent / name).mkdir()
            with self.subTest(name=name), self.assertRaises(InstallError):
                resolve_service(self.service.parent, name)

    def test_reserved_context_overrides_env_and_raw_ipv6(self):
        context = self.context(variables={"SERVICE_DIR": "/wrong", "HOST_ULA_IPV6": "[fd12::1]"})
        self.assertEqual(context.variables["SERVICE_DIR"], str(self.service))
        self.assertEqual(context.host_ula_ipv6, "fd12::1")
        self.assertEqual(context.variables["HOST_ULA_IPV6"], "[fd12::1]")
        self.assertEqual(context.systemd_units, ("demo.service",))

    def test_rootful_paths_and_custom_data_dir(self):
        context = self.context(rootless=False, service_data_dir="~/custom-data")
        self.assertEqual(context.install_location, self.destination)  # overridden by fixture
        self.assertEqual(context.service_data_dir, self.home / "custom-data")
        self.assertEqual(context.systemctl_argv, ["systemctl"])
        self.assertEqual(context.variables["SYSTEMCTL_CMD"], "sudo systemctl")

    def test_rootless_install_path_honors_process_xdg_config_home(self):
        config_home = self.root / "custom config"
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": str(config_home)}):
            context = build_context(self.context().config, self.service, "demo",
                                    {"HOST_IPV4": "192.0.2.10", "HOST_ULA_IPV6": "::1"},
                                    self.runner, home=self.home)
        self.assertEqual(context.install_location, config_home / "containers/systemd")
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": "relative"}), self.assertRaises(InstallError):
            self.context()

    def test_discovery_accepts_fc_ula_on_default_interface(self):
        runner = Mock()
        runner.run.side_effect = [subprocess.CompletedProcess([], 0, json.dumps([{"dev": "eth0"}])),
                                 subprocess.CompletedProcess([], 0, json.dumps([{"addr_info": [
                                     {"local": "192.0.2.20"}, {"local": "fe80::1"}, {"local": "fc01::20"}]}]))]
        self.assertEqual(discover_addresses(runner), ("192.0.2.20", "fc01::20"))
        self.assertEqual(runner.run.call_args.args[0][-1], "eth0")

    def test_no_ula_falls_back_and_explicit_addresses_avoid_discovery(self):
        runner = Mock()
        runner.run.side_effect = [subprocess.CompletedProcess([], 0, '[{"dev":"eth0"}]'),
                                 subprocess.CompletedProcess([], 0, '[{"addr_info":[{"local":"192.0.2.20"}]}]')]
        self.assertEqual(discover_addresses(runner), ("192.0.2.20", "::1"))
        with patch("installer.context.discover_addresses") as discovery:
            self.context()
        discovery.assert_not_called()

    def test_bad_addresses_fail(self):
        with self.assertRaises(InstallError):
            self.context(variables={"HOST_IPV4": "wrong"})

    def test_debug_without_ip_preserves_missing_ipv4(self):
        with patch("installer.context.sys.platform", "win32"):
            context = build_context(self.context().config, self.service, "demo", {}, self.runner,
                                    home=self.home, debug=True)
        self.assertEqual(context.host_ipv4, "")
        self.assertNotIn("HOST_IPV4", context.variables)


class RenderTests(ServiceTest):
    def test_extra_outputs_are_staged_until_publish(self):
        context = self.context(extra_template_files=("config/app.conf.template",), variables={"IMAGE": "nginx", "APP_MESSAGE": "hello"})
        staging = self.root / "stage"
        rendered = render_templates(context, staging)
        self.assertFalse((self.service / "config/app.conf").exists())
        publish_templates(context, rendered, debug=True)
        self.assertTrue((self.service / "__dbg_template__/config/app.conf").is_file())
        self.assertFalse((self.service / "config/app.conf").exists())
        publish_templates(context, rendered, debug=False)
        self.assertTrue((self.service / "config/app.conf").is_file())
        self.assertFalse((self.service / "demo.container").exists())

    def test_missing_or_duplicate_main_extra_fails(self):
        for extras in (("missing.conf.template",), ("demo.container.template",)):
            with self.subTest(extras=extras), self.assertRaises(InstallError):
                render_templates(self.context(extra_template_files=extras), self.root / "stage")

    def test_use_template_false_copies_raw_and_skips_extras(self):
        (self.service / "demo.container").write_text("[Container]\nImage=$IMAGE\n")
        context = self.context(use_template=False, use_traefik_labels=True,
                               extra_template_files=("missing.conf.template",))
        rendered = render_templates(context, self.root / "stage")
        self.assertEqual(rendered.main.staged.read_text(), "[Container]\nImage=$IMAGE\n")
        self.assertEqual(rendered.extras, ())

    def test_traefik_lan_and_public_labels(self):
        context = self.context(use_traefik_labels=True, enable_public_domain=True)
        output = inject_labels("[Unit]\n[Container]\nImage=nginx\n", context)
        self.assertIn("Network=traefik.network", output)
        self.assertIn("Host(`demo.hs.lan`)", output)
        self.assertIn("Host(`demo.example.test`)", output)
        self.assertIn("tls.certresolver=leresolver", output)
        self.assertLess(output.index("Label="), output.index("Image="))

    def test_bundle_labels_only_claim_primary_router(self):
        text = "# FileName=demo\n[Container]\nImage=nginx\n---\n# FileName=worker\n[Container]\nImage=busybox\n"
        context = self.context(file_type="quadlets", use_traefik_labels=True, systemd_units=("demo.service", "worker.service"))
        members = parse_bundle(inject_labels(text, context))
        self.assertIn("Label=", members[0].text)
        self.assertNotIn("Label=", members[1].text)

    def test_invalid_traefik_domain_or_section(self):
        for context, text in ((self.context(use_traefik_labels=True, variables={"PRIVATE_DOMAIN": "https://bad"}), "[Container]\n"),
                              (self.context(use_traefik_labels=True), "[Volume]\n")):
            with self.assertRaises(InstallError):
                inject_labels(text, context)

    def test_sample_bundle_parse(self):
        text = (EXAMPLES / "stack/stack.quadlets.template").read_text(encoding="utf-8")
        self.assertEqual([item.filename for item in parse_bundle(text)],
                         ["stack.container", "stack-worker.container", "stack.network", "stack.volume"])

    def test_bundle_matches_podman_extension_and_separator_rules(self):
        text = "# FileName=web.container\n[Container]\n  ---  \n# FileName=cache\n[Volume]\n"
        self.assertEqual([item.filename for item in parse_bundle(text)], ["web.container.container", "cache.volume"])
        with self.assertRaises(InstallError):
            parse_bundle("# FileName =web\n[Container]\n")

    def test_invalid_bundle_metadata(self):
        invalid = ["", "[Container]\n", "# FileName=../x\n[Container]\n",
                   "# FileName=x\n[Container]\n[Volume]\n",
                   "# FileName=x\n[Container]\n---\n# FileName=x\n[Container]\n"]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(InstallError):
                parse_bundle(text)

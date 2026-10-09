import os
from pathlib import Path
from unittest.mock import patch

from installer.common import InstallError, within
from installer.config import load_config
from installer.environment import load_environment, read_env

from helpers import ServiceTest


class ConfigTests(ServiceTest):
    def config_text(self, text):
        (self.service / "install.toml").write_text(text, encoding="utf-8")
        return load_config(self.service)

    def test_defaults(self):
        config = self.config_text("")
        self.assertTrue(config.rootless)
        self.assertTrue(config.use_template)
        self.assertEqual(config.file_type, "container")
        self.assertFalse(config.use_traefik_labels)
        self.assertFalse(config.enable_public_domain)
        self.assertEqual(config.container_uid, 1000)
        self.assertEqual(config.container_gid, 1000)
        self.assertEqual(config.mount_dirs, ())

    def test_sample_and_typed_variables(self):
        config = load_config(self.service)
        self.assertEqual(config.config_dirs, ("config",))
        self.assertEqual(config.hooks["pre_install"], ("hooks/pre_install.py:run",))
        config = self.config_text('[variables]\nCOUNT=5\nENABLED=true\nRATIO=1.5\n')
        self.assertEqual(config.variables, {"COUNT": "5", "ENABLED": "true", "RATIO": "1.5"})

    def test_invalid_settings(self):
        invalid = ['rootless="true"', 'file_type="pod"', 'mount_dirs="data"',
                   'mount_dirs=["data", "data"]', 'mount_dirs=["../escape"]',
                   'extra_template_files=["config.ini"]', 'container_uid=true',
                   'container_gid=-1', 'systemd_units=["bad/unit.service"]',
                   'unknown_option=true', 'service_data_dir=5',
                   '[variables]\nBAD=[]', '[hooks]\npre_install="hooks/a.py:run"',
                   '[hooks]\nprepare=[]', '[hooks]\npre_install=["../bad.py:run"]',
                   '[hooks]\npre_install=["hooks/a.sh:run"]', 'file_type="quadlets"']
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(InstallError):
                self.config_text(text)

    def test_missing_config_does_not_run_shell(self):
        (self.service / "install.toml").unlink()
        (self.service / "install.sh").write_text("touch SHOULD_NOT_EXIST")
        with self.assertRaisesRegex(InstallError, "không tự đọc install.sh"):
            load_config(self.service)
        self.assertFalse((self.service / "SHOULD_NOT_EXIST").exists())

    def test_toml_error_does_not_include_values(self):
        with self.assertRaises(InstallError) as caught:
            self.config_text('secret="private-value\n')
        self.assertNotIn("private-value", str(caught.exception))

    def test_bundle_requires_explicit_units(self):
        config = self.config_text('file_type="quadlets"\nsystemd_units=["demo.service", "worker.service"]')
        self.assertEqual(config.systemd_units, ("demo.service", "worker.service"))


class EnvironmentTests(ServiceTest):
    def test_literal_env_quotes_comments_bom_crlf(self):
        path = self.service / "ctv.env"
        path.write_bytes(b"\xef\xbb\xbf# comment\r\nexport PLAIN=value # comment\r\nHASH='user:$2b$10$abc'\r\n"
                         b'DOUBLE="a $VAR $(command) `command` \\path" # comment\r\n'
                         b"URL=x#fragment\r\nEMPTY=\r\n")
        result = read_env(path)
        self.assertEqual(result["PLAIN"], "value")
        self.assertEqual(result["HASH"], "user:$2b$10$abc")
        self.assertEqual(result["DOUBLE"], "a $VAR $(command) `command` \\path")
        self.assertEqual(result["URL"], "x#fragment")
        self.assertEqual(result["EMPTY"], "")

    def test_precedence_sorted_local_files_and_ignored_debug(self):
        (self.home / "hs-info.env").write_text("A=global\nGLOBAL=kept\n")
        (self.service / "ctv.env").write_text("A=local-root\n")
        for directory, value in (("a", "local-a"), ("z", "local-z"), ("__dbg_template__", "wrong")):
            path = self.service / directory
            path.mkdir()
            (path / "ctv.env").write_text(f"A={value}\n")
        env = load_environment(self.service, {}, home=self.home, inherited={"A": "process", "B": "process"})
        self.assertEqual(env, {"A": "local-z", "B": "process", "GLOBAL": "kept"})
        self.assertEqual(load_environment(self.service, {"A": "toml"}, home=self.home, inherited={})["A"], "toml")

    def test_invalid_env_reports_file_and_line_without_value(self):
        path = self.service / "ctv.env"
        for line in ("echo secret", 'A="secret', "A='secret' trailing"):
            path.write_text("# comment\n" + line)
            with self.subTest(line=line), self.assertRaises(InstallError) as caught:
                read_env(path)
            self.assertIn(":2:", str(caught.exception))
            self.assertNotIn("secret", str(caught.exception))

    def test_env_does_not_evaluate_or_expand(self):
        path = self.service / "ctv.env"
        path.write_text("A=$HOME\nB=$(touch marker)\nC=${A:-default}\n")
        with patch("subprocess.run") as process:
            self.assertEqual(read_env(path), {"A": "$HOME", "B": "$(touch marker)", "C": "${A:-default}"})
        process.assert_not_called()


class PathTests(ServiceTest):
    def test_reject_absolute_traversal_and_root_itself(self):
        for relative in ("/etc/passwd", "../escape", "config/../x", "C:/outside", "config\\x", ".", ""):
            with self.subTest(relative=relative), self.assertRaises(InstallError):
                within(self.service, relative)

    def test_reject_symlink_outside(self):
        link = self.service / "linked"
        try:
            link.symlink_to(self.home, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this host")
        with self.assertRaises(InstallError):
            within(self.service, "linked/secret")

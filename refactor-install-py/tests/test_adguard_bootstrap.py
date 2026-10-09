import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from installer.adguard import is_bootstrap_service
from installer.cli import run_pipeline

from helpers import ServiceTest


ADGUARD_IMAGES = (
    "adguard/adguardhome",
    "adguard/adguardhome:latest",
    "docker.io/adguard/adguardhome:v0.107.70",
    "docker.io/adguard/adguardhome@sha256:" + "a" * 64,
    "registry.example.test:5000/adguard/adguardhome:latest@sha256:" + "b" * 64,
    '"docker.io/adguard/adguardhome:latest"',
    "'adguard/adguardhome:latest'",
)
OTHER_IMAGES = (
    "docker.io/library/nginx:latest",
    "docker.io/not-adguard/adguardhome:latest",
    "docker.io/adguard/adguardhome-exporter:latest",
    "docker.io/adguard/adguardhome-backup:latest",
    "$IMAGE",
)


class ImageDetectionTests(unittest.TestCase):
    def test_tags_digests_registry_and_quotes(self):
        for image in ADGUARD_IMAGES:
            with self.subTest(image=image):
                self.assertTrue(is_bootstrap_service(f"[Container]\n Image = {image}\n"))

    def test_other_images_comments_and_sections(self):
        for image in OTHER_IMAGES:
            with self.subTest(image=image):
                self.assertFalse(is_bootstrap_service(f"[Container]\nImage={image}\n"))
        self.assertFalse(is_bootstrap_service("[Container]\n# Image=adguard/adguardhome\n"))
        self.assertFalse(is_bootstrap_service("[Service]\nImage=adguard/adguardhome\n"))
        self.assertTrue(is_bootstrap_service(
            "# FileName=web\n[Container]\nImage=nginx\n---\n"
            "# FileName=dns\n[Container]\nImage=adguard/adguardhome:latest\n"))


class BootstrapPipelineTests(ServiceTest):
    def test_rendered_adguard_image_skips_credentials_and_all_http(self):
        for image in ADGUARD_IMAGES:
            context = self.context(enable_public_domain=True, use_traefik_labels=True,
                                   variables={"IMAGE": image})
            context.log = Mock()
            with self.subTest(image=image), patch("installer.adguard.validate_settings") as settings, \
                    patch("installer.adguard.urllib.request.urlopen") as request, \
                    patch("installer.cli.adguard.register_rewrites") as register:
                run_pipeline(context, debug=False, allow_unresolved=False)
            settings.assert_not_called()
            request.assert_not_called()
            register.assert_not_called()
            context.log.assert_any_call(">>> Bỏ qua DNS rewrite: service dùng image AdGuard Home (bootstrap).")
            self.assertIn("certresolver=leresolver", (self.destination / "demo.container").read_text())

    def test_bundle_containing_adguard_skips_dns(self):
        (self.service / "demo.quadlets.template").write_text(
            "# FileName=demo\n[Container]\nImage=nginx\n---\n"
            "# FileName=dns\n[Container]\nImage=${IMAGE}\n")
        context = self.context(file_type="quadlets", systemd_units=("demo.service", "dns.service"),
                               enable_public_domain=True, variables={"IMAGE": "adguard/adguardhome:latest"})
        with patch("installer.adguard.urllib.request.urlopen") as request:
            run_pipeline(context, debug=False, allow_unresolved=False)
        request.assert_not_called()
        self.assertTrue((self.destination / "dns.container").is_file())

    def test_direct_container_without_template_skips_dns(self):
        (self.service / "demo.container").write_text("[Container]\nImage=docker.io/adguard/adguardhome:latest\n")
        context = self.context(use_template=False, enable_public_domain=True)
        with patch("installer.adguard.urllib.request.urlopen") as request:
            run_pipeline(context, debug=False, allow_unresolved=False)
        request.assert_not_called()

    def test_regular_image_still_registers_dns(self):
        context = self.context(enable_public_domain=True, variables={
            "IMAGE": "nginx", "ADGUARD_USERNAME": "example", "ADGUARD_PASSWORD": "example-only"})
        with patch("installer.adguard.urllib.request.urlopen",
                   side_effect=[io.BytesIO(b"[]"), io.BytesIO(b""), io.BytesIO(b"")]) as request:
            run_pipeline(context, debug=False, allow_unresolved=False)
        self.assertEqual(request.call_count, 3)


@unittest.skipUnless(sys.platform.startswith("linux"), "Bash regression checks run on Linux")
class BashBootstrapTests(ServiceTest):
    def setUp(self):
        super().setUp()
        template = Path(__file__).resolve().parents[2] / "home/nduc/install-v2.sh.template"
        if not template.is_file():
            self.skipTest("Run from the repository checkout to test the Bash template")
        text = template.read_text(encoding="utf-8-sig")
        definitions = text[text.index("quadlet_uses_adguard_home() {"):
                           text.index('\necho ">>> Validating execution environment..."')]
        self.harness = self.root / "dns-test.sh"
        self.harness.write_text(definitions + '''
QUADLET_FILE_LOCATION="$1"
HOME="$2"
SCRIPT_DIR="$3"
SERVICE_NAME=dns
PUBLIC_DOMAIN=example.test
HOST_IPV4=192.0.2.10
HOST_ULA_IPV6=::1
ADGUARD_USERNAME=example
ADGUARD_PASSWORD=example-only
curl() { echo API_CALLED >&2; return 77; }
jq() { return 0; }
if [[ "$4" == missing-credentials ]]; then
    unset PUBLIC_DOMAIN ADGUARD_USERNAME ADGUARD_PASSWORD
fi
register_adguard_rewrites
''', encoding="utf-8")

    def invoke(self, quadlet, mode="credentials"):
        path = self.service / "dns.container"
        path.write_text(quadlet, encoding="utf-8")
        return subprocess.run(["bash", str(self.harness), str(path), str(self.home),
                               str(self.service), mode], capture_output=True, text=True)

    def test_bootstrap_skips_api_even_without_credentials(self):
        for image in ADGUARD_IMAGES:
            with self.subTest(image=image):
                result = self.invoke(f"[Container]\nImage={image}\n", "missing-credentials")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Skipping DNS rewrites", result.stdout)
                self.assertNotIn("API_CALLED", result.stderr)

    def test_regular_images_still_call_api(self):
        for image in OTHER_IMAGES:
            with self.subTest(image=image):
                result = self.invoke(f"[Container]\nImage={image}\n")
                self.assertEqual(result.returncode, 1)
                self.assertIn("API_CALLED", result.stderr)

    def test_bundle_image_and_other_section(self):
        result = self.invoke("[Network]\n---\n[Container]\nImage=adguard/adguardhome:latest\n")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("API_CALLED", result.stderr)
        result = self.invoke("[Container]\nImage=nginx\n[Service]\nImage=adguard/adguardhome\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("API_CALLED", result.stderr)

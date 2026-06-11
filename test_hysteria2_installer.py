import importlib.util
import pathlib
import unittest
from unittest import mock


def load_installer():
    path = pathlib.Path(__file__).with_name("hysteria2-installer.py")
    spec = importlib.util.spec_from_file_location("hysteria2_installer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerConfigTests(unittest.TestCase):
    def test_static_masquerade_choices_only_include_high_plausibility_templates(self):
        installer = load_installer()

        choices = installer.get_static_masquerade_choices()

        names = [name for _label, name in choices]
        self.assertEqual(names, ["api-doc", "404"])

    def test_domain_uses_acme_certificate(self):
        installer = load_installer()

        with mock.patch.object(installer, "ask_input", side_effect=["example.com", "admin@example.com"]):
            cert = installer.collect_certificate_config()

        self.assertEqual(cert["cert_mode"], "acme")
        self.assertEqual(cert["domain"], "example.com")
        self.assertEqual(cert["email"], "admin@example.com")

    def test_empty_domain_uses_self_signed_certificate(self):
        installer = load_installer()

        with mock.patch.object(installer, "ask_input", return_value=""):
            cert = installer.collect_certificate_config()

        self.assertEqual(cert["cert_mode"], "self-signed")
        self.assertEqual(cert["domain"], "")
        self.assertEqual(cert["email"], "")

    def test_acme_custom_port_notice_says_custom_port_is_allowed(self):
        installer = load_installer()

        notice = installer.get_acme_custom_port_notice(44880)

        self.assertIn("当前自定义端口 44880/udp 可以继续使用", notice)
        self.assertIn("443/udp 只是更像普通 HTTP/3 网站的建议", notice)
        self.assertIn("ACME 证书验证仍需域名解析正确，并确保 80/443 验证端口可达", notice)


if __name__ == "__main__":
    unittest.main()

import unittest

import probe_gfw_like_masquerade as probe


class ProbeResultTests(unittest.TestCase):
    def test_detects_static_api_page(self):
        result = probe.classify_http3_response(
            probe.Http3ProbeResult(
                ok=True,
                status_code=200,
                headers={"content-type": "text/html"},
                body="<html><title>API Documentation</title><h1>API Reference</h1></html>",
            )
        )

        self.assertEqual(result.level, "PASS")
        self.assertIn("API", result.message)

    def test_detects_nginx_default_page(self):
        result = probe.classify_http3_response(
            probe.Http3ProbeResult(
                ok=True,
                status_code=200,
                headers={"content-type": "text/html"},
                body="<html><title>Welcome to nginx!</title></html>",
            )
        )

        self.assertEqual(result.level, "PASS")
        self.assertIn("nginx", result.message)

    def test_warns_on_empty_http3_response(self):
        result = probe.classify_http3_response(
            probe.Http3ProbeResult(ok=True, status_code=200, headers={}, body="")
        )

        self.assertEqual(result.level, "WARN")

    def test_fails_when_http3_probe_failed(self):
        result = probe.classify_http3_response(
            probe.Http3ProbeResult(ok=False, error="timed out")
        )

        self.assertEqual(result.level, "FAIL")
        self.assertIn("timed out", result.message)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import sys
import types
import unittest
from unittest.mock import patch


class WebResearchFetchTests(unittest.TestCase):
    def test_fetch_url_validates_relative_redirect_against_response_url(self):
        fake_httpx = types.ModuleType("httpx")
        fake_httpx.Client = object
        fake_httpx.Response = object
        fake_trafilatura = types.ModuleType("trafilatura")
        fake_trafilatura.extract = lambda *args, **kwargs: None
        spec = importlib.util.spec_from_file_location(
            "test_fetch_module",
            "/home/runner/work/Huxley/Huxley/PeteHaughie/Huxley/harness/web_research/fetch.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        fetch_module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"httpx": fake_httpx, "trafilatura": fake_trafilatura}):
            spec.loader.exec_module(fetch_module)

        seen_urls = []

        def fake_is_safe_url(url):
            seen_urls.append(url)
            return True

        class FakeResponse:
            def __init__(self):
                self.headers = {"location": "/login"}
                self.url = "https://example.com/start"
                self.text = "<html><body>hello</body></html>"

            def raise_for_status(self):
                return None

        class FakeClient:
            def __init__(self, *args, **kwargs):
                self._hooks = kwargs["event_hooks"]["response"]

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def get(self, url, headers=None):
                response = FakeResponse()
                for hook in self._hooks:
                    hook(response)
                return response

        with (
            patch.object(fetch_module, "_is_safe_url", side_effect=fake_is_safe_url),
            patch.object(fetch_module.httpx, "Client", FakeClient),
            patch.object(fetch_module.trafilatura, "extract", side_effect=["body", "title"]),
        ):
            result = fetch_module.fetch_url("https://example.com/start")

        self.assertEqual(result["title"], "title")
        self.assertEqual(seen_urls, ["https://example.com/start", "https://example.com/login"])


if __name__ == "__main__":
    unittest.main()

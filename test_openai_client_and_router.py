import sys
import types
import unittest
from unittest.mock import MagicMock, patch

try:
    import httpx  # noqa: F401
except ImportError:
    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = object
    sys.modules["httpx"] = fake_httpx

from harness.server.inference import OpenAICompatibleClient


class OpenAICompatibleClientTests(unittest.TestCase):
    @patch("harness.server.inference.httpx.Client")
    def test_chat_posts_json_without_stream_flag(self, client_cls):
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        response.raise_for_status.return_value = None

        client = MagicMock()
        client.post.return_value = response
        client_cls.return_value.__enter__.return_value = client

        api = OpenAICompatibleClient(endpoint="http://localhost:1234/v1", model="alpha")
        api.chat(messages=[{"role": "user", "content": "hello"}], max_tokens=16, temperature=0.2)

        sent_body = client.post.call_args.kwargs["json"]
        self.assertNotIn("stream", sent_body)

    @patch("harness.server.inference.httpx.Client")
    def test_chat_rejects_stream_true(self, client_cls):
        api = OpenAICompatibleClient(endpoint="http://localhost:1234/v1", model="alpha")

        with self.assertRaises(ValueError):
            api.chat(messages=[{"role": "user", "content": "hello"}], stream=True)

        client_cls.assert_not_called()

    @patch("harness.server.inference.httpx.Client")
    def test_stream_chat_sends_stream_true_and_yields_chunks(self, client_cls):
        chunk = {"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}
        sse_lines = [
            f"data: {__import__('json').dumps(chunk)}",
            "data: [DONE]",
        ]

        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.iter_lines.return_value = iter(sse_lines)

        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=resp)
        stream_ctx.__exit__ = MagicMock(return_value=False)

        client = MagicMock()
        client.stream.return_value = stream_ctx
        client_cls.return_value.__enter__.return_value = client

        api = OpenAICompatibleClient(endpoint="http://localhost:1234/v1", model="alpha")
        results = list(
            api.stream_chat(
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=16,
                temperature=0.5,
                request_options={"tools": [{"type": "function"}], "response_format": {"type": "json_object"}},
            )
        )

        sent_body = client.stream.call_args.kwargs["json"]
        self.assertTrue(sent_body.get("stream"))
        self.assertIn("tools", sent_body)
        self.assertIn("response_format", sent_body)

        self.assertEqual(results[0], chunk)
        self.assertEqual(results[-1], "[DONE]")

    @patch("harness.server.inference.httpx.Client")
    def test_stream_chat_stops_after_done(self, client_cls):
        chunk1 = {"choices": [{"delta": {"content": "a"}, "finish_reason": None}]}
        chunk2 = {"choices": [{"delta": {"content": "b"}, "finish_reason": None}]}
        sse_lines = [
            f"data: {__import__('json').dumps(chunk1)}",
            f"data: {__import__('json').dumps(chunk2)}",
            "data: [DONE]",
            f"data: {__import__('json').dumps({'should': 'not appear'})}",
        ]

        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.iter_lines.return_value = iter(sse_lines)

        stream_ctx = MagicMock()
        stream_ctx.__enter__ = MagicMock(return_value=resp)
        stream_ctx.__exit__ = MagicMock(return_value=False)

        client = MagicMock()
        client.stream.return_value = stream_ctx
        client_cls.return_value.__enter__.return_value = client

        api = OpenAICompatibleClient(endpoint="http://localhost:1234/v1", model="alpha")
        results = list(api.stream_chat(messages=[{"role": "user", "content": "go"}]))

        self.assertEqual(results, [chunk1, chunk2, "[DONE]"])


class RouterAliasCollisionTests(unittest.TestCase):
    def test_colliding_aliases_do_not_override_builtin_model_routes(self):
        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_gamma_module = types.ModuleType("harness.caste.gamma")

        class FakeAlpha:
            def __init__(self, tool_service=None):
                pass

        class FakeBeta:
            def __init__(self, **kwargs):
                pass

        class FakeGamma:
            def __init__(self, tool_service=None):
                pass

        fake_alpha_module.Alpha = FakeAlpha
        fake_beta_module.Beta = FakeBeta
        fake_gamma_module.Gamma = FakeGamma

        with (
            patch("harness.config.load_config", return_value={"api": {"alpha_model_id": "beta", "beta_model_id": "gemma-4-e4b"}}),
            patch.dict(
                sys.modules,
                {
                    "harness.caste.alpha": fake_alpha_module,
                    "harness.caste.beta": fake_beta_module,
                    "harness.caste.gamma": fake_gamma_module,
                },
            ),
        ):
            from harness.comms.router import Router

            router = Router()
            alpha_model, alpha_handler = router._resolve_openai_model("gemma-4-e4b")
            beta_model, beta_handler = router._resolve_openai_model("beta")

        self.assertEqual(alpha_model, "gemma-4-e4b")
        self.assertEqual(beta_model, "beta")
        self.assertIs(alpha_handler, router._alpha)
        self.assertIs(beta_handler, router._beta)

    def test_boolean_tools_config_is_normalized(self):
        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_tool_engine_module = types.ModuleType("harness.tool.engine")
        captured = {}

        class FakeAlpha:
            def __init__(self, tool_service=None):
                pass

        class FakeBeta:
            def __init__(self, **kwargs):
                pass

        class FakeGamma:
            def __init__(self, tool_service=None):
                pass

        class FakeToolService:
            def __init__(self, tools_cfg=None):
                captured["tools_cfg"] = tools_cfg

        fake_alpha_module.Alpha = FakeAlpha
        fake_beta_module.Beta = FakeBeta
        fake_gamma_module.Gamma = FakeGamma
        fake_tool_engine_module.ToolService = FakeToolService

        with (
            patch("harness.config.load_config", return_value={"tools": False}),
            patch.dict(
                sys.modules,
                {
                    "harness.caste.alpha": fake_alpha_module,
                    "harness.caste.beta": fake_beta_module,
                    "harness.caste.gamma": fake_gamma_module,
                    "harness.tool.engine": fake_tool_engine_module,
                },
            ),
        ):
            from harness.comms.router import Router

            router = Router()

        self.assertFalse(router.tools_enabled)
        self.assertEqual(captured["tools_cfg"], {"enabled": False})


if __name__ == "__main__":
    unittest.main()

import sys
import types
import unittest
from unittest.mock import patch

from harness.comms.router import OpenAIRequestError, Router
from harness.daemon.scheduler import SchedulerEngine


class SchedulerRouterReuseTests(unittest.TestCase):
    def test_openai_requests_reuse_single_router_instance(self):
        created = []

        class FakeRouter:
            def __init__(self):
                created.append(self)

            def openai_models(self):
                return []

            def openai_chat_completion(self, **kwargs):
                return {"choices": [{"message": {"content": "ok"}}]}

        engine = SchedulerEngine()

        with patch("harness.comms.router.Router", FakeRouter):
            engine.openai_models()
            engine.openai_chat_completion(
                model="alpha",
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=32,
                temperature=0.0,
            )

        self.assertEqual(len(created), 1)


class RouterOpenAIModelTests(unittest.TestCase):
    @patch("harness.comms.router.load_config", return_value={"api": {"alpha_model_id": 123, "beta_model_id": ""}})
    @patch("harness.caste.gamma.Gamma")
    @patch("harness.caste.beta.Beta")
    @patch("harness.caste.alpha.Alpha")
    def test_openai_models_cache_config_and_normalize_aliases(
        self,
        _alpha_cls,
        _beta_cls,
        _gamma_cls,
        load_config_mock,
    ):
        router = Router()

        model_ids = [model["id"] for model in router.openai_models()]
        resolved_id, _handler = router._resolve_openai_model("123")

        self.assertEqual(resolved_id, "123")
        self.assertIn("123", model_ids)
        self.assertIn("alpha", model_ids)
        self.assertIn("beta", model_ids)
        self.assertNotIn("", model_ids)
        load_config_mock.assert_called_once()

    def test_beta_tool_calling_raises_request_error_for_json_and_streaming(self):
        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_alpha_module.Alpha = lambda: object()
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_beta_module.Beta = lambda: object()
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_gamma_module.Gamma = lambda: object()
        with (
            patch("harness.comms.router.load_config", return_value={}),
            patch.dict(
                sys.modules,
                {
                    "harness.caste.alpha": fake_alpha_module,
                    "harness.caste.beta": fake_beta_module,
                    "harness.caste.gamma": fake_gamma_module,
                },
            ),
        ):
            router = Router()

            with self.assertRaises(OpenAIRequestError) as json_ctx:
                router.openai_chat_completion(
                    model="beta",
                    messages=[{"role": "user", "content": "hello"}],
                    request_options={"tools": [{"type": "function", "function": {"name": "ping"}}]},
                )

            with self.assertRaises(OpenAIRequestError) as stream_ctx:
                next(
                    router.openai_chat_completion_stream(
                        model="beta",
                        messages=[{"role": "user", "content": "hello"}],
                        request_options={"tools": [{"type": "function", "function": {"name": "ping"}}]},
                    )
                )

            self.assertEqual(
                str(json_ctx.exception),
                "tool calling is not supported for beta via the OpenAI-compatible API",
            )
            self.assertEqual(json_ctx.exception.status, 400)
            self.assertEqual(json_ctx.exception.error_type, "invalid_request_error")
            self.assertEqual(str(stream_ctx.exception), str(json_ctx.exception))

    def test_alpha_invalid_response_does_not_fallback_to_beta(self):
        class FakeAlpha:
            def complete_chat(self, *_args, **_kwargs):
                return "not-a-dict"

        class FakeBeta:
            def __init__(self):
                self.calls = 0

            def complete_chat(self, *_args, **_kwargs):
                self.calls += 1
                return "beta"

        class FakeGamma:
            pass

        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_alpha_module.Alpha = FakeAlpha
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_beta_module.Beta = FakeBeta
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_gamma_module.Gamma = FakeGamma

        with (
            patch("harness.comms.router.load_config", return_value={}),
            patch.dict(
                sys.modules,
                {
                    "harness.caste.alpha": fake_alpha_module,
                    "harness.caste.beta": fake_beta_module,
                    "harness.caste.gamma": fake_gamma_module,
                },
            ),
        ):
            router = Router()
            with self.assertRaises(RuntimeError) as ctx:
                router.openai_chat_completion(
                    model="alpha",
                    messages=[{"role": "user", "content": "hello"}],
                )

        self.assertEqual(str(ctx.exception), "invalid response from alpha model backend")
        self.assertEqual(router._beta.calls, 0)


if __name__ == "__main__":
    unittest.main()

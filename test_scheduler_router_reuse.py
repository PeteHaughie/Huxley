import sys
import types
import unittest
from unittest.mock import patch

from harness.comms.message import Action, Caste, Message
from harness.comms.router import OpenAIRequestError, Router
from harness.daemon.scheduler import SchedulerEngine, Schedule


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
    @patch("harness.config.load_config", return_value={"api": {"alpha_model_id": 123, "beta_model_id": ""}})
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
        fake_alpha_module.Alpha = lambda tool_service=None: object()
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_beta_module.Beta = lambda tool_service=None: object()
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_gamma_module.Gamma = lambda tool_service=None: object()
        with (
            patch("harness.config.load_config", return_value={}),
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
            def __init__(self, tool_service=None):
                pass
            def complete_chat(self, *_args, **_kwargs):
                return "not-a-dict"

        class FakeBeta:
            def __init__(self, tool_service=None):
                self.calls = 0

            def complete_chat(self, *_args, **_kwargs):
                self.calls += 1
                return "beta"

        class FakeGamma:
            def __init__(self, tool_service=None):
                pass

        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_alpha_module.Alpha = FakeAlpha
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_beta_module.Beta = FakeBeta
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_gamma_module.Gamma = FakeGamma

        with (
            patch("harness.config.load_config", return_value={}),
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

    def test_dispatch_rejects_tool_request_when_tools_disabled_in_config(self):
        class _FakeCaste:
            supports_tools = True

            def __init__(self, result_caste: Caste, call_counter: dict | None = None):
                self._result_caste = result_caste
                self._call_counter = call_counter

            def infer(self, _msg):
                if self._call_counter is not None:
                    self._call_counter["count"] += 1
                return Message(caste=self._result_caste, action=Action.INFER, payload={"result": "ok"})

        gamma_calls = {"count": 0}
        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_alpha_module.Alpha = lambda tool_service=None: _FakeCaste(Caste.ALPHA)
        fake_beta_module.Beta = lambda tool_service=None: _FakeCaste(Caste.BETA)
        fake_gamma_module.Gamma = lambda tool_service=None: _FakeCaste(
            Caste.GAMMA, call_counter=gamma_calls
        )

        with (
            patch("harness.config.load_config", return_value={"tools": {"enabled": False}}),
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
            resp = router.dispatch(
                Message(
                    caste=Caste.GAMMA,
                    action=Action.INFER,
                    payload={"prompt": "x", "tools": True},
                )
            )

        self.assertIn("error", resp.payload)
        self.assertIn("disabled", resp.payload["error"])
        self.assertEqual(gamma_calls["count"], 0)

    def test_dispatch_treats_tools_none_as_not_requested(self):
        class _FakeCaste:
            supports_tools = False

            def __init__(self, result_caste: Caste, call_counter: dict | None = None):
                self._result_caste = result_caste
                self._call_counter = call_counter

            def infer(self, _msg):
                if self._call_counter is not None:
                    self._call_counter["count"] += 1
                return Message(caste=self._result_caste, action=Action.INFER, payload={"result": "ok"})

        gamma_calls = {"count": 0}
        fake_alpha_module = types.ModuleType("harness.caste.alpha")
        fake_beta_module = types.ModuleType("harness.caste.beta")
        fake_gamma_module = types.ModuleType("harness.caste.gamma")
        fake_alpha_module.Alpha = lambda tool_service=None: _FakeCaste(Caste.ALPHA)
        fake_beta_module.Beta = lambda tool_service=None: _FakeCaste(Caste.BETA)
        fake_gamma_module.Gamma = lambda tool_service=None: _FakeCaste(
            Caste.GAMMA, call_counter=gamma_calls
        )

        with (
            patch("harness.config.load_config", return_value={"tools": {"enabled": True}}),
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
            resp = router.dispatch(
                Message(
                    caste=Caste.GAMMA,
                    action=Action.INFER,
                    payload={"prompt": "x", "tools": None},
                )
            )

        self.assertNotIn("error", resp.payload)
        self.assertEqual(gamma_calls["count"], 1)


class SchedulerSelfModTests(unittest.TestCase):
    def setUp(self):
        self.engine = SchedulerEngine()

    def test_self_mod_rejects_path_outside_allowed(self):
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            outside = f.name
        try:
            schedule = Schedule(
                when={"type": "interval", "every": 3600},
                action={"type": "self_mod", "file": outside, "content": "x=1"},
            )
            with self.assertRaises(RuntimeError) as ctx:
                self.engine._action_self_mod(schedule)
            self.assertIn("not in allowed directory", str(ctx.exception))
        finally:
            os.unlink(outside)

    @patch("harness.daemon.scheduler.JobBoard")
    @patch("harness.selfmod.validator.validate_patch")
    @patch("harness.selfmod.patcher.Patcher")
    def test_self_mod_posts_board_on_validation_failure(self, MockPatcher, mock_validate, MockBoard):
        mock_validate.return_value = {"ok": False, "errors": ["syntax error"], "warnings": []}
        MockPatcher.return_value.apply.return_value = {"ok": True, "changed": True, "diff": "--- a\n+++ b\n"}
        schedule = Schedule(
            when={"type": "interval", "every": 3600},
            action={"type": "self_mod", "file": __file__, "content": "bad code"},
        )
        self.engine._action_self_mod(schedule)
        MockBoard.return_value.create.assert_called_once()

    @patch("harness.daemon.scheduler.JobBoard")
    @patch("harness.selfmod.validator.validate_patch")
    @patch("harness.selfmod.patcher.Patcher")
    def test_self_mod_skips_board_when_no_changes(self, MockPatcher, mock_validate, MockBoard):
        mock_validate.return_value = {"ok": True, "errors": [], "warnings": []}
        MockPatcher.return_value.apply.return_value = {"ok": True, "changed": False}
        schedule = Schedule(
            when={"type": "interval", "every": 3600},
            action={"type": "self_mod", "file": __file__, "content": "x=1"},
        )
        self.engine._action_self_mod(schedule)
        MockBoard.return_value.create.assert_not_called()

    @patch("harness.selfmod.restart.register_reload_handler")
    @patch("harness.selfmod.validator.validate_patch")
    @patch("harness.selfmod.patcher.Patcher")
    def test_self_mod_auto_apply_calls_apply(self, MockPatcher, mock_validate, _mock_reload):
        mock_validate.return_value = {"ok": True, "errors": [], "warnings": []}
        mock_patcher = MockPatcher.return_value
        mock_patcher.apply.return_value = {"ok": True, "changed": True}
        schedule = Schedule(
            when={"type": "interval", "every": 3600},
            action={"type": "self_mod", "file": __file__, "content": "print('new')\n", "auto_apply": True},
        )
        self.engine._action_self_mod(schedule)
        mock_patcher.apply.assert_called_once()
        import signal
        if hasattr(signal, "SIGHUP"):
            self.assertTrue(self.engine._pending_reload)
        else:
            self.assertFalse(self.engine._pending_reload)

    @patch("harness.selfmod.validator.validate_patch")
    @patch("harness.selfmod.patcher.Patcher")
    def test_self_mod_rejects_empty_content(self, MockPatcher, mock_validate):
        schedule = Schedule(
            when={"type": "interval", "every": 3600},
            action={"type": "self_mod", "file": __file__, "content": ""},
        )
        with self.assertRaises(RuntimeError) as ctx:
            self.engine._action_self_mod(schedule)
        self.assertIn("empty content", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from harness.comms.router import Router
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


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()

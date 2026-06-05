import unittest

from harness.caste.beta import Beta
from harness.comms.message import Message, Caste, Action


class _FailingModel:
    def create_chat_completion(self, **kwargs):
        raise RuntimeError("llama_decode returned -3")


class _WorkingModel:
    def create_chat_completion(self, **kwargs):
        return {"choices": [{"message": {"content": "recovered"}}]}


class BetaRecoveryTests(unittest.TestCase):
    def test_decode_error_reloads_with_smaller_context_and_retries(self):
        beta = Beta({
            "model": "/tmp/fake-model.gguf",
            "ctx_size": 49152,
        })
        states = iter([
            _FailingModel(),
            _WorkingModel(),
        ])

        def fake_load():
            if beta._model is not None:
                return
            beta._model = next(states)

        beta._load = fake_load  # type: ignore[method-assign]

        msg = Message(
            caste=Caste.BETA,
            action=Action.INFER,
            payload={"prompt": "hello"},
            token_budget={"input": 256, "output": 32},
        )

        resp = beta.infer(msg)

        self.assertEqual(resp.payload["result"], "recovered")
        self.assertEqual(beta.ctx_size, 24576)


if __name__ == "__main__":
    unittest.main()

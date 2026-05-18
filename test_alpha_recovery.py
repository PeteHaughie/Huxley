import unittest

from harness.caste.alpha import Alpha


class _FailOnceClient:
    def __init__(self):
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("Server error '500 Internal Server Error' for url 'http://127.0.0.1:8081/v1/chat/completions'")
        return {"choices": [{"message": {"content": "ok after restart"}}]}


class AlphaRecoveryTests(unittest.TestCase):
    def test_chat_with_recovery_restarts_server_once_on_500(self):
        alpha = Alpha()
        client = _FailOnceClient()
        restarted = {"count": 0}

        alpha._client = client
        alpha._restart_server = lambda: restarted.__setitem__("count", restarted["count"] + 1) or True  # type: ignore[method-assign]

        resp = alpha._chat_with_recovery([{"role": "user", "content": "hello"}], 64)

        self.assertEqual(resp["choices"][0]["message"]["content"], "ok after restart")
        self.assertEqual(restarted["count"], 1)


if __name__ == "__main__":
    unittest.main()

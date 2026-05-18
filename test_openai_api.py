import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer

from harness.daemon import server as daemon_server


class _FakeScheduler:
    running = True

    def __init__(self):
        self.calls = []

    def openai_models(self) -> list[dict]:
        return [
            {"id": "alpha", "object": "model", "created": 0, "owned_by": "huxley", "permission": []},
            {"id": "beta", "object": "model", "created": 0, "owned_by": "huxley", "permission": []},
        ]

    def openai_chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> dict:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 123,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": f"ok:{model}"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


class OpenAIAPITests(unittest.TestCase):
    def setUp(self):
        self.original_scheduler = daemon_server._scheduler
        self.fake_scheduler = _FakeScheduler()
        daemon_server._scheduler = self.fake_scheduler
        self.server = HTTPServer(("127.0.0.1", 0), daemon_server.DaemonHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base_url = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        daemon_server._scheduler = self.original_scheduler

    def test_models_route_returns_openai_model_list(self):
        with urllib.request.urlopen(f"{self.base_url}/v1/models", timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["object"], "list")
        self.assertEqual([item["id"] for item in payload["data"]], ["alpha", "beta"])

    def test_chat_completions_route_forwards_request_shape(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "beta",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 64,
                    "temperature": 0.25,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["model"], "beta")
        self.assertEqual(payload["choices"][0]["message"]["content"], "ok:beta")
        self.assertEqual(len(self.fake_scheduler.calls), 1)
        self.assertEqual(self.fake_scheduler.calls[0]["messages"][0]["content"], "hello")
        self.assertEqual(self.fake_scheduler.calls[0]["max_tokens"], 64)
        self.assertEqual(self.fake_scheduler.calls[0]["temperature"], 0.25)

    def test_chat_completions_rejects_streaming(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "alpha",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": True,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read())
        self.assertIn("stream=true is not supported", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main()

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import HTTPServer
from unittest import mock

from harness.daemon import server as daemon_server


class _FakeScheduler:
    running = True

    def __init__(self):
        self.calls = []
        self.stream_calls = []

    def list_schedules(self) -> list:
        return []

    def openai_models(self) -> list[dict]:
        return [
            {"id": "gemma-4-e4b", "object": "model", "created": 0, "owned_by": "huxley-alpha", "permission": [], "root": "gemma-4-e4b", "parent": None},
            {"id": "alpha", "object": "model", "created": 0, "owned_by": "huxley-alpha", "permission": [], "root": "gemma-4-e4b", "parent": "gemma-4-e4b"},
            {"id": "ternary-bonsai-8b", "object": "model", "created": 0, "owned_by": "huxley-beta", "permission": [], "root": "ternary-bonsai-8b", "parent": None},
            {"id": "beta", "object": "model", "created": 0, "owned_by": "huxley-beta", "permission": [], "root": "ternary-bonsai-8b", "parent": "ternary-bonsai-8b"},
        ]

    def openai_chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_options: dict | None = None,
    ) -> dict:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "request_options": request_options,
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

    def openai_chat_completion_stream(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_options: dict | None = None,
    ):
        self.stream_calls.append(
            {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "request_options": request_options,
            }
        )
        yield {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": model,
            "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}],
        }
        yield {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 123,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
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
        model_ids = [item["id"] for item in payload["data"]]
        self.assertEqual(model_ids, ["gemma-4-e4b", "alpha", "ternary-bonsai-8b", "beta"])

    def test_status_route_reports_actual_server_port(self):
        with urllib.request.urlopen(f"{self.base_url}/v1/status", timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["openai_api"]["url"], f"{self.base_url}/v1")

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
        self.assertEqual(self.fake_scheduler.calls[0]["request_options"], {})

    def test_models_route_disabled_returns_openai_style_404(self):
        with mock.patch.object(
            daemon_server,
            "load_config",
            return_value={"api": {"enabled": False, "localhost_only": True}},
        ):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{self.base_url}/v1/models", timeout=5)

        self.assertEqual(ctx.exception.code, 404)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "not found")
        self.assertEqual(payload["error"]["type"], "not_found_error")

    def test_chat_completions_forwards_tools_and_tool_choice(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "gemma-4-e4b",
                    "messages": [{"role": "user", "content": "use the ping tool"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "ping",
                                "description": "ping tool",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "message": {"type": "string"}
                                    },
                                    "required": ["message"],
                                },
                            },
                        }
                    ],
                    "tool_choice": "auto",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["model"], "gemma-4-e4b")
        self.assertEqual(len(self.fake_scheduler.calls), 1)
        opts = self.fake_scheduler.calls[0]["request_options"]
        self.assertEqual(opts["tool_choice"], "auto")
        self.assertEqual(opts["tools"][0]["function"]["name"], "ping")

    def test_chat_completions_supports_streaming(self):
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = resp.read().decode()

        self.assertIn('data: {"id": "chatcmpl-stream"', payload)
        self.assertIn("data: [DONE]", payload)
        self.assertEqual(len(self.fake_scheduler.stream_calls), 1)
        self.assertEqual(self.fake_scheduler.stream_calls[0]["model"], "alpha")
        self.assertEqual(self.fake_scheduler.stream_calls[0]["request_options"], {})

    def test_chat_completions_streaming_empty_stream_returns_done(self):
        def empty_stream(**_kwargs):
            if False:
                yield {}

        self.fake_scheduler.openai_chat_completion_stream = empty_stream
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = resp.read().decode()

        self.assertEqual(payload.strip(), "data: [DONE]")

    def test_chat_completions_rejects_invalid_json(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=b"{",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "invalid JSON body")

    def test_chat_completions_rejects_non_json_content_type(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "alpha",
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ).encode(),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 415)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "Content-Type must be application/json")

    def test_chat_completions_rejects_remote_origin(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "alpha",
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": "https://example.com",
            },
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 403)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "Origin is not allowed")

    def test_chat_completions_rejects_invalid_ranges(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "alpha",
                    "messages": [{"role": "user", "content": "hello"}],
                    "max_tokens": 0,
                    "temperature": -0.25,
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "max_tokens must be greater than 0")

    def test_chat_completions_rejects_non_boolean_stream(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "alpha",
                    "messages": [{"role": "user", "content": "hello"}],
                    "stream": "false",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "stream must be a boolean")
        self.assertEqual(self.fake_scheduler.stream_calls, [])

    def test_chat_completions_hides_internal_errors(self):
        def boom(**_kwargs):
            raise Exception("secret/path should not leak")

        self.fake_scheduler.openai_chat_completion = boom
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "alpha",
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 500)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "internal server error")
        self.assertEqual(payload["error"]["type"], "server_error")

    def test_chat_completions_unknown_model_returns_not_found_error(self):
        def unknown_model(**_kwargs):
            raise ValueError("unknown model: nope")

        self.fake_scheduler.openai_chat_completion = unknown_model
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "nope",
                    "messages": [{"role": "user", "content": "hello"}],
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 404)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(payload["error"]["message"], "unknown model: nope")
        self.assertEqual(payload["error"]["type"], "not_found_error")

    def test_chat_completions_request_errors_return_400(self):
        def invalid_request(**_kwargs):
            raise daemon_server.OpenAIRequestError("tool calling is not supported for beta via the OpenAI-compatible API")

        self.fake_scheduler.openai_chat_completion = invalid_request
        req = urllib.request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "beta",
                    "messages": [{"role": "user", "content": "hello"}],
                    "tools": [{"type": "function", "function": {"name": "ping"}}],
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)

        self.assertEqual(ctx.exception.code, 400)
        payload = json.loads(ctx.exception.read())
        self.assertEqual(
            payload["error"]["message"],
            "tool calling is not supported for beta via the OpenAI-compatible API",
        )
        self.assertEqual(payload["error"]["type"], "invalid_request_error")

    def test_openai_routes_do_not_allow_cross_origin_reads_from_remote_origins(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/models",
            headers={"Origin": "https://example.com"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["object"], "list")
        self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_openai_routes_allow_cors_from_loopback_origins(self):
        req = urllib.request.Request(
            f"{self.base_url}/v1/models",
            headers={"Origin": "http://localhost:3000"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["object"], "list")
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

    def test_non_openai_routes_do_not_allow_cross_origin_reads_from_remote_origins(self):
        req = urllib.request.Request(
            f"{self.base_url}/health",
            headers={"Origin": "https://example.com"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["status"], "ok")
        self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_non_openai_routes_do_not_allow_cors_from_loopback_origins(self):
        req = urllib.request.Request(
            f"{self.base_url}/health",
            headers={"Origin": "http://localhost:3000"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read())

        self.assertEqual(payload["status"], "ok")
        self.assertIsNone(resp.headers.get("Access-Control-Allow-Origin"))

    def test_chat_completions_streaming_sends_done_after_error(self):
        from harness.comms.router import OpenAIRequestError as _OAIError

        def error_after_first_chunk(**_kwargs):
            yield {
                "id": "chatcmpl-err",
                "object": "chat.completion.chunk",
                "created": 123,
                "model": "alpha",
                "choices": [{"index": 0, "delta": {"content": "partial"}, "finish_reason": None}],
            }
            raise _OAIError("mid-stream error")

        self.fake_scheduler.openai_chat_completion_stream = error_after_first_chunk
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
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = resp.read().decode()

        self.assertIn("data: [DONE]", payload)


if __name__ == "__main__":
    unittest.main()

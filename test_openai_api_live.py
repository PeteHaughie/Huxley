import json
import os
import sys
import time
import unittest
import urllib.request
import urllib.error


LIVE_TEST_ENABLED = os.environ.get("HUXLEY_LIVE_API_TEST", "").lower() in {"1", "true", "yes", "on"}
LIVE_API_BASE = os.environ.get("HUXLEY_LIVE_API_BASE", "http://127.0.0.1:8083").rstrip("/")
LIVE_API_TIMEOUT = float(os.environ.get("HUXLEY_LIVE_API_TIMEOUT", "180"))


@unittest.skipUnless(LIVE_TEST_ENABLED, "set HUXLEY_LIVE_API_TEST=1 to run against a live daemon")
class LiveOpenAIAPITests(unittest.TestCase):
    def _get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"{LIVE_API_BASE}{path}", timeout=LIVE_API_TIMEOUT) as resp:
            return json.loads(resp.read())

    def _post_json(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            f"{LIVE_API_BASE}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=LIVE_API_TIMEOUT) as resp:
            return json.loads(resp.read())

    def _post_raw(self, path: str, body: dict) -> str:
        req = urllib.request.Request(
            f"{LIVE_API_BASE}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=LIVE_API_TIMEOUT) as resp:
            return resp.read().decode()

    def test_live_models_present_and_inference_timed(self):
        models_payload = self._get_json("/v1/models")
        model_ids = {item["id"] for item in models_payload.get("data", [])}
        self.assertIn("alpha", model_ids)
        self.assertIn("beta", model_ids)

        timings = {}
        prompts = {
            "beta": "Reply with one short line saying beta live ok.",
            "alpha": "Reply with one short line saying alpha live ok.",
        }
        for model in ("beta", "alpha"):
            started = time.perf_counter()
            payload = self._post_json(
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompts[model]}],
                    "max_tokens": 32,
                    "temperature": 0.0,
                },
            )
            elapsed = time.perf_counter() - started
            timings[model] = elapsed
            self.assertEqual(payload["model"], model)
            content = payload["choices"][0]["message"]["content"]
            self.assertIsInstance(content, str)
            self.assertTrue(content.strip())

        print(
            f"live-openai-timings alpha={timings['alpha']:.3f}s beta={timings['beta']:.3f}s base={LIVE_API_BASE}",
            file=sys.stderr,
            flush=True,
        )

    def test_live_streaming_chat_completions(self):
        timings = {}
        for model in ("beta", "alpha"):
            started = time.perf_counter()
            payload = self._post_raw(
                "/v1/chat/completions",
                {
                    "model": model,
                    "messages": [{"role": "user", "content": f"Reply with one short line saying {model} stream ok."}],
                    "max_tokens": 32,
                    "temperature": 0.0,
                    "stream": True,
                },
            )
            elapsed = time.perf_counter() - started
            timings[model] = elapsed
            self.assertIn("data: ", payload)
            self.assertIn("data: [DONE]", payload)

        print(
            f"live-openai-stream-timings alpha={timings['alpha']:.3f}s beta={timings['beta']:.3f}s base={LIVE_API_BASE}",
            file=sys.stderr,
            flush=True,
        )


if __name__ == "__main__":
    unittest.main()

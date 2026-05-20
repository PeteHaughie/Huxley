from __future__ import annotations
import httpx
import json
from typing import Optional, Iterator


class OpenAICompatibleClient:
    def __init__(self, endpoint: str, model: str, api_key: str = "unused", timeout: float = 30.0):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        stream: bool = False,
        request_options: Optional[dict] = None,
    ) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        body.update(self._normalized_request_options(request_options))

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.endpoint}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    def health(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.endpoint}/models")
                return resp.status_code == 200
        except Exception:
            return False

    def stream_chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        request_options: Optional[dict] = None,
    ) -> Iterator[dict | str]:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        body.update(self._normalized_request_options(request_options))

        with httpx.Client(timeout=self.timeout) as client:
            with client.stream(
                "POST",
                f"{self.endpoint}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        payload = line[6:]
                    else:
                        continue
                    if payload == "[DONE]":
                        yield payload
                        break
                    yield json.loads(payload)

    def _normalized_request_options(self, request_options: Optional[dict]) -> dict:
        if not request_options:
            return {}
        return {
            key: request_options[key]
            for key in ("tools", "tool_choice", "functions", "function_call", "response_format")
            if key in request_options
        }

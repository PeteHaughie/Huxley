from __future__ import annotations
import httpx
from typing import Optional, AsyncGenerator, Any


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
    ) -> dict:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": stream,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

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

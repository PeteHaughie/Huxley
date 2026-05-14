from __future__ import annotations
from harness.server.inference import OpenAICompatibleClient
from harness.comms import Message, Caste, Action, ContextHint
from harness.config import load_config


class CloudEndpoint:
    def __init__(self):
        self.cfg = load_config().get("cloud", {})
        self._client = None

    def _get_client(self) -> OpenAICompatibleClient | None:
        if not self.cfg.get("enabled"):
            return None
        if self._client is None:
            self._client = OpenAICompatibleClient(
                endpoint=self.cfg["endpoint"],
                model=self.cfg.get("model", "default"),
                api_key=self.cfg.get("api_key", ""),
                timeout=60.0,
            )
        return self._client

    def infer(self, msg: Message) -> Message | None:
        client = self._get_client()
        if client is None:
            return None

        prompt = _fmt_cloud_prompt(msg)
        try:
            resp = client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=msg.token_budget.get("output", 2048),
                temperature=0.1,
            )
            content = resp["choices"][0]["message"]["content"]
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"result": content, "source": "cloud", "raw": resp},
                session=msg.session,
            )
        except Exception as e:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": f"cloud: {e}", "source": "cloud"},
                session=msg.session,
            )

    def health(self) -> bool:
        client = self._get_client()
        if client is None:
            return False
        return client.health()


def _fmt_cloud_prompt(msg: Message) -> str:
    p = msg.payload
    if isinstance(p, dict):
        return p.get("prompt", str(p))
    return str(p)

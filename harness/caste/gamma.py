from __future__ import annotations
from harness.caste._base import CasteBase
from harness.comms.message import Message, Caste, Action, ContextHint
from harness.server.inference import OpenAICompatibleClient


class Gamma(CasteBase):
    caste = Caste.GAMMA

    def __init__(self, endpoint: str = "http://localhost:11434/v1", model: str = "apple-foundationmodel"):
        self.client = OpenAICompatibleClient(endpoint=endpoint, model=model, timeout=15.0)

    def infer(self, msg: Message) -> Message:
        prompt = _fmt_gamma_prompt(msg)
        try:
            resp = self.client.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=min(msg.token_budget.get("output", 512), 4096),
                temperature=0.0,
            )
            content = resp["choices"][0]["message"]["content"]
            return Message(
                caste=Caste.GAMMA,
                action=Action.INFER,
                payload={"result": content, "raw": resp},
                session=msg.session,
                context_hint=ContextHint.CAVEMAN,
            )
        except Exception as e:
            return Message(
                caste=Caste.GAMMA,
                action=Action.INFER,
                payload={"error": str(e)},
                session=msg.session,
                context_hint=ContextHint.CAVEMAN,
            )

    def health(self) -> bool:
        return self.client.health()


def _fmt_gamma_prompt(msg: Message) -> str:
    p = msg.payload
    if isinstance(p, dict) and "prompt" in p:
        return p["prompt"]
    return str(p)

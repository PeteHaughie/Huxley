from __future__ import annotations
from harness.caste._base import CasteBase
from harness.comms.message import Message, Caste, Action, ContextHint
from harness.server.inference import OpenAICompatibleClient


class Gamma(CasteBase):
    caste = Caste.GAMMA
    supports_tools = False

    def __init__(self, cfg: dict | None = None, tool_service=None):
        from harness.config import load_config

        super().__init__(tool_service=tool_service)
        _cfg = cfg or load_config().get("gamma", {})
        endpoint = _cfg.get("endpoint", "http://127.0.0.1:11434/v1")
        model = _cfg.get("model", "apple-foundationmodel")
        timeout = _cfg.get("timeout", 15.0)
        self.client = OpenAICompatibleClient(
            endpoint=endpoint, model=model, timeout=timeout
        )

    def _ensure_apfel(self) -> str | None:
        from harness.caste.apfeld import ensure_apfel

        if not ensure_apfel():
            return "apfel failed to start"
        return None

    def infer(self, msg: Message) -> Message:
        err = self._ensure_apfel()
        if err:
            return Message(
                caste=Caste.GAMMA,
                action=Action.INFER,
                payload={"error": err},
                session=msg.session,
                context_hint=ContextHint.CAVEMAN,
            )

        if self._msg_requests_tools(msg):
            return self._infer_with_tools(msg)

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

    def _infer_with_tools(self, msg: Message) -> Message:
        from harness.tool.engine import ToolService

        prompt = _fmt_gamma_prompt(msg)
        try:
            ts = self._tool_service or ToolService()
            ts.registry.scan_skills()
            tools = ts.registry.definitions()
            messages = [{"role": "user", "content": prompt}]
            resp = ts.run_loop(
                model_fn=lambda messages, **kw: self.client.chat(
                    messages=messages,
                    max_tokens=min(msg.token_budget.get("output", 512), 4096),
                    temperature=0.0,
                    request_options=kw if kw else None,
                ),
                messages=messages,
                tools=tools,
            )
            msg_content = resp["choices"][0]["message"]
            content = msg_content.get("content", "")
            return Message(
                caste=Caste.GAMMA,
                action=Action.INFER,
                payload={"result": content or "(tool result)", "raw": resp},
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

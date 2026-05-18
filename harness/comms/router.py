from __future__ import annotations
import time
from harness.comms.message import Message, Caste, Action
from harness.config import load_config


class Router:
    def __init__(self):
        from harness.caste.gamma import Gamma
        from harness.caste.beta import Beta
        from harness.caste.alpha import Alpha
        self._gamma = Gamma()
        self._beta = Beta()
        self._alpha = Alpha()
        self._routes: dict[Caste, object] = {
            Caste.GAMMA: self._gamma,
            Caste.BETA: self._beta,
            Caste.ALPHA: self._alpha,
        }

    def dispatch(self, msg: Message) -> Message:
        handler = self._routes.get(msg.caste)
        if handler is None:
            return Message(
                caste=Caste.ALPHA,
                action=Action.ROUTE,
                payload={"error": f"unknown caste: {msg.caste}"},
                session=msg.session,
            )
        return handler.infer(msg)

    def health(self, caste: Caste) -> bool:
        handler = self._routes.get(caste)
        if handler is None:
            return False
        return handler.health()

    def openai_models(self) -> list[dict]:
        cfg = load_config().get("api", {})
        models = [
            cfg.get("alpha_model_id", "alpha"),
            cfg.get("beta_model_id", "beta"),
        ]
        return [
            {
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": "huxley",
                "permission": [],
            }
            for model_id in models
        ]

    def openai_chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
    ) -> dict:
        canonical_model, handler = self._resolve_openai_model(model)
        max_output = max_tokens if max_tokens is not None else 512
        created = int(time.time())
        if handler is self._alpha:
            response = self._alpha.complete_chat(messages, max_output, temperature=temperature)
            if isinstance(response, dict):
                response["model"] = canonical_model
                response.setdefault("object", "chat.completion")
                response.setdefault("created", created)
                response.setdefault("id", f"chatcmpl-{created}")
                return response
        else:
            content = self._beta.complete_chat(messages, max_output, temperature=temperature)
            response = {
                "id": f"chatcmpl-{created}",
                "object": "chat.completion",
                "created": created,
                "model": canonical_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
            return response
        raise RuntimeError("invalid response from model backend")

    def _resolve_openai_model(self, model: str) -> tuple[str, object]:
        cfg = load_config().get("api", {})
        alpha_model_id = str(cfg.get("alpha_model_id", "alpha"))
        beta_model_id = str(cfg.get("beta_model_id", "beta"))
        alias_map = {
            alpha_model_id.lower(): (alpha_model_id, self._alpha),
            "alpha": (alpha_model_id, self._alpha),
            "gemma-4-e4b": (alpha_model_id, self._alpha),
            beta_model_id.lower(): (beta_model_id, self._beta),
            "beta": (beta_model_id, self._beta),
            "ternary-bonsai-8b": (beta_model_id, self._beta),
        }
        resolved = alias_map.get(str(model).strip().lower())
        if resolved is None:
            raise ValueError(f"unknown model: {model}")
        return resolved

from __future__ import annotations
from harness.caste._base import CasteBase
from harness.comms.message import Message, Caste, Action, ContextHint
from harness.config import load_config


class Beta(CasteBase):
    caste = Caste.BETA

    def __init__(self, cfg: dict | None = None):
        _cfg = cfg or load_config().get("beta", {})
        self.primary_engine = _cfg.get("engine", "mlx")
        self.primary_model = _cfg.get("model", "prism-ml/Ternary-Bonsai-8B")
        self.fallback_engine = _cfg.get("fallback_engine", "llama.cpp")
        self.fallback_model = _cfg.get("fallback_model", "")
        self.ctx_size = _cfg.get("ctx_size", 8192)
        self._model = None
        self._tokenizer = None

    def _load_mlx(self) -> str | None:
        import mlx_lm
        self._model, self._tokenizer = mlx_lm.load(self.primary_model)
        return None

    def _load_llamacpp(self, model_path: str) -> str | None:
        from llama_cpp import Llama
        self._model = Llama(
            model_path=model_path,
            n_ctx=self.ctx_size,
            n_gpu_layers=-1,
            verbose=False,
        )
        return None

    def _load(self):
        if self._model is not None:
            return
        errs = []
        if self.primary_engine == "mlx":
            try:
                return self._load_mlx()
            except Exception as e:
                errs.append(f"mlx({self.primary_model}): {e}")
        elif self.primary_engine == "llama.cpp":
            try:
                return self._load_llamacpp(self.primary_model)
            except Exception as e:
                errs.append(f"llamacpp({self.primary_model}): {e}")
        if self.fallback_model:
            try:
                return self._load_llamacpp(self.fallback_model)
            except Exception as e:
                errs.append(f"fallback({self.fallback_model}): {e}")
        raise RuntimeError(" | ".join(errs))

    def infer(self, msg: Message) -> Message:
        try:
            self._load()
        except ImportError as e:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": f"missing dep: {e}"},
                session=msg.session,
            )
        except Exception as e:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": f"model load failed: {e}"},
                session=msg.session,
            )
        prompt = _fmt_beta_prompt(msg)
        system = _beta_system_prompt(msg.context_hint)
        messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        max_tok = msg.token_budget.get("output", 128)
        try:
            if hasattr(self._tokenizer, "apply_chat_template"):
                import mlx_lm
                formatted = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                response = mlx_lm.generate(
                    self._model, self._tokenizer,
                    prompt=formatted, max_tokens=max_tok,
                    temp=0.1, verbose=False,
                )
            else:
                response = self._model.create_chat_completion(
                    messages=messages, max_tokens=max_tok,
                    temperature=0.1, stop=None,
                )
                response = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"result": response.strip()},
                session=msg.session,
            )
        except Exception as e:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": str(e)},
                session=msg.session,
            )

    def health(self) -> bool:
        try:
            self._load()
            return True
        except Exception:
            return False


def _beta_system_prompt(hint: str = "caveman") -> str:
    if hint == "caveman":
        return "You are a terse AI assistant. Respond in 1-2 sentences. No explanation, no rambling, no thinking out loud."
    return "You are a helpful AI assistant. Be concise."


def _fmt_beta_prompt(msg: Message) -> str:
    p = msg.payload
    if isinstance(p, dict):
        return p.get("prompt", str(p))
    return str(p)

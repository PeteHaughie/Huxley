from __future__ import annotations
from harness.caste._base import CasteBase
from harness.comms import Message, Caste, Action, ContextHint


class Beta(CasteBase):
    caste = Caste.BETA

    def __init__(self, model: str = "prism-ml/Ternary-Bonsai-8B", ctx_size: int = 8192):
        self.model_name = model
        self.ctx_size = ctx_size
        self._model = None
        self._tokenizer = None

    def _load(self):
        if self._model is not None:
            return
        import mlx_lm
        self._model, self._tokenizer = mlx_lm.load(self.model_name)

    def infer(self, msg: Message) -> Message:
        try:
            self._load()
        except ImportError:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": "mlx_lm not installed. pip install mlx-lm"},
                session=msg.session,
            )
        except Exception as e:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": f"model load failed: {e}"},
                session=msg.session,
            )

        import mlx_lm
        prompt = _fmt_beta_prompt(msg)
        try:
            response = mlx_lm.generate(
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=msg.token_budget.get("output", 512),
                temp=0.1,
                verbose=False,
            )
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"result": response},
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


def _fmt_beta_prompt(msg: Message) -> str:
    p = msg.payload
    if isinstance(p, dict):
        return p.get("prompt", str(p))
    return str(p)

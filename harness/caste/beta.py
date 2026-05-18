from __future__ import annotations
import gc
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

    def _load_mlx(self, model_name: str) -> str | None:
        import mlx_lm
        self._model, self._tokenizer = mlx_lm.load(model_name)
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
                return self._load_mlx(self.primary_model)
            except Exception as e:
                errs.append(f"mlx({self.primary_model}): {e}")
        elif self.primary_engine == "llama.cpp":
            try:
                return self._load_llamacpp(self.primary_model)
            except Exception as e:
                errs.append(f"llamacpp({self.primary_model}): {e}")
        if self.fallback_model:
            try:
                if self.fallback_engine == "mlx":
                    return self._load_mlx(self.fallback_model)
                else:
                    return self._load_llamacpp(self.fallback_model)
            except Exception as e:
                errs.append(f"fallback({self.fallback_model}): {e}")
        raise RuntimeError(" | ".join(errs))

    def _reset_model(self):
        self._model = None
        self._tokenizer = None
        gc.collect()

    def _recovery_ctx_size(self) -> int:
        if self.ctx_size > 24576:
            return 24576
        return max(8192, self.ctx_size // 2)

    def _run_generation(self, messages: list[dict], max_tok: int, temperature: float = 0.1) -> str:
        if hasattr(self._tokenizer, "apply_chat_template"):
            import mlx_lm
            formatted = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            return mlx_lm.generate(
                self._model, self._tokenizer,
                prompt=formatted, max_tokens=max_tok,
                temp=temperature, verbose=False,
            )
        response = self._model.create_chat_completion(
            messages=messages, max_tokens=max_tok,
            temperature=temperature, stop=None,
        )
        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    def _recover_and_retry(self, messages: list[dict], max_tok: int, error: Exception, temperature: float = 0.1) -> str:
        if "llama_decode returned -3" not in str(error):
            raise error
        retry_ctx = self._recovery_ctx_size()
        if retry_ctx == self.ctx_size:
            raise error
        old_ctx = self.ctx_size
        self._reset_model()
        self.ctx_size = retry_ctx
        print(f"γ|beta|recover|ctx {old_ctx}->{retry_ctx}|decode -3", flush=True)
        self._load()
        return self._run_generation(messages, max_tok, temperature=temperature)

    def complete_chat(self, messages: list[dict], max_tokens: int, temperature: float = 0.1) -> str:
        try:
            self._load()
        except ImportError as e:
            raise RuntimeError(f"missing dep: {e}") from e
        except Exception as e:
            raise RuntimeError(f"model load failed: {e}") from e
        try:
            return self._run_generation(messages, max_tokens, temperature=temperature)
        except Exception as e:
            return self._recover_and_retry(messages, max_tokens, e, temperature=temperature)

    def infer(self, msg: Message) -> Message:
        prompt = _fmt_beta_prompt(msg)
        system = _beta_system_prompt(msg.context_hint)
        history = []
        if msg.session:
            from harness.memory.persistence import SessionJournal
            journal = SessionJournal(msg.session, "beta")
            if journal.needs_compaction():
                self._compact_journal(journal, msg)
            history = journal.read(max_tokens=msg.token_budget.get("input", 4096))
        messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": prompt}]
        max_tok = msg.token_budget.get("output", 128)
        try:
            response = self.complete_chat(messages, max_tok, temperature=0.1)
        except Exception as e:
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"error": str(e)},
                session=msg.session,
            )
        try:
            if msg.session:
                journal.append("user", prompt)
                journal.append("assistant", response.strip())
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

    def _compact_journal(self, journal, msg):
        text = journal.build_compactable_text()
        if text is None:
            return
        cprompt = f"Condense this conversation into one paragraph preserving key facts, decisions, results, and current state. Drop greetings, pleasantries, and step-by-step reasoning:\n\n{text}"
        try:
            self._load()
            system = "You are a precise summarizer. Output only the summary paragraph, no preamble."
            cmessages = [{"role": "system", "content": system}, {"role": "user", "content": cprompt}]
            max_tok = msg.token_budget.get("output", 256)
            if hasattr(self._tokenizer, "apply_chat_template"):
                import mlx_lm
                formatted = self._tokenizer.apply_chat_template(cmessages, tokenize=False, add_generation_prompt=True)
                response = mlx_lm.generate(self._model, self._tokenizer, prompt=formatted, max_tokens=max_tok, temp=0.1, verbose=False)
            else:
                resp = self._model.create_chat_completion(messages=cmessages, max_tokens=max_tok, temperature=0.1, stop=None)
                response = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            summary = response.strip()
            if summary:
                journal.compact(summary)
                print(f"γ|beta|compact|ok|{journal.entry_count()} entries", flush=True)
        except Exception as e:
            print(f"γ|beta|compact|err|{e}", flush=True)

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

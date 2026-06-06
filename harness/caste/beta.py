from __future__ import annotations
import gc
import json
import re
from typing import Iterator, TYPE_CHECKING
from harness.caste._base import CasteBase
from harness.comms.message import Message, Caste, Action
from harness.config import load_config

if TYPE_CHECKING:
    from llama_cpp import Llama


class Beta(CasteBase):
    caste = Caste.BETA
    supports_tools = True

    def __init__(self, cfg: dict | None = None, tool_service=None):
        super().__init__(tool_service=tool_service)
        _cfg = cfg or load_config().get("beta", {})
        self.model_path = _cfg.get("model", "~/.huxley/models/Bonsai-8B.gguf")
        self.ctx_size = _cfg.get("ctx_size", 65536)
        self._model: Llama | None = None

    def _load_llamacpp(self, model_path: str) -> None:
        from llama_cpp import Llama

        self._model = Llama(
            model_path=model_path,
            n_ctx=self.ctx_size,
            n_gpu_layers=-1,
            verbose=False,
        )

    def _load(self):
        if self._model is not None:
            return
        self._load_llamacpp(self.model_path)

    def _reset_model(self):
        self._model = None
        gc.collect()

    def _recovery_ctx_size(self) -> int:
        if self.ctx_size > 24576:
            return 24576
        return max(8192, self.ctx_size // 2)

    def _run_generation(
        self, messages: list[dict], max_tok: int, temperature: float = 0.1
    ) -> str:
        response = self._model.create_chat_completion(
            messages=messages,
            max_tokens=max_tok,
            temperature=temperature,
            stop=None,
        )
        return response.get("choices", [{}])[0].get("message", {}).get("content", "")

    def _recover_and_retry(
        self,
        messages: list[dict],
        max_tok: int,
        error: Exception,
        temperature: float = 0.1,
    ) -> str:
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

    def complete_chat(
        self, messages: list[dict], max_tokens: int, temperature: float = 0.1
    ) -> str:
        try:
            self._load()
        except Exception as e:
            raise RuntimeError(f"model load failed: {e}") from e
        try:
            return self._run_generation(messages, max_tokens, temperature=temperature)
        except Exception as e:
            return self._recover_and_retry(
                messages, max_tokens, e, temperature=temperature
            )

    def stream_chat(
        self, messages: list[dict], max_tokens: int, temperature: float = 0.1
    ) -> Iterator[dict]:
        try:
            self._load()
        except Exception as e:
            raise RuntimeError(f"model load failed: {e}") from e

        try:
            yield from self._stream_generation(
                messages, max_tokens, temperature=temperature
            )
        except Exception as e:
            yield from self._recover_and_stream(
                messages, max_tokens, e, temperature=temperature
            )

    def _stream_generation(
        self, messages: list[dict], max_tok: int, temperature: float = 0.1
    ) -> Iterator[dict]:
        stream = self._model.create_chat_completion(
            messages=messages,
            max_tokens=max_tok,
            temperature=temperature,
            stop=None,
            stream=True,
        )
        finish_reason = "stop"
        yielded = False
        for chunk in stream:
            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {}).get("content", "")
            finish = choice.get("finish_reason")
            if delta:
                yielded = True
                yield {"delta": delta, "finish_reason": None}
            if finish:
                finish_reason = finish
        if not yielded:
            yield {"delta": "", "finish_reason": finish_reason}
        else:
            yield {"delta": "", "finish_reason": finish_reason}

    def _recover_and_stream(
        self,
        messages: list[dict],
        max_tok: int,
        error: Exception,
        temperature: float = 0.1,
    ) -> Iterator[dict]:
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
        yield from self._stream_generation(messages, max_tok, temperature=temperature)

    def infer(self, msg: Message) -> Message:
        if self._msg_requests_tools(msg):
            return self._infer_with_tools(msg)

        prompt = _fmt_beta_prompt(msg)
        system = _beta_system_prompt(msg.context_hint)
        history = []
        if msg.session:
            from harness.memory.persistence import SessionJournal

            journal = SessionJournal(msg.session, "beta")
            if journal.needs_compaction():
                self._compact_journal(journal, msg)
            history = journal.read(max_tokens=msg.token_budget.get("input", 4096))
        messages = (
            [{"role": "system", "content": system}]
            + history
            + [{"role": "user", "content": prompt}]
        )
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

    def _infer_with_tools(self, msg: Message) -> Message:
        from harness.tool.engine import ToolService

        prompt = _fmt_beta_prompt(msg)
        system = _beta_system_prompt(msg.context_hint)
        try:
            self._load()
            ts = self._tool_service or ToolService()
            ts.registry.scan_skills()
            tools = ts.registry.definitions()
            history = []
            if msg.session:
                from harness.memory.persistence import SessionJournal

                journal = SessionJournal(msg.session, "beta")
                history = journal.read(max_tokens=msg.token_budget.get("input", 4096))
            messages = (
                [{"role": "system", "content": system}]
                + history
                + [{"role": "user", "content": prompt}]
            )

            def _model_fn(messages, **kw):
                try:
                    resp = self._model.create_chat_completion(
                        messages=messages,
                        max_tokens=min(msg.token_budget.get("output", 512), 4096),
                        temperature=0.1,
                        **kw,
                    )
                except Exception as e:
                    if "llama_decode returned -3" not in str(e):
                        raise
                    retry_ctx = self._recovery_ctx_size()
                    if retry_ctx == self.ctx_size:
                        raise
                    old_ctx = self.ctx_size
                    self._reset_model()
                    self.ctx_size = retry_ctx
                    print(
                        f"γ|beta|recover|ctx {old_ctx}->{retry_ctx}|decode -3",
                        flush=True,
                    )
                    self._load()
                    resp = self._model.create_chat_completion(
                        messages=messages,
                        max_tokens=min(msg.token_budget.get("output", 512), 4096),
                        temperature=0.1,
                        **kw,
                    )
                _inject_tool_calls(resp)
                return resp

            resp = ts.run_loop(model_fn=_model_fn, messages=messages, tools=tools)
            msg_content = resp["choices"][0]["message"]
            content = msg_content.get("content", "")
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"result": content or "(tool result)", "raw": resp},
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
            cmessages = [
                {"role": "system", "content": system},
                {"role": "user", "content": cprompt},
            ]
            max_tok = msg.token_budget.get("output", 256)
            resp = self._model.create_chat_completion(
                messages=cmessages, max_tokens=max_tok, temperature=0.1, stop=None
            )
            response = (
                resp.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
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


def _inject_tool_calls(resp: dict) -> None:
    msg = resp.get("choices", [{}])[0].get("message", {})
    if msg.get("tool_calls") or not msg.get("content"):
        return
    content = msg["content"]
    if "<tool_call>" not in content:
        return
    tcs, cleaned = _extract_tool_calls(content)
    if not tcs:
        return
    if cleaned:
        return
    msg["tool_calls"] = tcs
    msg["content"] = cleaned


def _extract_tool_calls(text: str) -> tuple[list[dict], str]:
    pattern = r"<tool_call>\s*(\{.*?\})\s*</tool_call>"
    matches = list(re.finditer(pattern, text, re.DOTALL))
    if not matches:
        return [], text
    tool_calls = []
    for i, m in enumerate(matches):
        try:
            parsed = json.loads(m.group(1))
            tool_calls.append(
                {
                    "id": f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": parsed.get("name", ""),
                        "arguments": json.dumps(parsed.get("arguments", {})),
                    },
                }
            )
        except (json.JSONDecodeError, TypeError):
            continue
    cleaned = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    return tool_calls, cleaned

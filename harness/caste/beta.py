from __future__ import annotations
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request
import urllib.error
from typing import Iterator, Optional
from harness.caste._base import CasteBase
from harness.comms.message import Message, Caste, Action
from harness.config import load_config

BETA_TIMEOUT = int(os.environ.get("HUXLEY_BETA_TIMEOUT", "120"))


class Beta(CasteBase):
    caste = Caste.BETA
    supports_tools = True

    def __init__(self, cfg: dict | None = None, tool_service=None):
        super().__init__(tool_service=tool_service)
        _cfg = cfg or load_config().get("beta", {})
        self.model_path = os.path.expanduser(_cfg.get("model", "~/.huxley/models/Bonsai-8B.gguf"))
        self.ctx_size = _cfg.get("ctx_size", 65536)
        self._port = int(_cfg.get("port", os.environ.get("HUXLEY_BETA_PORT", "8082")))
        self._ngl = int(_cfg.get("ngl", 99))
        self._kill_stale_listener = bool(_cfg.get("kill_stale_listener", False))
        self._proc: Optional[subprocess.Popen] = None
        self._client: Optional[object] = None
        self._server_lock = threading.Lock()

    def _endpoint(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def _wait_for_server(self, timeout: int = BETA_TIMEOUT) -> bool:
        url = f"{self._endpoint()}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc and self._proc.poll() is not None:
                err = (
                    self._proc.stderr.read().decode(errors="replace")
                    if self._proc.stderr
                    else ""
                )
                print(f"γ|beta|crashed|{err}", flush=True)
                return False
            try:
                urllib.request.urlopen(url, timeout=2)
                return True
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(2)
        return False

    def _listener_pid(self) -> Optional[int]:
        try:
            result = subprocess.run(
                ["lsof", "-nP", "-t", f"-iTCP:{self._port}", "-sTCP:LISTEN"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            pid = result.stdout.strip().splitlines()
            if pid:
                return int(pid[0])
        except Exception:
            return None
        return None

    def _foreign_listener_pid(self) -> Optional[int]:
        pid = self._listener_pid()
        if pid is None:
            return None
        if self._proc and self._proc.poll() is None and self._proc.pid == pid:
            return None
        return pid

    def _clear_stale_listener(self, pid: int):
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.2)
                except ProcessLookupError:
                    break
            print(f"γ|beta|clear_listener|pid {pid}", flush=True)
        except ProcessLookupError:
            pass
        except OSError as e:
            print(f"γ|beta|clear_listener_err|pid {pid}|{e}", flush=True)

    def _ensure_port_available(self):
        pid = self._foreign_listener_pid()
        if pid is None:
            return
        if not self._kill_stale_listener:
            raise RuntimeError(
                f"beta port {self._port} already in use by pid {pid}; "
                "set beta.kill_stale_listener=true to terminate it automatically"
            )
        self._clear_stale_listener(pid)

    def start_server(self) -> bool:
        with self._server_lock:
            if self._proc and self._proc.poll() is None:
                return True
            self._ensure_port_available()
            if self.client().health():
                return True

            cmd = [
                "llama-server",
                "-m", self.model_path,
                "--host", "127.0.0.1",
                "--port", str(self._port),
                "-ngl", str(self._ngl),
                "-c", str(self.ctx_size),
                "--alias", "beta",
            ]
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                ok = self._wait_for_server()
                if not ok:
                    ret = self._proc.poll()
                    err = ""
                    if ret is not None:
                        err = (
                            self._proc.stderr.read().decode(errors="replace")[:500]
                            if self._proc.stderr
                            else ""
                        )
                        self._proc = None
                    else:
                        self._proc.kill()
                        self._proc.wait(timeout=5)
                        self._proc = None
                        err = "process still running after timeout"
                    print(f"γ|beta|server_fail|{err[:200]}", flush=True)
                return ok
            except FileNotFoundError:
                return False

    def stop_server(self):
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
            self._client = None

    def client(self) -> object:
        if self._client is None:
            from harness.server.inference import OpenAICompatibleClient as _OCC

            self._client = _OCC(
                endpoint=f"{self._endpoint()}/v1",
                model="beta",
                timeout=120.0,
            )
        return self._client

    def _should_restart_for_error(self, err: Exception) -> bool:
        text = str(err)
        return "500 Internal Server Error" in text or "timed out" in text

    def _restart_server(self) -> bool:
        self.stop_server()
        return self.start_server()

    def _chat_with_recovery(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.1,
        request_options: dict | None = None,
    ) -> dict:
        try:
            return self.client().chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                request_options=request_options,
            )
        except Exception as e:
            if not self._should_restart_for_error(e):
                raise
            print("γ|beta|recover|restart server after upstream failure", flush=True)
            if not self._restart_server():
                raise
            return self.client().chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                request_options=request_options,
            )

    def complete_chat(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.1,
        request_options: dict | None = None,
    ) -> dict:
        if not self.start_server():
            raise RuntimeError(
                f"beta server unavailable on port {self._port} — install llama.cpp or check config"
            )
        resp = self._chat_with_recovery(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            request_options=request_options,
        )
        _inject_tool_calls(resp)
        return resp

    def stream_chat(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.1,
        request_options: dict | None = None,
    ) -> Iterator[dict]:
        if not self.start_server():
            raise RuntimeError(
                f"beta server unavailable on port {self._port} — install llama.cpp or check config"
            )
        try:
            for event in self.client().stream_chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                request_options=request_options,
            ):
                if event == "[DONE]":
                    break
                if isinstance(event, dict):
                    choice = event.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    tool_calls = delta.get("tool_calls")
                    finish = choice.get("finish_reason")
                    if content or tool_calls:
                        yield {"delta": content, "tool_calls": tool_calls, "finish_reason": None}
                    if finish:
                        yield {"delta": "", "tool_calls": None, "finish_reason": finish}
        except Exception as e:
            if not self._should_restart_for_error(e):
                raise
            print(
                "γ|beta|recover|restart server after upstream streaming failure",
                flush=True,
            )
            if not self._restart_server():
                raise
            for event in self.client().stream_chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                request_options=request_options,
            ):
                if event == "[DONE]":
                    break
                if isinstance(event, dict):
                    choice = event.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    tool_calls = delta.get("tool_calls")
                    finish = choice.get("finish_reason")
                    if content or tool_calls:
                        yield {"delta": content, "tool_calls": tool_calls, "finish_reason": None}
                    if finish:
                        yield {"delta": "", "tool_calls": None, "finish_reason": finish}

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
            resp = self.complete_chat(messages, max_tok, temperature=0.1)
            content = resp.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
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
                journal.append("assistant", content)
            return Message(
                caste=Caste.BETA,
                action=Action.INFER,
                payload={"result": content, "raw": resp},
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
            if not self.start_server():
                raise RuntimeError(
                    f"beta server unavailable on port {self._port} — install llama.cpp or check config"
                )
            ts = self._tool_service or ToolService()
            skill_name = msg.payload.get("skill_name") if isinstance(msg.payload, dict) else None
            ts.registry.scan_skills(skill_name=skill_name)
            tools = ts.registry.definitions(skill_name=skill_name)
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
                    resp = self.client().chat(
                        messages=messages,
                        max_tokens=min(msg.token_budget.get("output", 512), 4096),
                        temperature=0.1,
                        request_options=kw,
                    )
                except Exception as e:
                    if self._should_restart_for_error(e):
                        print("γ|beta|recover|restart during tool loop", flush=True)
                        self._restart_server()
                        resp = self.client().chat(
                            messages=messages,
                            max_tokens=min(msg.token_budget.get("output", 512), 4096),
                            temperature=0.1,
                            request_options=kw,
                        )
                    else:
                        raise
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
            self.start_server()
            system = "You are a precise summarizer. Output only the summary paragraph, no preamble."
            cmessages = [
                {"role": "system", "content": system},
                {"role": "user", "content": cprompt},
            ]
            max_tok = msg.token_budget.get("output", 256)
            resp = self.client().chat(
                messages=cmessages, max_tokens=max_tok, temperature=0.1,
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
            return self.client().health()
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
    msg["tool_calls"] = tcs
    msg["content"] = cleaned or None


def _extract_tool_calls(text: str) -> tuple[list[dict], str]:
    pattern = r"<tool_call>\s*(.*?)\s*</tool_call>"
    matches = list(re.finditer(pattern, text, re.DOTALL))
    if not matches:
        return [], text
    tool_calls = []
    for m in matches:
        try:
            parsed = json.loads(m.group(1))
            args = parsed.get("arguments", {})
            tool_calls.append(
                {
                    "type": "function",
                    "function": {
                        "name": parsed.get("name", ""),
                        "arguments": args if isinstance(args, str) else json.dumps(args),
                    },
                }
            )
        except (json.JSONDecodeError, TypeError):
            continue
    cleaned = re.sub(pattern, "", text, flags=re.DOTALL).strip()
    return tool_calls, cleaned

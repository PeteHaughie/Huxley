from __future__ import annotations
import subprocess
import time
import signal
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Iterator

from harness.caste._base import CasteBase
from harness.config import load_config
from harness.comms.message import Message, Caste, Action, ContextHint

if TYPE_CHECKING:
    from harness.server.inference import OpenAICompatibleClient

ALPHA_PORT = int(os.environ.get("HUXLEY_ALPHA_PORT", "8081"))
ALPHA_TIMEOUT = int(os.environ.get("HUXLEY_ALPHA_TIMEOUT", "120"))


class Alpha(CasteBase):
    caste = Caste.ALPHA

    def __init__(self, ctx_size: int = 32768):
        self.cfg = load_config()
        acfg = self.cfg["alpha"]
        self.ctx_size = ctx_size
        self._proc: Optional[subprocess.Popen] = None
        self._client: Optional[OpenAICompatibleClient] = None

    def _endpoint(self) -> str:
        return f"http://127.0.0.1:{ALPHA_PORT}"

    def _wait_for_server(self, timeout: int = ALPHA_TIMEOUT) -> bool:
        url = f"{self._endpoint()}/health"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc and self._proc.poll() is not None:
                err = self._proc.stderr.read().decode(errors="replace") if self._proc.stderr else ""
                print(f"γ|alpha|crashed|{err}", flush=True)
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
                ["lsof", "-nP", "-t", f"-iTCP:{ALPHA_PORT}", "-sTCP:LISTEN"],
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

    def _clear_stale_listener(self):
        pid = self._listener_pid()
        if pid is None:
            return
        if self._proc and self._proc.poll() is None and self._proc.pid == pid:
            return
        try:
            os.kill(pid, signal.SIGTERM)
            deadline = time.time() + 5
            while time.time() < deadline:
                try:
                    os.kill(pid, 0)
                    time.sleep(0.2)
                except ProcessLookupError:
                    break
            print(f"γ|alpha|clear_listener|pid {pid}", flush=True)
        except ProcessLookupError:
            pass
        except OSError as e:
            print(f"γ|alpha|clear_listener_err|pid {pid}|{e}", flush=True)

    def start_server(self) -> bool:
        acfg = self.cfg["alpha"]
        if self._proc and self._proc.poll() is None:
            return True
        if self.client().health():
            return True
        self._clear_stale_listener()

        cmd = [
            "llama-server",
            "-m", acfg["model"],
            "--host", "127.0.0.1",
            "--port", str(ALPHA_PORT),
            "-ngl", str(acfg["ngl"]),
            "-c", str(acfg["ctx_size"]),
            "--cache-type-k", acfg["cache_type_k"],
            "--cache-type-v", acfg["cache_type_v"],
        ]
        if acfg.get("mtp") and acfg.get("draft_model"):
            cmd.extend(["-md", acfg["draft_model"]])
            cmd.extend(["--spec-draft-n-max", str(acfg.get("draft_max", 8))])

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
                    err = self._proc.stderr.read().decode(errors="replace")[:500] if self._proc.stderr else ""
                    self._proc = None
                else:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
                    self._proc = None
                    err = "process still running after timeout"
                print(f"γ|alpha|server_fail|{err[:200]}", flush=True)
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

    def client(self) -> OpenAICompatibleClient:
        if self._client is None:
            from harness.server.inference import OpenAICompatibleClient as _OCC
            self._client = _OCC(
                endpoint=f"{self._endpoint()}/v1",
                model="gemma-4-e4b",
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
            print("γ|alpha|recover|restart server after upstream failure", flush=True)
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
            raise RuntimeError(f"alpha server unavailable on port {ALPHA_PORT} — install llama.cpp or check config")
        return self._chat_with_recovery(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            request_options=request_options,
        )

    def stream_chat(
        self,
        messages: list[dict],
        max_tokens: int,
        temperature: float = 0.1,
        request_options: dict | None = None,
    ) -> Iterator[dict]:
        if not self.start_server():
            raise RuntimeError(f"alpha server unavailable on port {ALPHA_PORT} — install llama.cpp or check config")
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
                    yield event
        except Exception as e:
            if not self._should_restart_for_error(e):
                raise
            print("γ|alpha|recover|restart server after upstream streaming failure", flush=True)
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
                    yield event

    def infer(self, msg: Message) -> Message:
        try:
            from harness.memory.persistence import SessionJournal
            user_content = _fmt_alpha_prompt(msg)
            history = []
            if msg.session:
                journal = SessionJournal(msg.session, "alpha")
                if journal.needs_compaction():
                    self._compact_journal(journal, msg)
                history = journal.read(max_tokens=msg.token_budget.get("input", 4096))
            messages = history + [{"role": "user", "content": user_content}]
            resp = self.complete_chat(
                messages=messages,
                max_tokens=msg.token_budget.get("output", 2048),
                temperature=0.1,
            )
            msg_content = resp["choices"][0]["message"]
            content = msg_content.get("content", "") or msg_content.get("reasoning_content", "")
            if msg.session:
                journal.append("user", user_content)
                journal.append("assistant", content)
            return Message(
                caste=Caste.ALPHA,
                action=Action.INFER,
                payload={"result": content, "raw": resp},
                session=msg.session,
            )
        except Exception as e:
            return Message(
                caste=Caste.ALPHA,
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
            resp = self._chat_with_recovery(
                messages=[{"role": "system", "content": "You are a precise summarizer. Output only the summary paragraph, no preamble."}, {"role": "user", "content": cprompt}],
                max_tokens=msg.token_budget.get("output", 256),
                temperature=0.1,
            )
            summary = resp["choices"][0]["message"]["content"].strip()
            if summary:
                journal.compact(summary)
                print(f"γ|alpha|compact|ok|{journal.entry_count()} entries", flush=True)
        except Exception as e:
            print(f"γ|alpha|compact|err|{e}", flush=True)

    def health(self) -> bool:
        try:
            url = f"{self._endpoint()}/health"
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            return False


def _fmt_alpha_prompt(msg: Message) -> str:
    p = msg.payload
    if isinstance(p, dict):
        return p.get("prompt", str(p))
    return str(p)

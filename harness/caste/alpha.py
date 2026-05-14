from __future__ import annotations
import subprocess
import time
import signal
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from harness.caste._base import CasteBase
from harness.config import load_config
from harness.comms.message import Message, Caste, Action, ContextHint

if TYPE_CHECKING:
    from harness.server.inference import OpenAICompatibleClient

ALPHA_PORT = int(os.environ.get("MONSTER_ALPHA_PORT", "8081"))
ALPHA_TIMEOUT = int(os.environ.get("MONSTER_ALPHA_TIMEOUT", "120"))


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
            try:
                urllib.request.urlopen(url, timeout=2)
                return True
            except (urllib.error.URLError, ConnectionError, OSError):
                time.sleep(2)
        return False

    def start_server(self) -> bool:
        acfg = self.cfg["alpha"]
        if self._proc and self._proc.poll() is None:
            return True

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
            cmd.extend(["--draft-block-size", str(acfg.get("draft_block_size", 3))])
            cmd.extend(["--draft-max", str(acfg.get("draft_max", 8))])

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return self._wait_for_server()
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

    def infer(self, msg: Message) -> Message:
        if not self.start_server():
            return Message(
                caste=Caste.ALPHA,
                action=Action.INFER,
                payload={"error": "alpha server unavailable — install llama.cpp for llama-server"},
                session=msg.session,
            )
        try:
            resp = self.client().chat(
                messages=[{"role": "user", "content": _fmt_alpha_prompt(msg)}],
                max_tokens=msg.token_budget.get("output", 2048),
                temperature=0.1,
            )
            content = resp["choices"][0]["message"]["content"]
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

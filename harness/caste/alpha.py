from __future__ import annotations
import subprocess
import time
import signal
import os
import re
from pathlib import Path
from typing import Optional

from harness.caste._base import CasteBase
from harness.comms import Message, Caste, Action, ContextHint
from harness.server.inference import OpenAICompatibleClient
from harness.config import load_config

ALPHA_PORT = int(os.environ.get("MONSTER_ALPHA_PORT", "8081"))


class Alpha(CasteBase):
    caste = Caste.ALPHA

    def __init__(self, ctx_size: int = 32768):
        self.cfg = load_config()
        acfg = self.cfg["alpha"]
        self.ctx_size = ctx_size
        self._proc: Optional[subprocess.Popen] = None
        self._client: Optional[OpenAICompatibleClient] = None

    def start_server(self) -> Optional[str]:
        acfg = self.cfg["alpha"]
        if self._proc and self._proc.poll() is None:
            return f"http://127.0.0.1:{ALPHA_PORT}"

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
            time.sleep(2)
            if self._proc.poll() is not None:
                return None
            return f"http://127.0.0.1:{ALPHA_PORT}"
        except FileNotFoundError:
            return None

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
            self._client = OpenAICompatibleClient(
                endpoint=f"http://127.0.0.1:{ALPHA_PORT}/v1",
                model="gemma-4-e4b",
                timeout=60.0,
            )
        return self._client

    def infer(self, msg: Message) -> Message:
        endpoint = self.start_server()
        if not endpoint:
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
            if self._client:
                return self._client.health()
            return False
        except Exception:
            return False


def _fmt_alpha_prompt(msg: Message) -> str:
    p = msg.payload
    if isinstance(p, dict):
        return p.get("prompt", str(p))
    return str(p)

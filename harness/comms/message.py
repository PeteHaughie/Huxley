from __future__ import annotations
import uuid
import json
from enum import Enum
from datetime import datetime, timezone
from typing import Any, Optional


class Caste(str, Enum):
    ALPHA = "\u03b1"
    BETA = "\u03b2"
    GAMMA = "\u03b3"


class Action(str, Enum):
    INFER = "infer"
    ROUTE = "route"
    STORE = "store"
    RECALL = "recall"
    FORK = "fork"
    SKILL_LOAD = "skill_load"


class ContextHint(str, Enum):
    CAVEMAN = "caveman"
    NORMAL = "normal"
    FULL = "full"


class Message:
    __slots__ = (
        "caste", "msg_id", "session",
        "action", "payload", "token_budget",
        "context_hint", "timestamp",
    )

    def __init__(
        self,
        caste: Caste,
        action: Action,
        payload: Any = None,
        session: Optional[str] = None,
        token_budget: Optional[dict] = None,
        context_hint: ContextHint = ContextHint.CAVEMAN,
    ):
        self.caste = caste
        self.msg_id = str(uuid.uuid4())
        self.session = session or ""
        self.action = action
        self.payload = payload or {}
        self.token_budget = token_budget or {"input": 4096, "output": 512}
        self.context_hint = context_hint
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "caste": self.caste.value,
            "msg_id": self.msg_id,
            "session": self.session,
            "action": self.action.value,
            "payload": self.payload,
            "token_budget": self.token_budget,
            "context_hint": self.context_hint.value,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        m = cls(
            caste=Caste(data["caste"]),
            action=Action(data["action"]),
            payload=data.get("payload"),
            session=data.get("session"),
            token_budget=data.get("token_budget"),
            context_hint=ContextHint(data.get("context_hint", "caveman")),
        )
        m.msg_id = data.get("msg_id", m.msg_id)
        m.timestamp = data.get("timestamp", m.timestamp)
        return m

    @classmethod
    def from_json(cls, raw: str) -> Message:
        return cls.from_dict(json.loads(raw))

    def __repr__(self):
        return f"<{self.caste.value}|{self.action.value}|{self.msg_id[:8]}>"

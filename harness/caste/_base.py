from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from harness.comms import Message, Caste
    from harness.tool.engine import ToolService


class CasteBase(ABC):
    caste: Caste
    supports_tools: bool = False

    def __init__(self, tool_service: Optional[ToolService] = None):
        self._tool_service = tool_service

    @property
    def tool_service(self) -> Optional[ToolService]:
        return self._tool_service

    @tool_service.setter
    def tool_service(self, ts: Optional[ToolService]):
        self._tool_service = ts

    @abstractmethod
    def infer(self, msg: Message) -> Message: ...

    @abstractmethod
    def health(self) -> bool: ...

    def _msg_requests_tools(self, msg: Message) -> bool:
        payload = msg.payload
        if not isinstance(payload, dict):
            return False
        return payload.get("tools", False) is not False

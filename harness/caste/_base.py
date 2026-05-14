from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from harness.comms import Message, Caste


class CasteBase(ABC):
    caste: Caste

    @abstractmethod
    def infer(self, msg: Message) -> Message:
        ...

    @abstractmethod
    def health(self) -> bool:
        ...

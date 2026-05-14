from __future__ import annotations
from harness.cloud.endpoint import CloudEndpoint
from harness.comms import Message


class CloudRouter:
    def __init__(self):
        self._ep = CloudEndpoint()

    def route(self, msg: Message) -> Message:
        result = self._ep.infer(msg)
        if result is None:
            return Message(
                caste=msg.caste,
                action=msg.action,
                payload={"error": "cloud not enabled or unreachable"},
                session=msg.session,
            )
        return result

    def available(self) -> bool:
        return self._ep.health()

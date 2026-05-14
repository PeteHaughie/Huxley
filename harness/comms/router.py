from __future__ import annotations
from harness.comms import Message, Caste, Action
from harness.caste.gamma import Gamma
from harness.caste.beta import Beta
from harness.caste.alpha import Alpha


class Router:
    def __init__(self):
        self._gamma = Gamma()
        self._beta = Beta()
        self._alpha = Alpha()
        self._routes: dict[Caste, object] = {
            Caste.GAMMA: self._gamma,
            Caste.BETA: self._beta,
            Caste.ALPHA: self._alpha,
        }

    def dispatch(self, msg: Message) -> Message:
        handler = self._routes.get(msg.caste)
        if handler is None:
            return Message(
                caste=Caste.ALPHA,
                action=Action.ROUTE,
                payload={"error": f"unknown caste: {msg.caste}"},
                session=msg.session,
            )
        return handler.infer(msg)

    def health(self, caste: Caste) -> bool:
        handler = self._routes.get(caste)
        if handler is None:
            return False
        return handler.health()

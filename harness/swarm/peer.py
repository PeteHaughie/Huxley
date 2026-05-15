import time
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Peer:
    addr: str
    port: int
    hostname: str
    castes: str
    load: float
    version: str
    last_seen: float = field(default_factory=time.time)
    lost: bool = False

    def age(self) -> float:
        return time.time() - self.last_seen

    def key(self) -> str:
        return f"{self.addr}:{self.port}"

    def to_dict(self) -> dict:
        return {
            "addr": self.addr,
            "port": self.port,
            "hostname": self.hostname,
            "castes": self.castes,
            "load": self.load,
            "version": self.version,
            "age": round(self.age(), 1),
            "lost": self.lost,
        }


class PeerTable:
    def __init__(self, stale_timeout: float = 90.0):
        self._peers: dict[str, Peer] = {}
        self._lock = threading.Lock()
        self._stale_timeout = stale_timeout

    def add(self, info: dict) -> Peer:
        key = f"{info['addr']}:{info['port']}"
        with self._lock:
            now = time.time()
            if key in self._peers:
                p = self._peers[key]
                p.hostname = info.get("hostname", p.hostname)
                p.castes = info.get("castes", p.castes)
                p.load = info.get("load", p.load)
                p.version = info.get("version", p.version)
                p.last_seen = now
                p.lost = False
            else:
                p = Peer(
                    addr=info["addr"],
                    port=info["port"],
                    hostname=info.get("hostname", ""),
                    castes=info.get("castes", ""),
                    load=info.get("load", 0.0),
                    version=info.get("version", "0.1.0"),
                    last_seen=now,
                )
                self._peers[key] = p
            return p

    def list_active(self) -> list[Peer]:
        with self._lock:
            now = time.time()
            for p in list(self._peers.values()):
                was_lost = p.lost
                p.lost = (now - p.last_seen) > self._stale_timeout
                if p.lost and not was_lost:
                    pass
            return [p for p in self._peers.values() if not p.lost]

    def list_all(self) -> list[Peer]:
        with self._lock:
            now = time.time()
            for p in self._peers.values():
                p.lost = (now - p.last_seen) > self._stale_timeout
            return list(self._peers.values())

    def count(self) -> int:
        with self._lock:
            return len(self._peers)

    def remove(self, key: str) -> bool:
        with self._lock:
            if key in self._peers:
                del self._peers[key]
                return True
            return False

    def prune(self):
        with self._lock:
            now = time.time()
            self._peers = {k: p for k, p in self._peers.items() if (now - p.last_seen) < self._stale_timeout * 2}

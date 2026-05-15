import json
import socket
import struct
import time
import threading
from typing import Optional

from harness.swarm.peer import PeerTable

MULTICAST_GROUP = "239.255.43.21"
MULTICAST_PORT = 43210
ANNOUNCE_INTERVAL = 30
BUFFER_SIZE = 2048


def _build_announce(hostname: str, daemon_port: int, castes: str = "αβγ", load: float = 0.0, version: str = "0.1.0") -> bytes:
    payload = {
        "type": "monster_announce",
        "hostname": hostname,
        "port": daemon_port,
        "castes": castes,
        "load": load,
        "version": version,
    }
    return json.dumps(payload, ensure_ascii=False).encode()


def _parse_announce(data: bytes, addr: tuple) -> Optional[dict]:
    try:
        payload = json.loads(data.decode())
        if payload.get("type") != "monster_announce":
            return None
        return {
            "addr": addr[0],
            "port": payload.get("port", 0),
            "hostname": payload.get("hostname", addr[0]),
            "castes": payload.get("castes", ""),
            "load": payload.get("load", 0.0),
            "version": payload.get("version", "0.0.0"),
        }
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


class DiscoveryService:
    def __init__(self, daemon_port: int, peer_table: PeerTable):
        self.daemon_port = daemon_port
        self._peers = peer_table
        self._running = False
        self._send_thread: Optional[threading.Thread] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._send_sock: Optional[socket.socket] = None
        self._recv_sock: Optional[socket.socket] = None
        self._hostname = socket.gethostname()
        self._self_key = f"{self._get_local_ip()}:{daemon_port}"

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            self._recv_sock = self._make_recv_socket()
            self._send_sock = self._make_send_socket()
        except OSError as e:
            print(f"γ|swarm|sock_err|{e}", flush=True)
            self._running = False
            return
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True, name="swarm-recv")
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True, name="swarm-send")
        self._recv_thread.start()
        self._send_thread.start()
        print(f"γ|swarm|start|{MULTICAST_GROUP}:{MULTICAST_PORT}", flush=True)

    def stop(self):
        self._running = False
        for s in (self._send_sock, self._recv_sock):
            if s:
                try:
                    s.close()
                except OSError:
                    pass
        for t in (self._send_thread, self._recv_thread):
            if t:
                t.join(timeout=3)
        print("γ|swarm|stop", flush=True)

    def _make_recv_socket(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        try:
            s.bind(("0.0.0.0", MULTICAST_PORT))
        except OSError:
            s.bind(("0.0.0.0", 0))
        mreq = struct.pack("4sl", socket.inet_aton(MULTICAST_GROUP), socket.INADDR_ANY)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        s.settimeout(2.0)
        return s

    def _make_send_socket(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("0.0.0.0"))
        s.settimeout(1.0)
        return s

    def _send_loop(self):
        while self._running:
            try:
                data = _build_announce(self._hostname, self.daemon_port)
                self._send_sock.sendto(data, (MULTICAST_GROUP, MULTICAST_PORT))
            except OSError:
                pass
            for _ in range(ANNOUNCE_INTERVAL):
                if not self._running:
                    return
                time.sleep(1)

    @staticmethod
    def _get_local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("239.255.43.21", 43210))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except OSError:
            return "127.0.0.1"

    def _recv_loop(self):
        while self._running:
            try:
                data, addr = self._recv_sock.recvfrom(BUFFER_SIZE)
                info = _parse_announce(data, addr)
                if info and info["addr"] != "127.0.0.1":
                    key = f"{info['addr']}:{info['port']}"
                    if key != self._self_key:
                        self._peers.add(info)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    time.sleep(1)
                continue

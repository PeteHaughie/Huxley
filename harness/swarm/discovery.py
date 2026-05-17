import json
import socket
import struct
import time
import uuid
import threading
from typing import Optional

from harness.swarm.peer import PeerTable

MULTICAST_GROUP = "239.255.43.21"
MULTICAST_PORT = 43210
ANNOUNCE_INTERVAL = 30
BUFFER_SIZE = 2048


def _build_announce(hostname: str, daemon_port: int, castes: str = "αβγ", load: float = 0.0, version: str = "0.1.0", instance_id: str = "") -> bytes:
    payload = {
        "type": "huxley_announce",
        "hostname": hostname,
        "port": daemon_port,
        "castes": castes,
        "load": load,
        "version": version,
        "instance_id": instance_id,
    }
    return json.dumps(payload, ensure_ascii=False).encode()


def _parse_announce(data: bytes, addr: tuple) -> Optional[dict]:
    try:
        payload = json.loads(data.decode())
        if payload.get("type") != "huxley_announce":
            return None
        return {
            "addr": addr[0],
            "port": payload.get("port", 0),
            "hostname": payload.get("hostname", addr[0]),
            "castes": payload.get("castes", ""),
            "load": payload.get("load", 0.0),
            "version": payload.get("version", "0.0.0"),
            "instance_id": payload.get("instance_id", ""),
        }
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _lan_interfaces() -> list[dict]:
    """Return list of {ip, bcast} for non-loopback interfaces with an IPv4 addr."""
    ifaces = []
    seen = set()
    try:
        import subprocess
        r = subprocess.run(["ifconfig", "-l"], capture_output=True, text=True, timeout=3)
        for name in r.stdout.strip().split():
            r2 = subprocess.run(["ifconfig", name], capture_output=True, text=True, timeout=3)
            for line in r2.stdout.splitlines():
                line = line.strip()
                if line.startswith("inet ") and "127.0.0.1" not in line:
                    parts = line.split()
                    ip = parts[1]
                    if ip in seen:
                        continue
                    seen.add(ip)
                    entry = {"ip": ip}
                    for i, p in enumerate(parts):
                        if p == "broadcast" and i + 1 < len(parts):
                            entry["bcast"] = parts[i + 1]
                    ifaces.append(entry)
    except Exception:
        pass
    if not ifaces:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("239.255.43.21", 43210))
            ip = s.getsockname()[0]
            s.close()
            if ip != "127.0.0.1":
                ifaces.append({"ip": ip})
        except OSError:
            pass
    return ifaces


def _lan_ips() -> list[str]:
    return [e["ip"] for e in _lan_interfaces()]


def test_multicast() -> dict:
    r = {"interface": None, "interfaces": [], "send_ok": False, "recv_ok": False, "loopback": False, "error": None, "firewall": None}
    try:
        ips = _lan_ips()
        r["interface"] = ips[0] if ips else "?"
        for ip in ips:
            r["interfaces"].append(ip)
        recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        recv.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        recv.bind(("0.0.0.0", MULTICAST_PORT))
        for ip in ips:
            try:
                mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton(ip))
                recv.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
            except OSError:
                pass
        recv.settimeout(3.0)
        r["recv_ok"] = True
        payload = json.dumps({"type": "huxley_announce", "hostname": "test", "port": 0}).encode()
        send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        send.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for ip in ips:
            try:
                send.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                send.sendto(payload, (MULTICAST_GROUP, MULTICAST_PORT))
            except OSError:
                pass
        send.sendto(payload, ("255.255.255.255", MULTICAST_PORT))
        send.close()
        r["send_ok"] = True
        try:
            data, addr = recv.recvfrom(2048)
            r["loopback"] = True
            r["loopback_from"] = str(addr)
        except socket.timeout:
            r["loopback"] = False
        recv.close()
    except OSError as e:
        r["error"] = str(e)
    try:
        import subprocess
        pf = subprocess.run(
            ["/usr/libexec/ApplicationFirewall/socketfilterfw", "--getglobalstate"],
            capture_output=True, text=True, timeout=5,
        )
        r["firewall"] = (pf.stdout.strip() or pf.stderr.strip())[:120]
    except Exception:
        r["firewall"] = "unknown"
    return r


def _bcast_addrs() -> list[str]:
    """Return list of subnet broadcast addresses for non-loopback interfaces."""
    addrs = []
    for iface in _lan_interfaces():
        bcast = iface.get("bcast")
        if bcast:
            addrs.append(bcast)
    return addrs


def send_manual_announce(hostname: str, daemon_port: int, castes: str = "αβγ", instance_id: str = ""):
    ips = _lan_ips()
    bcasts = _bcast_addrs()
    data = _build_announce(hostname, daemon_port, castes=castes, instance_id=instance_id)
    def _send_with_socket(label: str, send_fn) -> int:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        except OSError as e:
            print(f"γ|swarm|announce|err|{label}_socket|{e}", flush=True)
            return 0
        try:
            return send_fn(sock)
        except OSError as e:
            print(f"γ|swarm|announce|err|{label}_send|{e}", flush=True)
            return 0
        finally:
            sock.close()

    def _send_mcast(sock: socket.socket) -> int:
        sent = 0
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        for ip in ips:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                sock.sendto(data, (MULTICAST_GROUP, MULTICAST_PORT))
                sent += 1
            except OSError:
                pass
        return sent

    def _send_bcast(sock: socket.socket) -> int:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sent = 0
        for bcast in bcasts:
            try:
                sock.sendto(data, (bcast, MULTICAST_PORT))
                sent += 1
            except OSError:
                pass
        sock.sendto(data, ("255.255.255.255", MULTICAST_PORT))
        sent += 1
        return sent

    sent = _send_with_socket("mcast", _send_mcast) + _send_with_socket("bcast", _send_bcast)
    status = "sent" if sent > 0 else "attempted"
    iface_parts = []
    for iface in _lan_interfaces():
        ip = iface["ip"]
        b = iface.get("bcast", "?")
        iface_parts.append(f"{ip} bcast={b}")
    print(f"γ|swarm|announce|{status}|{MULTICAST_GROUP}:{MULTICAST_PORT}+bcast|ifaces={','.join(iface_parts)}", flush=True)


class DiscoveryService:
    def __init__(self, daemon_port: int, peer_table: PeerTable):
        self.daemon_port = daemon_port
        self._peers = peer_table
        self._running = False
        self._send_thread: Optional[threading.Thread] = None
        self._recv_thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None
        self._hostname = socket.gethostname()
        self._local_ips = _lan_ips()
        self._self_ports = {daemon_port}
        self._instance_id = uuid.uuid4().hex[:12]

    def start(self):
        if self._running:
            return
        self._running = True
        try:
            self._sock = self._make_socket()
        except OSError as e:
            print(f"γ|swarm|sock_err|{e}", flush=True)
            self._running = False
            return
        print(f"γ|swarm|start|mcast+bcast|port={MULTICAST_PORT}|ifaces={','.join(self._local_ips)}", flush=True)
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True, name="swarm-recv")
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True, name="swarm-send")
        self._recv_thread.start()
        self._send_thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        for t in (self._send_thread, self._recv_thread):
            if t:
                t.join(timeout=3)
        print("γ|swarm|stop", flush=True)

    def _make_socket(self) -> socket.socket:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("0.0.0.0", MULTICAST_PORT))
        joined = 0
        for ip in self._local_ips:
            try:
                mreq = struct.pack("4s4s", socket.inet_aton(MULTICAST_GROUP), socket.inet_aton(ip))
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                joined += 1
            except OSError:
                pass
        if joined == 0:
            print(f"γ|swarm|warn|IP_ADD_MEMBERSHIP failed on all interfaces, relying on broadcast", flush=True)
        s.settimeout(2.0)
        return s

    def _send_loop(self):
        for _ in range(3):
            if not self._running:
                return
            self._announce_all()
            time.sleep(1)
        while self._running:
            self._announce_all()
            for _ in range(ANNOUNCE_INTERVAL):
                if not self._running:
                    return
                time.sleep(1)

    def _announce_all(self):
        try:
            from harness.board import JobBoard, State
            board = JobBoard()
            load = float(len(board.list(state=State.IN_PROGRESS)))
        except Exception:
            load = 0.0
        try:
            data = _build_announce(self._hostname, self.daemon_port, load=load, instance_id=self._instance_id)
            for ip in self._local_ips:
                try:
                    self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                    self._sock.sendto(data, (MULTICAST_GROUP, MULTICAST_PORT))
                except OSError:
                    pass
            bcasts = _bcast_addrs()
            for bcast in bcasts:
                try:
                    self._sock.sendto(data, (bcast, MULTICAST_PORT))
                except OSError:
                    pass
            self._sock.sendto(data, ("255.255.255.255", MULTICAST_PORT))
        except OSError:
            pass

    def _recv_loop(self):
        while self._running:
            try:
                data, addr = self._sock.recvfrom(BUFFER_SIZE)
                info = _parse_announce(data, addr)
                if info:
                    same_id = info.get("instance_id", "") == self._instance_id
                    local_port = info["port"] in self._self_ports
                    local_ip = info["addr"] in self._local_ips
                    is_self = same_id or (local_ip and local_port)
                    if not is_self:
                        self._peers.add(info)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    time.sleep(1)
                continue

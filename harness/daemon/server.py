import json
import os
import threading
import http.server
import urllib.parse
from harness.daemon.scheduler import SchedulerEngine, Schedule, _ensure_scheduler_dir

DAEMON_PORT = int(os.environ.get("MONSTERD_PORT", "8083"))

_scheduler = SchedulerEngine()


class DaemonHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, data, status=200, ctype="application/json"):
        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _path_parts(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def do_GET(self):
        path, qs = self._path_parts()
        if path == "/health":
            self._send({"status": "ok", "scheduler_running": _scheduler.running})
        elif path == "/v1/status":
            schedules = _scheduler.list_schedules()
            self._send({
                "running": True,
                "scheduler_running": _scheduler.running,
                "schedules": len(schedules),
                "uptime": None,
            })
        elif path == "/v1/schedules":
            self._send([s.to_dict() for s in _scheduler.list_schedules()])
        elif path.startswith("/v1/schedules/"):
            sid = path.split("/v1/schedules/")[1]
            s = _scheduler.get_schedule(sid)
            if s:
                self._send(s.to_dict())
            else:
                self._send({"error": "not found"}, 404)
        elif path == "/v1/schedule/history":
            sid = qs.get("id", [None])[0]
            self._send(_scheduler.history(sid))
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        path, _ = self._path_parts()
        if path == "/v1/schedules":
            body = self._read_body()
            s = Schedule(
                when=body.get("when", {"type": "interval", "every": 3600}),
                action=body.get("action", {"type": "post_to_board", "level": "task", "title": "scheduled"}),
                enabled=body.get("enabled", True),
                title=body.get("title", ""),
                missed_behaviour=body.get("missed_behaviour", "skip"),
            )
            _scheduler.add_schedule(s)
            self._send(s.to_dict(), 201)
        elif path == "/v1/shutdown":
            _scheduler.stop()
            self._send({"status": "stopping"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
        else:
            self._send({"error": "not found"}, 404)

    def do_DELETE(self):
        path, _ = self._path_parts()
        if path.startswith("/v1/schedules/"):
            sid = path.split("/v1/schedules/")[1]
            if _scheduler.remove_schedule(sid):
                self._send({"status": "removed"})
            else:
                self._send({"error": "not found"}, 404)
        else:
            self._send({"error": "not found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def run_daemon(port: int = DAEMON_PORT):
    _ensure_scheduler_dir()
    _scheduler.start()
    addr = ("127.0.0.1", port)
    server = http.server.HTTPServer(addr, DaemonHandler)
    print(f"γ|monsterd|listen|http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _scheduler.stop()
        server.server_close()

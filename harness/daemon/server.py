import json
import os
import threading
import http.server
import urllib.parse
from harness.daemon.scheduler import SchedulerEngine, Schedule, _ensure_scheduler_dir, _peer_table
from harness.board import JobBoard, State
from harness.config import load_config

DAEMON_PORT = int(os.environ.get("HUXLEYD_PORT", "8083"))

_scheduler = SchedulerEngine(daemon_port=DAEMON_PORT)


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

    def _send_error_json(self, status: int, message: str):
        self._send({"error": {"message": message, "type": "invalid_request_error"}}, status=status)

    def _begin_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def _write_sse_event(self, payload: dict | str):
        if isinstance(payload, str):
            data = payload
        else:
            data = json.dumps(payload)
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def _api_enabled(self) -> bool:
        return load_config().get("api", {}).get("enabled", True)

    def _localhost_only(self) -> bool:
        return load_config().get("api", {}).get("localhost_only", True)

    def _is_loopback_client(self) -> bool:
        host = (self.client_address[0] or "").strip()
        return host in {"127.0.0.1", "::1", "::ffff:127.0.0.1"}

    def do_GET(self):
        path, qs = self._path_parts()
        if path == "/health":
            self._send({"status": "ok", "scheduler_running": _scheduler.running})
        elif path == "/v1/models":
            if not self._api_enabled():
                self._send({"error": "not found"}, 404)
                return
            if self._localhost_only() and not self._is_loopback_client():
                self._send_error_json(403, "OpenAI-compatible API is restricted to localhost")
                return
            self._send({"object": "list", "data": _scheduler.openai_models()})
        elif path == "/v1/status":
            schedules = _scheduler.list_schedules()
            api_cfg = load_config().get("api", {})
            daemon_url = f"http://127.0.0.1:{DAEMON_PORT}/v1"
            self._send({
                "running": True,
                "scheduler_running": _scheduler.running,
                "schedules": len(schedules),
                "uptime": None,
                "openai_api": {
                    "enabled": api_cfg.get("enabled", True),
                    "localhost_only": api_cfg.get("localhost_only", True),
                    "url": daemon_url,
                    "models": [m["id"] for m in _scheduler.openai_models()],
                },
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
        elif path == "/v1/swarm/peers":
            self._send([p.to_dict() for p in _peer_table.list_active()])
        elif path == "/v1/swarm/peers/all":
            self._send([p.to_dict() for p in _peer_table.list_all()])
        elif path == "/v1/swarm/activity":
            activity = _scheduler.peer_activity_snapshot()
            peers = []
            for peer in _peer_table.list_all():
                item = peer.to_dict()
                item["activity"] = activity.get(peer.key())
                peers.append(item)
            self._send(peers)
        elif path == "/v1/load":
            board = JobBoard()
            self._send({"load": len(board.list(state=State.IN_PROGRESS))})
        elif path == "/v1/swarm/status":
            from harness.swarm.discovery import _lan_ips
            import socket
            ips = _lan_ips()
            self._send({
                "enabled": True,
                "hostname": socket.gethostname(),
                "lan_ip": ips[0] if ips else "?",
                "port": DAEMON_PORT,
                "peers": _peer_table.count(),
                "active_peers": len(_peer_table.list_active()),
            })
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        path, _ = self._path_parts()
        if path == "/v1/chat/completions":
            if not self._api_enabled():
                self._send({"error": "not found"}, 404)
                return
            if self._localhost_only() and not self._is_loopback_client():
                self._send_error_json(403, "OpenAI-compatible API is restricted to localhost")
                return
            body = self._read_body()
            model = body.get("model")
            if not model:
                self._send_error_json(400, "model is required")
                return
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                self._send_error_json(400, "messages must be a non-empty list")
                return
            max_tokens = body.get("max_tokens")
            if max_tokens is not None:
                try:
                    max_tokens = int(max_tokens)
                except (TypeError, ValueError):
                    self._send_error_json(400, "max_tokens must be an integer")
                    return
            try:
                temperature = float(body.get("temperature", 0.0))
            except (TypeError, ValueError):
                self._send_error_json(400, "temperature must be numeric")
                return
            if body.get("stream"):
                try:
                    self._begin_sse()
                    for chunk in _scheduler.openai_chat_completion_stream(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    ):
                        self._write_sse_event(chunk)
                    self._write_sse_event("[DONE]")
                except (BrokenPipeError, ConnectionResetError):
                    return
                except Exception as e:
                    try:
                        self._write_sse_event(
                            {"error": {"message": str(e), "type": "invalid_request_error"}}
                        )
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return
            try:
                response = _scheduler.openai_chat_completion(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except ValueError as e:
                self._send_error_json(404, str(e))
                return
            except RuntimeError as e:
                self._send_error_json(503, str(e))
                return
            except Exception as e:
                self._send_error_json(500, str(e))
                return
            self._send(response)
        elif path == "/v1/schedules":
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
        elif path == "/v1/units/execute":
            body = self._read_body()
            try:
                result = _scheduler.infer(body.get("prompt", ""), "unit")
                self._send({"result": result})
            except Exception as e:
                self._send({"error": str(e)}, 500)
        elif path == "/v1/tasks/execute":
            body = self._read_body()
            try:
                result = _scheduler.execute_task(body.get("title", ""), body.get("prompt", ""))
                self._send(result)
            except Exception as e:
                self._send({"error": str(e)}, 500)
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
    addr = ("0.0.0.0", port)
    server = http.server.ThreadingHTTPServer(addr, DaemonHandler)
    print(f"γ|huxleyd|listen|http://0.0.0.0:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _scheduler.stop()
        server.server_close()

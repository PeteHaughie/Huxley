import json
import math
import os
import threading
import http.server
import ipaddress
import urllib.parse
from collections.abc import Iterator
from harness.daemon.scheduler import SchedulerEngine, Schedule, _ensure_scheduler_dir, _peer_table
from harness.board import JobBoard, State
from harness.comms.router import OpenAIRequestError
from harness.config import load_config

DAEMON_PORT = int(os.environ.get("HUXLEYD_PORT", "8083"))

_scheduler = SchedulerEngine(daemon_port=DAEMON_PORT)


class DaemonHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _apply_cors_headers(self):
        allow_origin = self._cors_origin()
        if not allow_origin:
            return
        self.send_header("Access-Control-Allow-Origin", allow_origin)
        if allow_origin != "*":
            self.send_header("Vary", "Origin")

    def _send(self, data, status=200, ctype="application/json"):
        if isinstance(data, str):
            data = data.encode()
        elif not isinstance(data, bytes):
            data = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self._apply_cors_headers()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _path_parts(self):
        parsed = urllib.parse.urlparse(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def _send_error_json(self, status: int, message: str, error_type: str = "invalid_request_error"):
        self._send({"error": {"message": message, "type": error_type}}, status=status)

    def _begin_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self._apply_cors_headers()
        self.end_headers()

    def _write_sse_event(self, payload: dict | str):
        if isinstance(payload, str):
            data = payload
        else:
            data = json.dumps(payload)
        self.wfile.write(f"data: {data}\n\n".encode())
        self.wfile.flush()

    def _api_config(self) -> dict:
        if not hasattr(self, "_req_api_cfg"):
            api_cfg = load_config().get("api")
            self._req_api_cfg = api_cfg if isinstance(api_cfg, dict) else {}
        return self._req_api_cfg

    def _api_enabled(self) -> bool:
        return self._api_config().get("enabled", True)

    def _localhost_only(self) -> bool:
        return self._api_config().get("localhost_only", True)

    def _is_openai_route(self, path: str) -> bool:
        return path in {"/v1/models", "/v1/chat/completions"}

    def _is_loopback_host(self, host: str | None) -> bool:
        host = (host or "").strip().lower()
        if host == "localhost":
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return ip.is_loopback or (getattr(ip, "ipv4_mapped", None) is not None and ip.ipv4_mapped.is_loopback)

    def _is_loopback_client(self) -> bool:
        return self._is_loopback_host(self.client_address[0])

    def _is_loopback_origin(self, origin: str) -> bool:
        return self._is_loopback_host(urllib.parse.urlparse(origin).hostname)

    def _cors_origin(self) -> str | None:
        origin = self.headers.get("Origin", "").strip()
        if not origin or "\r" in origin or "\n" in origin:
            return None
        parsed = urllib.parse.urlparse(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        route, _ = self._path_parts()
        if not self._is_openai_route(route):
            return None
        if self._is_loopback_host(parsed.hostname):
            return "*"
        return None

    def do_GET(self):
        path, qs = self._path_parts()
        if path == "/health":
            self._send({"status": "ok", "scheduler_running": _scheduler.running})
        elif path == "/v1/models":
            if not self._api_enabled():
                self._send_error_json(404, "not found", error_type="not_found_error")
                return
            if self._localhost_only() and not self._is_loopback_client():
                self._send_error_json(403, "OpenAI-compatible API is restricted to localhost")
                return
            self._send({"object": "list", "data": _scheduler.openai_models()})
        elif path == "/v1/status":
            schedules = _scheduler.list_schedules()
            api_cfg = load_config().get("api")
            api_cfg = api_cfg if isinstance(api_cfg, dict) else {}
            daemon_url = f"http://127.0.0.1:{self.server.server_port}/v1"
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
                self._send_error_json(404, "not found", error_type="not_found_error")
                return
            if self._localhost_only() and not self._is_loopback_client():
                self._send_error_json(403, "OpenAI-compatible API is restricted to localhost")
                return
            content_type = self.headers.get_content_type()
            if content_type != "application/json":
                self._send_error_json(415, "Content-Type must be application/json")
                return
            origin = self.headers.get("Origin", "").strip()
            if origin and not self._is_loopback_origin(origin):
                self._send_error_json(403, "Origin is not allowed")
                return
            try:
                body = self._read_body()
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_error_json(400, "invalid JSON body")
                return
            except (ValueError, OverflowError):
                self._send_error_json(400, "invalid Content-Length")
                return
            if not isinstance(body, dict):
                self._send_error_json(400, "JSON body must be an object")
                return
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
                if isinstance(max_tokens, bool):
                    self._send_error_json(400, "max_tokens must be an integer")
                    return
                if isinstance(max_tokens, int):
                    pass
                elif isinstance(max_tokens, str):
                    stripped = max_tokens.strip()
                    if not stripped or not stripped.lstrip("+-").isdigit():
                        self._send_error_json(400, "max_tokens must be an integer")
                        return
                    max_tokens = int(stripped)
                else:
                    self._send_error_json(400, "max_tokens must be an integer")
                    return
                if max_tokens <= 0:
                    self._send_error_json(400, "max_tokens must be greater than 0")
                    return
            temperature = body.get("temperature", 0.0)
            if isinstance(temperature, bool):
                self._send_error_json(400, "temperature must be numeric")
                return
            try:
                temperature = float(temperature)
            except (TypeError, ValueError):
                self._send_error_json(400, "temperature must be numeric")
                return
            if not math.isfinite(temperature) or temperature < 0:
                self._send_error_json(400, "temperature must be finite and non-negative")
                return
            request_options = {
                key: body[key]
                for key in ("tools", "tool_choice", "functions", "function_call", "response_format")
                if key in body
            }
            stream = body.get("stream", False)
            if not isinstance(stream, bool):
                self._send_error_json(400, "stream must be a boolean")
                return
            if stream:
                stream_iter: Iterator[dict] = _scheduler.openai_chat_completion_stream(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    request_options=request_options,
                )
                try:
                    first_chunk = next(stream_iter)
                except StopIteration:
                    try:
                        self._begin_sse()
                        self._write_sse_event("[DONE]")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                    return
                except (BrokenPipeError, ConnectionResetError):
                    return
                except OpenAIRequestError as e:
                    self._send_error_json(e.status, str(e), error_type=e.error_type)
                    return
                except ValueError as e:
                    self._send_error_json(404, str(e), error_type="not_found_error")
                    return
                except RuntimeError as e:
                    print(f"γ|huxleyd|openai_stream_err|{e}", flush=True)
                    self._send_error_json(503, "service temporarily unavailable", error_type="server_error")
                    return
                except Exception as e:
                    print(f"γ|huxleyd|openai_stream_err|{e}", flush=True)
                    self._send_error_json(500, "internal server error", error_type="server_error")
                    return
                try:
                    self._begin_sse()
                    self._write_sse_event(first_chunk)
                    for chunk in stream_iter:
                        self._write_sse_event(chunk)
                    self._write_sse_event("[DONE]")
                except (BrokenPipeError, ConnectionResetError):
                    return
                except OpenAIRequestError as e:
                    try:
                        self._write_sse_event({"error": {"message": str(e), "type": e.error_type}})
                        self._write_sse_event("[DONE]")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                except Exception as e:
                    print(f"γ|huxleyd|openai_stream_err|{e}", flush=True)
                    try:
                        self._write_sse_event(
                            {"error": {"message": "internal server error", "type": "server_error"}}
                        )
                        self._write_sse_event("[DONE]")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                finally:
                    close_stream = getattr(stream_iter, "close", None)
                    if callable(close_stream):
                        close_stream()
                return
            try:
                response = _scheduler.openai_chat_completion(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    request_options=request_options,
                )
            except OpenAIRequestError as e:
                self._send_error_json(e.status, str(e), error_type=e.error_type)
                return
            except ValueError as e:
                self._send_error_json(404, str(e), error_type="not_found_error")
                return
            except RuntimeError as e:
                print(f"γ|huxleyd|openai_err|{e}", flush=True)
                self._send_error_json(503, "service temporarily unavailable", error_type="server_error")
                return
            except Exception as e:
                print(f"γ|huxleyd|openai_err|{e}", flush=True)
                self._send_error_json(500, "internal server error", error_type="server_error")
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
        self._apply_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


def run_daemon(port: int = DAEMON_PORT):
    _ensure_scheduler_dir()
    _scheduler.start()
    addr = ("0.0.0.0", port)
    server = http.server.HTTPServer(addr, DaemonHandler)
    print(f"γ|huxleyd|listen|http://0.0.0.0:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _scheduler.stop()
        server.server_close()

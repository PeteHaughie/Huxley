from __future__ import annotations
import json
import os
import subprocess
import threading
from typing import Any


def _resolve_union_type(types: list) -> dict:
    for t in types:
        if isinstance(t, dict) and t.get("type") not in (None, "null"):
            return t
        if isinstance(t, dict) and "description" in t:
            return t
    return {"type": "string", "description": ""}


class McpBridge:
    def __init__(self, server_name: str, config: dict):
        self._name = server_name
        self._command = config.get("command", "")
        self._args = config.get("args", [])
        self._env: dict = config.get("env", {}) or {}
        self._auto_start = bool(config.get("auto_start", True))
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._tools: list[dict] = []
        self._connected = False
        self._defs: list[dict] = []
        self._req_id = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self):
        with self._lock:
            if self._connected:
                return
            if not self._auto_start:
                return
            if not self._command:
                raise RuntimeError(
                    f"MCP server '{self._name}' has no command configured"
                )
            self._start_process()
            self._handshake()
            self._discover_tools()
            self._connected = True

    def disconnect(self):
        with self._lock:
            self._connected = False
            self._defs = []
            self._tools = []
            if self._proc is not None:
                try:
                    self._proc.stdin.close()
                except Exception:
                    pass
                try:
                    self._proc.wait(timeout=3)
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                self._proc = None

    def definitions(self) -> list[dict]:
        if not self._defs:
            self.connect()
        return list(self._defs)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if not self._connected:
            self.connect()
        with self._lock:
            resp = self._send_request(
                "tools/call",
                {"name": name, "arguments": arguments},
            )
            result = resp.get("result", resp)
            if result.get("isError"):
                content_items = result.get("content", [])
                err_msg = ""
                for item in content_items:
                    if isinstance(item, dict):
                        err_msg += item.get("text", str(item))
                raise RuntimeError(
                    err_msg.strip() or f"MCP tool '{name}' returned error"
                )
            content_items = result.get("content", [])
            parts = []
            for item in content_items:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    if text:
                        parts.append(text)
            return "\n".join(parts) if parts else str(result)

    def _start_process(self):
        merged_env = dict(os.environ)
        merged_env.update({k: v for k, v in self._env.items() if v})
        self._proc = subprocess.Popen(
            [self._command] + list(self._args),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
        )
        self._stderr_lines: list[str] = []

        def _drain_stderr():
            assert self._proc is not None and self._proc.stderr is not None
            for raw in self._proc.stderr:
                line = raw.decode(errors="replace").rstrip()
                self._stderr_lines = (self._stderr_lines + [line])[-100:]

        threading.Thread(target=_drain_stderr, daemon=True).start()

    def _send_request(self, method: str, params: dict | None = None) -> dict:
        self._req_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
        }
        if params is not None:
            req["params"] = params
        self._write(req)
        return self._read()

    def _send_notification(self, method: str):
        self._write({"jsonrpc": "2.0", "method": method})

    def _write(self, msg: dict):
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP bridge process not running")
        line = json.dumps(msg) + "\n"
        self._proc.stdin.write(line.encode())
        self._proc.stdin.flush()

    def _read(self) -> dict:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("MCP bridge process not running")
        line = self._proc.stdout.readline()
        if not line:
            stderr = "\n".join(getattr(self, "_stderr_lines", [])[-10:])
            raise RuntimeError(
                f"MCP server process ended (exit={self._proc.poll()}, stderr={stderr[:200]})"
            )
        return json.loads(line.decode())

    def _handshake(self):
        resp = self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "huxley", "version": "0.1.0"},
            },
        )
        result = resp.get("result", {})
        self._server_version = result.get("protocolVersion", "")
        self._send_notification("notifications/initialized")

    def _discover_tools(self):
        resp = self._send_request("tools/list")
        result = resp.get("result", {})
        raw_tools = result.get("tools", [])
        self._tools = []
        self._defs = []
        for t in raw_tools:
            tool_name = t.get("name", "")
            tool_dict = {
                "name": tool_name,
                "description": t.get("description", ""),
                "inputSchema": t.get("inputSchema", {}),
            }
            try:
                openai_def = self._to_openai_def(tool_dict)
                self._tools.append(tool_dict)
                self._defs.append(openai_def)
            except Exception as e:
                print(
                    f"\u03b3|mcp|schema_warn|{self._name}|{tool_name}|{e}",
                    flush=True,
                )

    def _to_openai_def(self, tool: dict) -> dict:
        name = tool.get("name", "")
        description = tool.get("description", "")
        input_schema = tool.get("inputSchema", {})
        properties = {}
        required: list[str] = []
        raw_props = (
            input_schema.get("properties", {}) if isinstance(input_schema, dict) else {}
        )
        raw_required = (
            input_schema.get("required", []) if isinstance(input_schema, dict) else []
        )
        for prop_name, prop_schema in raw_props.items():
            if isinstance(prop_schema, dict):
                entry = self._normalize_prop_schema(prop_schema)
                properties[prop_name] = entry
            elif isinstance(prop_schema, str):
                properties[prop_name] = {"type": prop_schema, "description": ""}
        if isinstance(raw_required, list):
            required = raw_required
        parameters: dict[str, object] = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    @staticmethod
    def _normalize_prop_schema(schema: dict) -> dict:
        types = schema.get("anyOf") or schema.get("oneOf")
        if types and isinstance(types, list):
            resolved = _resolve_union_type(types)
            return {
                "type": resolved.get("type", "string"),
                "description": resolved.get("description", schema.get("description", "")),
            }

        return {
            "type": schema.get("type", "string"),
            "description": schema.get("description", "") or "",
        }

    def __repr__(self) -> str:
        return f"McpBridge(name={self._name!r}, connected={self._connected})"

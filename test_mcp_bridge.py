"""Unit tests for McpBridge using a fake stdio JSON-RPC server."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from harness.tool.mcp_bridge import McpBridge
from harness.tool.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers to build a minimal fake MCP server (subprocess writing to stdout)
# ---------------------------------------------------------------------------

_FAKE_SERVER_SCRIPT = textwrap.dedent("""\
    import json, sys

    def respond(req_id, result):
        msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\\n"
        sys.stdout.write(msg)
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        req_id = req.get("id")

        if method == "initialize":
            respond(req_id, {"protocolVersion": "2024-11-05", "capabilities": {}})
        elif method == "notifications/initialized":
            pass  # notification, no response needed
        elif method == "tools/list":
            respond(req_id, {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echoes the input.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"text": {"type": "string", "description": "Text to echo"}},
                            "required": ["text"],
                        },
                    }
                ]
            })
        elif method == "tools/call":
            args = req.get("params", {}).get("arguments", {})
            text = args.get("text", "")
            respond(req_id, {
                "content": [{"type": "text", "text": f"echo: {text}"}],
                "isError": False,
            })
""")


def _start_fake_server() -> subprocess.Popen:
    """Start a fake MCP server subprocess."""
    return subprocess.Popen(
        [sys.executable, "-c", _FAKE_SERVER_SCRIPT],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class TestMcpBridgeHandshake(unittest.TestCase):
    """Test McpBridge handshake and tool discovery via fake server."""

    def _make_bridge(self) -> McpBridge:
        proc = _start_fake_server()
        bridge = McpBridge(
            "fake",
            {"command": sys.executable, "args": ["-c", _FAKE_SERVER_SCRIPT]},
        )
        # Inject the already-started process to avoid spawning another
        bridge._proc = proc
        # Start stderr drain thread
        bridge._stderr_lines: list[str] = []

        def _drain():
            assert bridge._proc is not None and bridge._proc.stderr is not None
            for raw in bridge._proc.stderr:
                line = raw.decode(errors="replace").rstrip()
                bridge._stderr_lines = (bridge._stderr_lines + [line])[-100:]

        threading.Thread(target=_drain, daemon=True).start()
        return bridge

    def tearDown(self):
        # Cleanup any leftover processes
        pass

    def test_handshake_and_tool_discovery(self):
        bridge = self._make_bridge()
        bridge._handshake()
        bridge._discover_tools()
        bridge._connected = True

        defs = bridge.definitions()
        self.assertEqual(len(defs), 1)
        fn = defs[0]["function"]
        self.assertEqual(fn["name"], "echo")
        self.assertIn("Echoes", fn["description"])
        params = fn["parameters"]
        self.assertIn("text", params["properties"])

        bridge.disconnect()

    def test_call_tool_returns_result(self):
        bridge = self._make_bridge()
        bridge._handshake()
        bridge._discover_tools()
        bridge._connected = True

        result = bridge._send_request("tools/call", {"name": "echo", "arguments": {"text": "hello"}})
        content = result.get("result", result).get("content", [])
        texts = [c["text"] for c in content if "text" in c]
        self.assertIn("echo: hello", texts)

        bridge.disconnect()

    def test_definitions_lazy_connect(self):
        """definitions() triggers connect() if not already connected."""
        bridge = McpBridge(
            "fake",
            {"command": sys.executable, "args": ["-c", _FAKE_SERVER_SCRIPT]},
        )
        # Not connected yet — definitions() should trigger connect()
        defs = bridge.definitions()
        self.assertIsInstance(defs, list)
        # Should have discovered at least our echo tool
        names = [d["function"]["name"] for d in defs]
        self.assertIn("echo", names)
        bridge.disconnect()

    def test_call_tool_via_bridge(self):
        """call_tool() returns the text content from the MCP server."""
        bridge = McpBridge(
            "fake",
            {"command": sys.executable, "args": ["-c", _FAKE_SERVER_SCRIPT]},
        )
        result = bridge.call_tool("echo", {"text": "world"})
        self.assertEqual(result, "echo: world")
        bridge.disconnect()

    def test_no_command_raises(self):
        """connect() raises RuntimeError when command is empty."""
        bridge = McpBridge("empty", {"command": ""})
        with self.assertRaises(RuntimeError):
            bridge.connect()

    def test_auto_start_false_skips_connect(self):
        """connect() is a no-op when auto_start=False."""
        bridge = McpBridge("noop", {"command": "nonexistent", "auto_start": False})
        bridge.connect()  # should not raise
        self.assertFalse(bridge.connected)

    def test_connect_disconnects_process_on_handshake_failure(self):
        bridge = McpBridge(
            "fake",
            {"command": sys.executable, "args": ["-c", "import time; time.sleep(60)"]},
        )
        with patch.object(bridge, "_handshake", side_effect=RuntimeError("boom")):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                bridge.connect()
        self.assertIsNone(bridge._proc)


class TestMcpBridgeSchemaConversion(unittest.TestCase):
    """Test schema normalisation helpers."""

    def test_normalize_plain_prop(self):
        schema = {"type": "string", "description": "A string"}
        result = McpBridge._normalize_prop_schema(schema)
        self.assertEqual(result["type"], "string")
        self.assertEqual(result["description"], "A string")

    def test_normalize_any_of(self):
        schema = {
            "anyOf": [
                {"type": "null"},
                {"type": "integer", "description": "An int"},
            ]
        }
        result = McpBridge._normalize_prop_schema(schema)
        self.assertEqual(result["type"], "integer")

    def test_normalize_falls_back_to_string(self):
        schema = {"anyOf": [{"type": "null"}]}
        result = McpBridge._normalize_prop_schema(schema)
        self.assertEqual(result["type"], "string")


class TestToolRegistryDefinitionsConnectsMcp(unittest.TestCase):
    """definitions() must trigger _connect_mcp_servers() so MCP tools are included."""

    def test_definitions_calls_connect_mcp_servers(self):
        reg = ToolRegistry()
        with patch.object(reg, "_connect_mcp_servers") as mock_connect:
            mock_connect.side_effect = lambda: None
            reg.definitions()
        mock_connect.assert_called_once()

    def test_definitions_includes_mcp_tools_after_connect(self):
        """After MCP is connected, definitions() returns both builtin and MCP defs."""
        reg = ToolRegistry()

        fake_def = {
            "type": "function",
            "function": {"name": "web_search", "description": "Search", "parameters": {"type": "object", "properties": {}}},
        }

        def _fake_connect():
            reg._mcp_tool_index["web_search"] = ("web-research", fake_def)
            reg._mcp_connected = True

        with patch.object(reg, "_connect_mcp_servers", side_effect=_fake_connect):
            defs = reg.definitions()

        names = [d["function"]["name"] for d in defs]
        self.assertIn("web_search", names)

    def test_connect_disconnects_failed_bridge(self):
        reg = ToolRegistry(mcp_bridges_cfg={"broken": {"command": "fake"}})
        bridge = MagicMock()
        bridge.definitions.side_effect = RuntimeError("boom")
        with patch("harness.tool.mcp_bridge.McpBridge", return_value=bridge):
            reg._connect_mcp_servers()
        bridge.disconnect.assert_called_once()


if __name__ == "__main__":
    unittest.main()

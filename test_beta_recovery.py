import unittest
from unittest.mock import patch, MagicMock

from harness.caste.beta import Beta, _extract_tool_calls
from harness.comms.message import Message, Caste, Action


class BetaRecoveryTests(unittest.TestCase):
    @patch("harness.caste.beta.Beta.start_server", return_value=True)
    def test_server_error_returns_error_message(self, mock_start):
        beta = Beta({
            "model": "/tmp/fake-model.gguf",
            "ctx_size": 24576,
        })

        mock_client = MagicMock()
        mock_client.chat.side_effect = RuntimeError("500 Internal Server Error")
        mock_client.health.return_value = True
        beta._client = mock_client

        msg = Message(
            caste=Caste.BETA,
            action=Action.INFER,
            payload={"prompt": "hello"},
            token_budget={"input": 256, "output": 32},
        )

        resp = beta.infer(msg)

        self.assertIn("error", resp.payload)
        self.assertIn("500", str(resp.payload["error"]))

    @patch("harness.caste.beta.Beta.start_server", return_value=True)
    def test_health_without_running_server(self, mock_start):
        beta = Beta({
            "model": "/tmp/fake-model.gguf",
            "ctx_size": 24576,
        })
        self.assertFalse(beta.health())

    def test_extract_tool_calls_leaves_id_unset_for_tool_service(self):
        text = '<tool_call>{"name":"read_file","arguments":{"path":"x.txt"}}</tool_call>'
        tool_calls, cleaned = _extract_tool_calls(text)
        self.assertEqual(cleaned, "")
        self.assertEqual(len(tool_calls), 1)
        self.assertNotIn("id", tool_calls[0])

    def test_should_restart_for_500(self):
        beta = Beta()
        self.assertTrue(beta._should_restart_for_error(RuntimeError("500 Internal Server Error")))
        self.assertTrue(beta._should_restart_for_error(RuntimeError("timed out")))
        self.assertFalse(beta._should_restart_for_error(RuntimeError("model load failed")))

    def test_start_server_fails_fast_when_port_owned_by_foreign_process(self):
        beta = Beta({"port": 8082})
        beta._client = MagicMock()
        beta._client.health.return_value = True

        with patch.object(beta, "_listener_pid", return_value=4321):
            with self.assertRaisesRegex(RuntimeError, "beta port 8082 already in use by pid 4321"):
                beta.start_server()

    def test_start_server_can_clear_foreign_listener_when_opted_in(self):
        beta = Beta({"port": 8082, "kill_stale_listener": True})
        beta._client = MagicMock()
        beta._client.health.return_value = False

        with (
            patch.object(beta, "_listener_pid", side_effect=[4321, None]),
            patch.object(beta, "_clear_stale_listener") as clear_listener,
            patch("harness.caste.beta.subprocess.Popen") as popen,
            patch.object(beta, "_wait_for_server", return_value=True),
        ):
            popen.return_value = MagicMock(stderr=MagicMock())
            self.assertTrue(beta.start_server())

        clear_listener.assert_called_once_with(4321)


if __name__ == "__main__":
    unittest.main()

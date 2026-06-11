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


if __name__ == "__main__":
    unittest.main()

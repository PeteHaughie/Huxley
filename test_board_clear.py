import json
import threading
import unittest
import urllib.request
from http.server import HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

import harness.board.core as board_core
import harness.board.serve as board_serve
from harness.board import JobBoard, Level, Task


class BoardClearTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._board_dir = Path(self._tmp.name)
        self._old_board_dir = board_core.HUXLEY_BOARD_DIR
        board_core.HUXLEY_BOARD_DIR = self._board_dir

    def tearDown(self):
        board_core.HUXLEY_BOARD_DIR = self._old_board_dir
        self._tmp.cleanup()

    def test_job_board_clear_removes_all_tasks(self):
        board = JobBoard()
        board.create(Task(level=Level.EPIC, title="epic"))
        board.create(Task(level=Level.TASK, title="task"))

        removed = board.clear()

        self.assertEqual(removed, 2)
        self.assertEqual(board.list(), [])

    def test_delete_tasks_endpoint_clears_board(self):
        board = JobBoard()
        board.create(Task(level=Level.EPIC, title="epic"))
        board.create(Task(level=Level.UNIT, title="unit"))

        server = HTTPServer(("127.0.0.1", 0), board_serve.BoardHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/tasks",
                method="DELETE",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()

        self.assertEqual(body, {"status": "cleared", "removed": 2})
        self.assertEqual(board.list(), [])

    def test_job_board_writes_do_not_leave_temp_files(self):
        board = JobBoard()
        task = board.create(Task(level=Level.UNIT, title="unit"))
        task.title = "updated"
        board.update(task)

        self.assertEqual(sorted(p.name for p in self._board_dir.iterdir()), [f"{task.id}.json"])


if __name__ == "__main__":
    unittest.main()

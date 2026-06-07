import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import harness.board.core as board_core
from harness.board import JobBoard, Task, Level


class ToolsE2ETests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self._old_board_dir = board_core.HUXLEY_BOARD_DIR
        board_core.HUXLEY_BOARD_DIR = Path(self._tmp.name)

        self._infer_calls = []

        def _fake_infer(prompt, level, max_output=512, use_tools=False):
            self._infer_calls.append({"prompt": prompt, "level": level, "use_tools": use_tools})
            return "1. Research the API\n2. Implement the solution\n3. Test the changes"

        from harness.daemon.scheduler import SchedulerEngine

        self.engine = SchedulerEngine()
        self.engine._infer = _fake_infer  # type: ignore[method-assign]
        self.board = JobBoard()

    def tearDown(self):
        self.board.clear()
        board_core.HUXLEY_BOARD_DIR = self._old_board_dir
        self._tmp.cleanup()

    def test_tools_tag_propagates_epic_to_tasks(self):
        epic = Task(level=Level.EPIC, title="Build tool system", tags=["tools"])
        self.board.create(epic)
        self.engine._route_work(epic, self.board)

        children = self.board.children_of(epic.id)
        self.assertGreaterEqual(len(children), 1)
        for child in children:
            self.assertIn("tools", child.tags)

        tools_infers = [c for c in self._infer_calls if c["use_tools"] is True]
        self.assertGreaterEqual(len(tools_infers), 1)

    def test_tools_tag_propagates_task_to_units(self):
        task = Task(level=Level.TASK, title="Implement search", tags=["tools"])
        self.board.create(task)
        self.engine._route_work(task, self.board)

        children = self.board.children_of(task.id)
        self.assertGreaterEqual(len(children), 1)
        for child in children:
            self.assertIn("tools", child.tags)

        tools_infers = [c for c in self._infer_calls if c["use_tools"] is True]
        self.assertGreaterEqual(len(tools_infers), 1)

    def test_no_tools_tag_does_not_propagate(self):
        epic = Task(level=Level.EPIC, title="Normal project")
        self.board.create(epic)
        self.engine._route_work(epic, self.board)

        children = self.board.children_of(epic.id)
        for child in children:
            self.assertNotIn("tools", child.tags)

        tools_infers = [c for c in self._infer_calls if c["use_tools"] is True]
        self.assertEqual(len(tools_infers), 0)

    def test_gamma_execute_passes_use_tools(self):
        unit = Task(level=Level.UNIT, title="Test file search", tags=["tools"])
        self.board.create(unit)
        self.engine._route_work(unit, self.board)

        self.assertGreaterEqual(len(self._infer_calls), 1)
        last = self._infer_calls[-1]
        self.assertEqual(last["level"], "unit")
        self.assertTrue(last["use_tools"])

    def test_gamma_execute_no_tools_default(self):
        unit = Task(level=Level.UNIT, title="Test file search")
        self.board.create(unit)
        self.engine._route_work(unit, self.board)

        self.assertGreaterEqual(len(self._infer_calls), 1)
        last = self._infer_calls[-1]
        self.assertFalse(last["use_tools"])


if __name__ == "__main__":
    unittest.main()

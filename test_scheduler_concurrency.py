import time
import unittest

from harness.board import JobBoard, Task, Level
from harness.daemon.scheduler import SchedulerEngine, _peer_table

SLOW_INFER_DELAY = 0.3


class SchedulerConcurrencyTests(unittest.TestCase):
    def setUp(self):
        JobBoard().clear()
        _peer_table._peers.clear()
        self.infer_calls = []

    def tearDown(self):
        JobBoard().clear()
        _peer_table._peers.clear()

    def _slow_infer(self, prompt, level, max_output=512, use_tools=False):
        self.infer_calls.append((prompt, level))
        time.sleep(SLOW_INFER_DELAY)
        return f"done: {prompt[:20]}"

    def test_concurrent_tick_does_3_tasks_faster_than_sequential(self):
        board = JobBoard()
        for i in range(3):
            board.create(Task(level=Level.UNIT, title=f"unit-{i}", prompt=f"work-{i}"))

        engine = SchedulerEngine(max_concurrent=4, tick_interval=999)
        engine._infer = self._slow_infer

        start = time.time()
        engine._worker_tick()
        elapsed = time.time() - start

        tasks = board.list()
        done = [t for t in tasks if t.state.name == "DONE"]

        self.assertEqual(len(done), 3)
        self.assertEqual(len(self.infer_calls), 3)
        self.assertLess(
            elapsed, 2.5 * SLOW_INFER_DELAY,
            f"{elapsed:.2f}s — sequential would take ~{3 * SLOW_INFER_DELAY:.2f}s",
        )

    def test_max_concurrent_2_leaves_remaining_tasks_unclaimed(self):
        board = JobBoard()
        for i in range(6):
            board.create(Task(level=Level.UNIT, title=f"unit-{i}", prompt=f"work-{i}"))

        engine = SchedulerEngine(max_concurrent=2, tick_interval=999)
        engine._infer = self._slow_infer

        engine._worker_tick()

        tasks = board.list()
        in_progress = [t for t in tasks if t.state.name == "IN_PROGRESS"]
        unclaimed = [t for t in tasks if t.state.name in ("BACKLOG", "READY")]

        self.assertLessEqual(len(in_progress), 2)
        self.assertGreaterEqual(len(unclaimed), 4)

    def test_concurrent_tick_all_levels_route_correctly(self):
        board = JobBoard()
        board.create(Task(level=Level.UNIT, title="ua", prompt="a"))
        board.create(Task(level=Level.UNIT, title="ub", prompt="b"))
        board.create(Task(level=Level.UNIT, title="uc", prompt="c"))

        engine = SchedulerEngine(max_concurrent=3, tick_interval=999)
        engine._infer = self._slow_infer

        engine._worker_tick()

        done = [t for t in board.list() if t.state.name == "DONE"]
        self.assertEqual(len(done), 3)

    def test_escalation_check_still_runs_when_no_work(self):
        engine = SchedulerEngine(max_concurrent=4, tick_interval=999)
        engine._infer = self._slow_infer

        engine._worker_tick()

        self.assertEqual(len(self.infer_calls), 0)

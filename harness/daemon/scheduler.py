import json
import os
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

from harness.config import load_config, MONSTER_HOME, MONSTER_BOARD_DIR
from harness.board import JobBoard, Task, Level, State
from harness.swarm.discovery import DiscoveryService
from harness.swarm.peer import PeerTable

SCHEDULER_DIR = MONSTER_HOME / "scheduler"
SCHEDULES_PATH = SCHEDULER_DIR / "schedules.json"
HISTORY_PATH = SCHEDULER_DIR / "history.json"

TRIGGER_TYPES = ("interval", "daily_at", "cron", "idle", "backlog", "condition", "window")
ACTION_TYPES = ("post_to_board", "trigger_alpha", "run_skill", "self_mod")
MISSED_BEHAVIOURS = ("skip", "catch_up", "fire_once")


class Schedule:
    def __init__(
        self,
        when: dict,
        action: dict,
        enabled: bool = True,
        title: str = "",
        missed_behaviour: str = "skip",
    ):
        self.id = uuid.uuid4().hex[:12]
        self.when = when
        self.action = action
        self.enabled = enabled
        self.title = title
        self.missed_behaviour = missed_behaviour
        self.last_fired: Optional[str] = None
        self.next_fire: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "when": self.when,
            "action": self.action,
            "enabled": self.enabled,
            "title": self.title,
            "missed_behaviour": self.missed_behaviour,
            "last_fired": self.last_fired,
            "next_fire": self.next_fire,
        }

    @staticmethod
    def from_dict(d: dict) -> "Schedule":
        s = Schedule(
            when=d["when"],
            action=d["action"],
            enabled=d.get("enabled", True),
            title=d.get("title", ""),
            missed_behaviour=d.get("missed_behaviour", "skip"),
        )
        s.id = d["id"]
        s.last_fired = d.get("last_fired")
        s.next_fire = d.get("next_fire")
        return s


def _ensure_scheduler_dir():
    SCHEDULER_DIR.mkdir(parents=True, exist_ok=True)


def _load_schedules() -> list[Schedule]:
    _ensure_scheduler_dir()
    if not SCHEDULES_PATH.exists():
        return []
    with open(SCHEDULES_PATH) as f:
        return [Schedule.from_dict(d) for d in json.load(f)]


def _save_schedules(schedules: list[Schedule]):
    _ensure_scheduler_dir()
    data = [s.to_dict() for s in schedules]
    with open(SCHEDULES_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _append_history(schedule_id: str, action: dict, result: str):
    _ensure_scheduler_dir()
    entry = {"schedule_id": schedule_id, "action": action, "result": result, "at": datetime.now(timezone.utc).isoformat()}
    history = []
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            history = json.load(f)
    history.append(entry)
    max_entries = 1000
    if len(history) > max_entries:
        history = history[-max_entries:]
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _calc_next_fire(when: dict, last_fired: Optional[str] = None) -> Optional[str]:
    ttype = when.get("type", "interval")
    now = datetime.now(timezone.utc)
    last = datetime.fromisoformat(last_fired) if last_fired else None

    if ttype == "interval":
        every = when.get("every") or when.get("interval", 3600)
        if last is None:
            return now.isoformat()
        return (last + timedelta(seconds=every)).isoformat()
    elif ttype == "daily_at":
        time_str = when.get("at", "02:00")
        hour, minute = map(int, time_str.split(":"))
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate.isoformat()
    elif ttype == "idle":
        delay = when.get("after_seconds", 3600)
        return (now + timedelta(seconds=delay)).isoformat()
    elif ttype == "backlog":
        delay = when.get("check_interval", 300)
        return (now + timedelta(seconds=delay)).isoformat()
    return (now + timedelta(hours=1)).isoformat()


def _check_idle(board: JobBoard, when: dict) -> bool:
    delay = when.get("after_seconds", 3600)
    tasks = board.list()
    active = [t for t in tasks if t.state in (State.BACKLOG, State.READY, State.IN_PROGRESS)]
    if active:
        return False
    mtimes = [p.stat().st_mtime for p in MONSTER_BOARD_DIR.glob("*.json")]
    if not mtimes:
        return True
    latest = max(mtimes)
    elapsed = time.time() - latest
    return elapsed >= delay


def _check_backlog(board: JobBoard, when: dict) -> bool:
    threshold = when.get("threshold", 5)
    tasks = board.list(state=State.BACKLOG)
    return len(tasks) >= threshold


_peer_table = PeerTable()


class SchedulerEngine:
    def __init__(self, tick_interval: int = 5, daemon_port: Optional[int] = None):
        self.tick_interval = tick_interval
        self._daemon_port = daemon_port
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._router: Any = None
        self._discovery: Optional[DiscoveryService] = None
        self._action_handlers: dict[str, Callable] = {
            "post_to_board": self._action_post_to_board,
        }

    @property
    def running(self) -> bool:
        return self._running

    def start(self):
        if self._running:
            return
        self._running = True
        cfg = load_config()
        if cfg.get("swarm", {}).get("enabled", True):
            port = self._daemon_port or cfg.get("daemon", {}).get("port", 8083)
            self._discovery = DiscoveryService(port, _peer_table)
            self._discovery.start()
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._discovery:
            self._discovery.stop()
            self._discovery = None
        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

    def add_schedule(self, schedule: Schedule):
        schedules = _load_schedules()
        schedule.next_fire = _calc_next_fire(schedule.when)
        schedules.append(schedule)
        _save_schedules(schedules)

    def remove_schedule(self, schedule_id: str) -> bool:
        schedules = _load_schedules()
        filtered = [s for s in schedules if s.id != schedule_id]
        if len(filtered) == len(schedules):
            return False
        _save_schedules(filtered)
        return True

    def list_schedules(self) -> list[Schedule]:
        return _load_schedules()

    def get_schedule(self, schedule_id: str) -> Optional[Schedule]:
        for s in self.list_schedules():
            if s.id.startswith(schedule_id):
                return s
        return None

    def history(self, schedule_id: Optional[str] = None, limit: int = 20) -> list[dict]:
        _ensure_scheduler_dir()
        if not HISTORY_PATH.exists():
            return []
        with open(HISTORY_PATH) as f:
            entries = json.load(f)
        if schedule_id:
            entries = [e for e in entries if e["schedule_id"].startswith(schedule_id)]
        return entries[-limit:]

    def _tick_loop(self):
        while self._running:
            try:
                self._tick()
                self._worker_tick()
            except Exception as e:
                print(f"γ|scheduler|tick_err|{e}", flush=True)
            time.sleep(self.tick_interval)

    def _worker_tick(self):
        board = JobBoard()
        for level, caste_tag in [(Level.UNIT, "γ"), (Level.TASK, "β"), (Level.EPIC, "α")]:
            t = board.claim(level, caste_tag=caste_tag)
            if t is None:
                continue
            print(f"γ|worker|claim|{t.id[:8]}|{level.value}|{t.title[:40]}", flush=True)
            try:
                result = self._execute(t)
                board.complete(t.id, result)
                print(f"γ|worker|done|{t.id[:8]}|{level.value}", flush=True)
            except Exception as e:
                print(f"γ|worker|err|{t.id[:8]}|{e}", flush=True)
                board.complete(t.id, f"error: {e}")
            return

    def _execute(self, task: Task) -> str:
        from harness.comms import Message, Caste, Action
        from harness.comms.router import Router
        if self._router is None:
            self._router = Router()
        msg = Message(
            caste={"epic": Caste.ALPHA, "task": Caste.BETA, "unit": Caste.GAMMA}[task.level.value],
            action=Action.INFER,
            payload={"prompt": task.prompt or task.title},
        )
        resp = self._router.dispatch(msg)
        payload = resp.payload
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload.get("result", "")

    def _tick(self):
        board = JobBoard()
        now = datetime.now(timezone.utc)
        changed = False
        for s in self.list_schedules():
            if not s.enabled or not s.next_fire:
                continue
            wtype = s.when.get("type", "interval")
            due = False
            if wtype in ("interval", "daily_at", "cron"):
                next_dt = datetime.fromisoformat(s.next_fire)
                if now >= next_dt:
                    due = True
            elif wtype == "idle":
                if _check_idle(board, s.when):
                    due = True
            elif wtype == "backlog":
                if _check_backlog(board, s.when):
                    due = True
            if not due:
                continue
            self._fire(s)
            s.last_fired = now.isoformat()
            s.next_fire = _calc_next_fire(s.when)
            changed = True
        if changed:
            _save_schedules(self.list_schedules())

    def _fire(self, schedule: Schedule):
        handler = self._action_handlers.get(schedule.action.get("type"))
        if handler is None:
            print(f"γ|scheduler|no_handler|{schedule.id}|{schedule.action.get('type')}", flush=True)
            return
        try:
            handler(schedule)
            print(f"γ|scheduler|fire|{schedule.id[:8]}|{schedule.action.get('type')}|{schedule.title}", flush=True)
            _append_history(schedule.id, schedule.action, "ok")
        except Exception as e:
            print(f"γ|scheduler|fire_err|{schedule.id[:8]}|{e}", flush=True)
            _append_history(schedule.id, schedule.action, f"err: {e}")

    def _action_post_to_board(self, schedule: Schedule):
        a = schedule.action
        board = JobBoard()
        level_str = a.get("level", "task")
        try:
            level = Level(level_str)
        except ValueError:
            level = Level.TASK
        t = Task(
            level=level,
            title=a.get("title", schedule.title or "scheduled task"),
            prompt=a.get("prompt", ""),
        )
        board.create(t)

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
                self._route_work(t, board)
            except Exception as e:
                print(f"γ|worker|err|{t.id[:8]}|{e}", flush=True)
                board.complete(t.id, f"error: {e}")
            return
        self._escalation_check(board)

    def _route_work(self, task: Task, board: JobBoard):
        level = task.level
        if level == Level.EPIC:
            self._alpha_breakdown(task, board)
        elif level == Level.TASK:
            if board.children_of(task.id):
                self._beta_review(task, board)
            else:
                self._beta_triage(task, board)
        elif level == Level.UNIT:
            self._gamma_execute(task, board)

    def _infer(self, prompt: str, level: str, max_output: int = 512) -> str:
        from harness.comms import Message, Caste, Action
        from harness.comms.router import Router
        if self._router is None:
            self._router = Router()
        caste_map = {"epic": Caste.ALPHA, "task": Caste.BETA, "unit": Caste.GAMMA}
        msg = Message(
            caste=caste_map[level],
            action=Action.INFER,
            payload={"prompt": prompt},
            token_budget={"input": 4096, "output": max_output},
        )
        resp = self._router.dispatch(msg)
        if "error" in resp.payload:
            raise RuntimeError(resp.payload["error"])
        return resp.payload.get("result", "")

    def infer(self, prompt: str, level: str, max_output: int = 512) -> str:
        return self._infer(prompt, level, max_output)

    def execute_task(self, title: str, prompt: str) -> dict:
        triage_result = self._infer(prompt or title, Level.TASK.value)
        steps = self._parse_bullets(triage_result)
        if not steps or len(steps) < 2:
            return {"task_result": triage_result, "units": []}
        units = []
        for step in steps:
            unit_result = self._infer(step, Level.UNIT.value)
            units.append({"title": step[:80], "result": unit_result})
        compiled = "\n\n".join(f"## {s}\n{u['result']}" for s, u in zip(steps, units))
        return {"task_result": compiled, "units": units}

    def _parse_bullets(self, text: str) -> list[str]:
        import re
        text = text.strip()
        text = re.sub(r"^(Here['´`]s|I['´`]ll|Let me|I need to|I should|The user|The request|Ok,? let).*\n\n", "", text, flags=re.MULTILINE)
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        bullets = []
        for line in lines:
            stripped = re.sub(r"^[\s*•\-‣⁃◦⦿⟹→]+|\d+[\.\)]\s*", "", line).strip()
            if not stripped or len(stripped) < 15:
                continue
            if re.match(r"^[A-Za-z]", stripped):
                bullets.append(stripped)
            elif bullets and len(stripped) > 10:
                bullets[-1] += " " + stripped
            elif len(stripped) > 25:
                bullets.append(stripped)
        if not bullets and len(text) > 20:
            bullets = [text]
        return bullets

    def _alpha_breakdown(self, task: Task, board: JobBoard):
        prompt = (
            f"You are breaking down a project request into sub-tasks.\n"
            f"Request: {task.prompt or task.title}\n\n"
            f"Output a numbered list of 3-6 specific, actionable sub-tasks. "
            f"Each sub-task should be a self-contained research or development task. "
            f"Output ONLY the numbered list, one per line."
        )
        result = self._infer(prompt, Level.EPIC.value, max_output=1024)
        bullets = self._parse_bullets(result)
        if not bullets or len(bullets) < 2:
            board.complete(task.id, result)
            print(f"γ|worker|alpha_done|{task.id[:8]}|direct|no bullets", flush=True)
            return
        for bullet in bullets:
            board.create(Task(level=Level.TASK, title=bullet[:80], prompt=bullet, parent_id=task.id))
        print(f"γ|worker|alpha|{task.id[:8]}|{len(bullets)} tasks", flush=True)

    def _beta_triage(self, task: Task, board: JobBoard):
        prompt = (
            f"Break this task into concrete research steps:\n"
            f"Task: {task.prompt or task.title}\n\n"
            f"Output a numbered list of 2-4 specific research or implementation steps. "
            f"Each step must be a single, actionable item that can be executed independently. "
            f"Output ONLY the numbered list, one per line."
        )
        result = self._infer(prompt, Level.TASK.value)
        steps = self._parse_bullets(result)
        if not steps or len(steps) < 2:
            board.complete(task.id, result)
            print(f"γ|worker|beta_triage_done|{task.id[:8]}|direct", flush=True)
            return
        for step in steps:
            board.create(Task(level=Level.UNIT, title=step[:80], prompt=step, parent_id=task.id))
        print(f"γ|worker|beta_triage|{task.id[:8]}|{len(steps)} units", flush=True)

    def _gamma_execute(self, task: Task, board: JobBoard):
        from harness.config import load_config
        cfg = load_config()
        delegation = cfg.get("swarm", {}).get("delegation", {})
        if delegation.get("enabled", True):
            max_load = delegation.get("max_load", 5)
            peer = self._select_peer("βγ", max_load)
            if peer and task.parent_id:
                parent = board.get(task.parent_id)
                if parent:
                    resp = self._delegate_to_peer(peer, "/v1/tasks/execute",
                                                  {"title": parent.title, "prompt": parent.prompt})
                    if resp and "task_result" in resp:
                        for child in board.children_of(parent.id):
                            board.delete(child.id)
                        board.complete(parent.id, resp["task_result"])
                        for u in resp.get("units", []):
                            child = Task(level=Level.UNIT, title=u["title"][:80],
                                         prompt=u["title"], parent_id=parent.id,
                                         state=State.DONE, result=u["result"])
                            board.create(child)
                        print(f"γ|worker|delegate|{peer}|{parent.id[:8]}|task", flush=True)
                        return
            peer = self._select_peer("γ", max_load)
            if peer:
                resp = self._delegate_to_peer(peer, "/v1/units/execute",
                                              {"prompt": task.prompt or task.title})
                if resp and "result" in resp:
                    board.complete(task.id, resp["result"])
                    print(f"γ|worker|delegate|{peer}|{task.id[:8]}|unit", flush=True)
                    return
            print(f"γ|worker|delegate_fallback|{task.id[:8]}|local", flush=True)
        result = self._infer(task.prompt or task.title, Level.UNIT.value)
        board.complete(task.id, result)
        print(f"γ|worker|gamma_done|{task.id[:8]}", flush=True)

    def _select_peer(self, required_castes: str, max_load: int) -> Optional[str]:
        candidates = [p for p in _peer_table.list_active()
                      if all(c in p.castes for c in required_castes)
                      and p.load < max_load]
        if not candidates:
            return None
        best = min(candidates, key=lambda p: p.load)
        return f"{best.addr}:{best.port}"

    def _delegate_to_peer(self, peer_key: str, path: str, body: dict) -> Optional[dict]:
        from harness.comms.remote import post_to_peer
        addr, port_str = peer_key.rsplit(":", 1)
        return post_to_peer(addr, int(port_str), path, body)

    def _compile_project_files(self, epic: Task, board: JobBoard, proj_dir: Path):
        import re
        summary = (epic.result or "")[:4000]
        prompt = (
            f"Generate the actual project files for this completed project.\n"
            f"Project: {epic.title}\n"
            f"Request: {epic.prompt}\n\n"
            f"Research summary:\n{summary}\n\n"
            f"Output each file as:\n"
            f"--- FILE: path/to/filename.ext\n"
            f"<file contents>\n"
            f"---\n"
            f"Generate real, working code. Include README.md. Output ONLY the file blocks."
        )
        try:
            result = self._infer(prompt, Level.EPIC.value, max_output=4096)
        except Exception as e:
            print(f"γ|worker|compile_err|{epic.id[:8]}|{e}", flush=True)
            return
        blocks = re.split(r'^---\s+FILE:\s+', result, flags=re.MULTILINE)
        written = 0
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            first_line = block.split('\n', 1)[0].strip()
            content = block.split('\n', 1)[1] if '\n' in block else ''
            if not first_line or not content:
                continue
            fpath = proj_dir / first_line
            fpath.parent.mkdir(parents=True, exist_ok=True)
            clean = content.strip()
            clean = re.sub(r'^```\w*\n', '', clean)
            clean = re.sub(r'\n```\s*$', '', clean)
            fpath.write_text(clean)
            written += 1
            print(f"γ|worker|compile_file|{fpath.name}", flush=True)
        if written > 0:
            print(f"γ|worker|compile_ok|{epic.id[:8]}|{written} files|{proj_dir}", flush=True)

    def _beta_review(self, task: Task, board: JobBoard):
        children = board.children_of(task.id)
        done = [c for c in children if c.state == State.DONE]
        if len(done) < len(children):
            return
        review_attempts = task.tags.count("reviewed") + 1
        if review_attempts >= 3:
            compiled = "\n\n".join(
                f"## {c.title}\n{c.result or '(no result)'}" for c in done
            )
            board.complete(task.id, compiled)
            print(f"γ|worker|beta_review_force|{task.id[:8]}|auto-accept after {review_attempts}", flush=True)
            return
        compiled = "\n\n".join(
            f"## {c.title}\n{c.result or '(no result)'}" for c in done
        )
        review_prompt = (
            f"Review these completed sub-tasks for the task: {task.title}\n\n"
            f"{compiled}\n\n"
            f"Start your response with exactly ACCEPT if all are satisfactory, or REJECT if any need rework."
        )
        review = self._infer(review_prompt, Level.TASK.value, max_output=512)
        upper = review.strip().upper()
        if upper.startswith("ACCEPT"):
            final = review[len("ACCEPT"):].strip().lstrip(":").strip()
            board.complete(task.id, final or compiled)
            print(f"γ|worker|beta_review_accept|{task.id[:8]}", flush=True)
        else:
            task.tags = task.tags + ["reviewed"]
            board.update(task)
            rejected = [c for c in done if c.title.split()[0].lower() in review.lower()]
            if not rejected:
                rejected = done[:1]
            for c in rejected:
                c.tags = c.tags + ["rework"]
                c.prompt = f"[Review feedback: {review[:200].strip()}]\n\n{c.prompt or c.title}"
                c.transition(State.BACKLOG)
                board.update(c)
            print(f"γ|worker|beta_review_reject|{task.id[:8]}|{len(rejected)} rework|attempt={review_attempts}", flush=True)

    def _escalation_check(self, board: JobBoard):
        for task in board.list(level=Level.TASK, state=State.IN_PROGRESS):
            children = board.children_of(task.id)
            if not children:
                continue
            done = [c for c in children if c.state == State.DONE]
            if len(done) == len(children):
                task.transition(State.READY)
                board.update(task)
                print(f"γ|worker|escalate|{task.id[:8]}|task→ready", flush=True)
        for task in board.list(level=Level.EPIC, state=State.IN_PROGRESS):
            children = board.children_of(task.id)
            if not children:
                continue
            done = [c for c in children if c.state == State.DONE]
            if len(done) == len(children):
                compiled = "\n\n".join(
                    f"## {c.title}\n{c.result or '(no result)'}" for c in done
                )
                board.complete(task.id, compiled)
                epic = board.get(task.id)
                if epic is None:
                    return
                from harness.projects import archive_epic
                proj_dir = archive_epic(epic, board)
                epic.tags.append(f"project:{proj_dir.name}")
                board.update(epic)
                self._compile_project_files(epic, board, proj_dir)
                print(f"γ|worker|escalate|{task.id[:8]}|epic→done|project={proj_dir.name}", flush=True)

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

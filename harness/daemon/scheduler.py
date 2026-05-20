import json
import os
import time
import uuid
import threading
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Optional

from harness.config import load_config, HUXLEY_HOME, HUXLEY_BOARD_DIR
from harness.board import JobBoard, Task, Level, State
from harness.swarm.discovery import DiscoveryService
from harness.swarm.peer import PeerTable

SCHEDULER_DIR = HUXLEY_HOME / "scheduler"
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
    mtimes = [p.stat().st_mtime for p in HUXLEY_BOARD_DIR.glob("*.json")]
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
        self._peer_failures: dict[str, float] = {}
        self._peer_selection_cursor: dict[str, str] = {}
        self._peer_activity: dict[str, dict[str, Any]] = {}
        self._peer_activity_lock = threading.Lock()
        self._peer_activity_ttl = 120
        self._inference_lock = threading.Lock()

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
        caste_map = {"epic": Caste.ALPHA, "task": Caste.BETA, "unit": Caste.GAMMA}
        msg = Message(
            caste=caste_map[level],
            action=Action.INFER,
            payload={"prompt": prompt},
            token_budget={"input": 4096, "output": max_output},
        )
        with self._inference_lock:
            if self._router is None:
                self._router = self._get_router()
            resp = self._router.dispatch(msg)
        if "error" in resp.payload:
            raise RuntimeError(resp.payload["error"])
        return resp.payload.get("result", "")

    def infer(self, prompt: str, level: str, max_output: int = 512) -> str:
        return self._infer(prompt, level, max_output)

    def _get_router(self):
        if self._router is None:
            from harness.comms.router import Router
            self._router = Router()
        return self._router

    def openai_models(self) -> list[dict]:
        return self._get_router().openai_models()

    def openai_chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_options: dict | None = None,
    ) -> dict:
        with self._inference_lock:
            return self._get_router().openai_chat_completion(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                request_options=request_options,
            )

    def openai_chat_completion_stream(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_options: dict | None = None,
    ):
        def stream():
            with self._inference_lock:
                yield from self._get_router().openai_chat_completion_stream(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    request_options=request_options,
                )

        return stream()

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

    def _begin_peer_activity(self, peer_key: str, task: Task, caste: str, contribution_level: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._peer_activity_lock:
            self._peer_activity[peer_key] = {
                "peer_key": peer_key,
                "task_id": task.id,
                "task_title": task.title,
                "task_level": task.level.value,
                "contribution_level": contribution_level,
                "caste": caste,
                "status": "active",
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
            }

    def _end_peer_activity(self, peer_key: str, status: str):
        now = datetime.now(timezone.utc).isoformat()
        with self._peer_activity_lock:
            activity = self._peer_activity.get(peer_key)
            if activity is None:
                return
            activity["status"] = status
            activity["updated_at"] = now
            activity["finished_at"] = now

    def peer_activity_snapshot(self) -> dict[str, dict]:
        cutoff = time.time() - self._peer_activity_ttl
        snapshot: dict[str, dict] = {}
        with self._peer_activity_lock:
            stale_keys = []
            for peer_key, activity in self._peer_activity.items():
                finished_at = activity.get("finished_at")
                if finished_at:
                    try:
                        finished_ts = datetime.fromisoformat(finished_at).timestamp()
                    except ValueError:
                        finished_ts = 0
                    if finished_ts and finished_ts < cutoff:
                        stale_keys.append(peer_key)
                        continue
                snapshot[peer_key] = dict(activity)
            for peer_key in stale_keys:
                del self._peer_activity[peer_key]
        return snapshot

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
            selection = delegation.get("selection", "round_robin")
            peers = self._select_peers("βγ", max_load, selection)
            if peers and task.parent_id:
                parent = board.get(task.parent_id)
                if parent:
                    for peer in peers:
                        self._begin_peer_activity(peer, parent, "βγ", Level.TASK.value)
                        resp = self._delegate_to_peer(
                            peer,
                            "/v1/tasks/execute",
                            {"title": parent.title, "prompt": parent.prompt},
                        )
                        if resp and "task_result" in resp:
                            self._end_peer_activity(peer, "completed")
                            self._mark_peer_selected("βγ", peer)
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
                        self._end_peer_activity(peer, "failed")
            for peer in self._select_peers("γ", max_load, selection):
                self._begin_peer_activity(peer, task, "γ", Level.UNIT.value)
                resp = self._delegate_to_peer(peer, "/v1/units/execute",
                                              {"prompt": task.prompt or task.title})
                if resp and "result" in resp:
                    self._end_peer_activity(peer, "completed")
                    self._mark_peer_selected("γ", peer)
                    board.complete(task.id, resp["result"])
                    print(f"γ|worker|delegate|{peer}|{task.id[:8]}|unit", flush=True)
                    return
                self._end_peer_activity(peer, "failed")
            print(f"γ|worker|delegate_fallback|{task.id[:8]}|local", flush=True)
        result = self._infer(task.prompt or task.title, Level.UNIT.value)
        board.complete(task.id, result)
        print(f"γ|worker|gamma_done|{task.id[:8]}", flush=True)

    def _select_peer(self, required_castes: str, max_load: int) -> Optional[str]:
        peers = self._select_peers(required_castes, max_load)
        return peers[0] if peers else None

    def _select_peers(
        self,
        required_castes: str,
        max_load: int,
        strategy: str = "round_robin",
    ) -> list[str]:
        candidates = [
            p for p in _peer_table.list_active()
            if all(c in p.castes for c in required_castes) and p.load < max_load
        ]
        if not candidates:
            return []
        if strategy != "round_robin":
            strategy = "round_robin"
        ordered = sorted(candidates, key=lambda p: p.key())
        if strategy == "round_robin":
            keys = [peer.key() for peer in ordered]
            last_key = self._peer_selection_cursor.get(required_castes)
            if last_key in keys:
                start = (keys.index(last_key) + 1) % len(keys)
                return keys[start:] + keys[:start]
            return keys
        return [peer.key() for peer in ordered]

    def _mark_peer_selected(self, required_castes: str, peer_key: str):
        self._peer_selection_cursor[required_castes] = peer_key

    def _delegate_to_peer(self, peer_key: str, path: str, body: dict) -> Optional[dict]:
        last_fail = self._peer_failures.get(peer_key, 0.0)
        if time.time() - last_fail < 60:
            return None
        from harness.comms.remote import post_to_peer
        addr, port_str = peer_key.rsplit(":", 1)
        result = post_to_peer(addr, int(port_str), path, body, timeout=120)
        if result is None:
            self._peer_failures[peer_key] = time.time()
        return result

    def _compile_project_files(self, epic: Task, board: JobBoard, proj_dir: Path):
        summary = (epic.result or "")[:4000]
        prompt = (
            f"Generate the actual project files for this completed project.\n"
            f"Project: {epic.title}\n"
            f"Request: {epic.prompt}\n\n"
            f"Research summary:\n{summary}\n\n"
            f"Produce one or more implementation suggestions.\n"
            f"Always wrap each suggestion as:\n"
            f"--- OPTION: short-name\n"
            f"--- FILE: path/to/filename.ext\n"
            f"<file contents>\n"
            f"... more FILE blocks ...\n"
            f"--- END OPTION\n\n"
            f"If there is only one good implementation, output a single OPTION block.\n"
            f"Keep each suggestion self-contained and namespace-safe.\n"
            f"Each suggestion must include README.md. "
            f"Output ONLY the OPTION and FILE blocks.\n"
        )
        try:
            result = self._infer(prompt, Level.EPIC.value, max_output=4096)
        except Exception as e:
            print(f"γ|worker|compile_err|{epic.id[:8]}|{e}", flush=True)
            return
        from harness.projects import write_compiled_suggestions
        suggestions = write_compiled_suggestions(proj_dir, result)
        written = 0
        for suggestion in suggestions:
            written += suggestion["file_count"]
            print(f"γ|worker|compile_suggestion|{suggestion['folder']}|{suggestion['file_count']} files", flush=True)
        if written > 0:
            print(f"γ|worker|compile_ok|{epic.id[:8]}|{len(suggestions)} suggestions|{written} files|{proj_dir}", flush=True)
        else:
            print(f"γ|worker|compile_empty|{epic.id[:8]}|no file blocks", flush=True)

    def _beta_review(self, task: Task, board: JobBoard):
        children = board.children_of(task.id)
        done = [c for c in children if c.state == State.DONE]
        if len(done) < len(children):
            return
        review_attempts = task.tags.count("reviewed") + 1
        refined_count = task.tags.count("refined")
        MAX_REVIEW = 5
        MAX_REFINE = 5
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
            return
        if review_attempts < MAX_REVIEW:
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
            return
        if refined_count >= MAX_REFINE:
            board.block(task.id, f"Failed after {review_attempts} reviews and {refined_count} refinements. Needs human intervention.")
            print(f"γ|worker|beta_blocked|{task.id[:8]}|{MAX_REFINE} refinements exhausted|needs human intervention", flush=True)
            return
        for c in children:
            board.delete(c.id)
        board.block(task.id)
        refine_prompt = (
            f"The previous decomposition of this task was rejected after {review_attempts} review attempts.\n"
            f"Latest review feedback: {review[:400].strip()}\n\n"
            f"Re-analyze this task and break it into narrower, more specific, and more clearly defined research steps:\n"
            f"Task: {task.prompt or task.title}\n\n"
            f"Output a numbered list of 2-4 concrete steps that are each independently achievable. "
            f"Each step must be more precisely scoped than the previous attempt. "
            f"Output ONLY the numbered list, one per line."
        )
        result = self._infer(refine_prompt, Level.TASK.value)
        steps = self._parse_bullets(result)
        if not steps or len(steps) < 2:
            steps = [f"{task.prompt or task.title} (step 1)"]
        for step in steps:
            board.create(Task(level=Level.UNIT, title=step[:80], prompt=step, parent_id=task.id))
        task.tags = [t for t in task.tags if t != "reviewed"] + ["refined"]
        task.transition(State.IN_PROGRESS)
        board.update(task)
        print(f"γ|worker|beta_refine|{task.id[:8]}|{len(steps)} units after {review_attempts} rejections|refined={refined_count + 1}", flush=True)

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

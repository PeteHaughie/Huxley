from __future__ import annotations
import sys
import argparse
from pathlib import Path

from harness import __version__
from harness.config import load_config, ensure_monster_dirs, MONSTER_MODELS_DIR, resolve_path
from harness.memory import SessionStore
from harness.comms import Message, Caste, Action, ContextHint
from harness.comms.router import Router
from harness.skill.registry import SkillRegistry
from harness.cloud.router import CloudRouter
from harness.selfmod.introspect import module_map, api_surface
from harness.selfmod.patcher import Patcher
from harness.board import JobBoard, Task, Level as BLevel, State as BState
from harness.board.serve import serve as board_serve
from harness.daemon.lifecycle import start_daemon, stop_daemon, daemon_status, is_running, DAEMON_PORT


def cmd_init(args):
    ensure_monster_dirs()
    sid, work_dir = SessionStore.resolve_session(args.dir)
    dot_monster = work_dir / ".monster"
    target = Path.home() / ".monster" / "sessions" / sid
    if not dot_monster.exists():
        dot_monster.symlink_to(target, target_is_directory=True)
    print(f"γ|init|{sid[:12]}|{work_dir}", flush=True)


def cmd_session(args):
    sid, work_dir = SessionStore.resolve_session(args.dir)
    print(f"γ|session|{sid[:12]}|{work_dir}", flush=True)


def cmd_skills(args):
    reg = SkillRegistry()
    reg.refresh()
    skills = reg.all()
    if not skills:
        print("γ|skills|none", flush=True)
        return
    for s in skills:
        print(f"γ|skill|{s['name']}|{s['description'][:80]}", flush=True)


def cmd_infer(args):
    router = Router()
    msg = Message(
        caste=Caste.from_alias(args.caste),
        action=Action.INFER,
        payload={"prompt": args.prompt},
        context_hint=ContextHint(args.context),
    )
    resp = router.dispatch(msg)
    payload = resp.payload
    if "error" in payload:
        print(f"γ|error|{payload['error']}", flush=True)
    else:
        print(payload.get("result", ""), flush=True)


def cmd_api(args):
    apis = api_surface()
    for a in apis:
        print(f"γ|api|{a['module']}|{a['name']}|{a['kind']}|{a['lineno']}", flush=True)


def cmd_modules(args):
    mm = module_map()
    for modname, info in mm.items():
        print(f"γ|mod|{modname}|{info.get('file', '')}", flush=True)


def cmd_cloud(args):
    cr = CloudRouter()
    msg = Message(
        caste=Caste.BETA,
        action=Action.INFER,
        payload={"prompt": args.prompt},
    )
    resp = cr.route(msg)
    payload = resp.payload
    if "error" in payload:
        print(f"γ|cloud|err|{payload['error']}", flush=True)
    else:
        print(payload.get("result", ""), flush=True)


def cmd_patch(args):
    patcher = Patcher()
    content = Path(args.file).read_text()
    result = patcher.apply(args.file, content, dry_run=args.dry_run)
    print(f"γ|patch|{'ok' if result['ok'] else 'err'}|{result.get('patch_id', '')}", flush=True)
    if "diff" in result:
        print(result["diff"], flush=True)


def cmd_models(args):
    mp = Path(resolve_path("~/.monster/models"))
    if not mp.exists():
        print("γ|models|none", flush=True)
        return
    ggufs = list(mp.glob("*.gguf"))
    if not ggufs:
        print("γ|models|empty", flush=True)
        return
    for m in sorted(ggufs):
        size = m.stat().st_size
        gb = size / (1024**3)
        print(f"γ|model|{m.name}|{gb:.1f}G", flush=True)


# -- daemon commands --

def cmd_daemon(args):
    if args.daemon_cmd == "start":
        ok = start_daemon()
        if ok:
            print("γ|monsterd|start|ok", flush=True)
        else:
            print("γ|monsterd|start|already_running" if is_running() else "γ|monsterd|start|fail", flush=True)
    elif args.daemon_cmd == "stop":
        ok = stop_daemon()
        print("γ|monsterd|stop|ok" if ok else "γ|monsterd|stop|not_running", flush=True)
    elif args.daemon_cmd == "status":
        st = daemon_status()
        if st["running"]:
            print(f"γ|monsterd|running|scheduler={st.get('scheduler_running', False)}|schedules={st.get('schedules', 0)}", flush=True)
        else:
            print("γ|monsterd|stopped", flush=True)


# -- schedule commands --

def _daemon_api(method: str, path: str, body: dict | None = None) -> dict | list | None:
    import urllib.request, urllib.error, json
    url = f"http://127.0.0.1:{DAEMON_PORT}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        return None


def cmd_schedule(args):
    if args.sched_cmd == "list":
        data = _daemon_api("GET", "/v1/schedules")
        if data is None:
            print("γ|schedule|err|daemon not running", flush=True)
            return
        if not data:
            print("γ|schedule|empty", flush=True)
            return
        for s in data:
            icon = "●" if s.get("enabled") else "○"
            wtype = s.get("when", {}).get("type", "?")
            print(f"γ|schedule|{icon}|{s['id'][:8]}|{wtype:<10}|{s.get('title','-')}", flush=True)
    elif args.sched_cmd == "add":
        when_val = args.every if args.when_type == "interval" else args.at
        when_key = "every" if args.when_type == "interval" else "at"
        body = {
            "when": {"type": args.when_type, when_key: when_val},
            "action": {"type": "post_to_board", "level": args.level or "task", "title": args.title, "prompt": args.prompt or ""},
            "title": args.title,
        }
        data = _daemon_api("POST", "/v1/schedules", body)
        if data is None:
            print("γ|schedule|err|daemon not running", flush=True)
            return
        print(f"γ|schedule|add|{data['id'][:12]}|{args.when_type}|{args.title}", flush=True)
    elif args.sched_cmd == "remove":
        data = _daemon_api("DELETE", f"/v1/schedules/{args.schedule_id}")
        if data is None:
            print("γ|schedule|err|daemon not running", flush=True)
            return
        print(f"γ|schedule|remove|{'ok' if data.get('status') == 'removed' else 'not_found'}", flush=True)
    elif args.sched_cmd == "history":
        sid = getattr(args, "schedule_id", None)
        q = f"?id={sid}" if sid else ""
        data = _daemon_api("GET", f"/v1/schedule/history{q}")
        if data is None:
            print("γ|schedule|err|daemon not running", flush=True)
            return
        if not data:
            print("γ|schedule|history|empty", flush=True)
            return
        for e in data[-10:]:
            print(f"γ|schedule|history|{e['schedule_id'][:8]}|{e['action'].get('type','?')}|{e.get('result','?')}|{e.get('at','')[:19]}", flush=True)


# -- board commands --

def cmd_board(args):
    board = JobBoard()
    if args.board_cmd == "list":
        _board_list(board, args)
    elif args.board_cmd == "post":
        _board_post(board, args)
    elif args.board_cmd == "show":
        _board_show(board, args)
    elif args.board_cmd == "claim":
        _board_claim(board, args)
    elif args.board_cmd == "complete":
        _board_complete(board, args)
    elif args.board_cmd == "serve":
        board_serve(port=args.port)


def _board_list(board: JobBoard, args):
    level = BLevel(args.level) if args.level else None
    state = BState(args.state) if args.state else None
    tasks = board.list(level=level, state=state)
    if not tasks:
        print("γ|board|empty", flush=True)
        return
    for t in tasks:
        tag = f"{t.level.value[0].upper()}"
        icon = {"backlog": "○", "ready": "◉", "in_progress": "◎", "blocked": "⊘", "done": "●", "archived": "·"}.get(t.state.value, "○")
        print(f"γ|board|{icon}|{tag}|{t.id[:8]}|{t.state.value:<12}|{t.caste or '-':<4}|{t.title[:60]}", flush=True)


def _board_post(board: JobBoard, args):
    level = BLevel(args.level)
    t = Task(level=level, title=args.title, prompt=args.prompt or args.title)
    board.create(t)
    print(f"γ|board|post|{t.id[:12]}|{t.level.value}|{t.title}", flush=True)


def _board_show(board: JobBoard, args):
    t = board.get(args.task_id)
    if t is None:
        print(f"γ|board|not_found|{args.task_id}", flush=True)
        return
    children = board.children_of(t.id)
    print(f"id:      {t.id}", flush=True)
    print(f"level:   {t.level.value}", flush=True)
    print(f"state:   {t.state.value}", flush=True)
    print(f"caste:   {t.caste or '-'}", flush=True)
    print(f"title:   {t.title}", flush=True)
    print(f"prompt:  {t.prompt}", flush=True)
    if t.result:
        print(f"result:  {t.result[:200]}", flush=True)
    print(f"created: {t.created}", flush=True)
    print(f"updated: {t.updated}", flush=True)
    if children:
        print(f"children ({len(children)}):", flush=True)
        for c in children:
            print(f"  {c.id[:8]} {c.state.value} {c.title[:50]}", flush=True)


def _board_claim(board: JobBoard, args):
    level = BLevel(args.level)
    t = board.claim(level, caste_tag=args.caste)
    if t is None:
        print(f"γ|board|no_tasks|{args.level}", flush=True)
        return
    print(f"γ|board|claimed|{t.id[:12]}|{t.level.value}|{t.title}", flush=True)
    if t.prompt:
        print(f"prompt: {t.prompt}", flush=True)


def _board_complete(board: JobBoard, args):
    result = args.result or ""
    t = board.complete(args.task_id, result)
    if t is None:
        print(f"γ|board|cannot_complete|{args.task_id}", flush=True)
        return
    print(f"γ|board|done|{t.id[:12]}|{t.level.value}|{t.title}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        prog="monster",
        description="1BitMonster — hyper-efficient local-first AI agent harness",
    )
    parser.add_argument("--version", action="version", version=__version__)

    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Init .monster session in directory")
    init_p.add_argument("--dir", default=None, help="Target directory")

    session_p = sub.add_parser("session", help="Show current session info")
    session_p.add_argument("--dir", default=None, help="Target directory")

    skills_p = sub.add_parser("skills", help="List available skills")
    skills_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    infer_p = sub.add_parser("infer", help="Run inference on a caste")
    infer_p.add_argument("caste", choices=["α", "β", "γ", "a", "b", "g", "alpha", "beta", "gamma"], help="Caste to infer from (a/b/g or α/β/γ)")
    infer_p.add_argument("prompt", help="Prompt text")
    infer_p.add_argument("--context", choices=["caveman", "normal", "full"], default="caveman")
    infer_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    api_p = sub.add_parser("api", help="List harness API surface")
    api_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    modules_p = sub.add_parser("modules", help="List all harness modules")
    modules_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    cloud_p = sub.add_parser("cloud", help="Route prompt via cloud endpoint")
    cloud_p.add_argument("prompt", help="Prompt text")
    cloud_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    patch_p = sub.add_parser("patch", help="Apply a self-mod patch (dry-run by default)")
    patch_p.add_argument("file", help="Target Python file")
    patch_p.add_argument("--apply", dest="dry_run", action="store_false", help="Apply the patch")
    patch_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    models_p = sub.add_parser("models", help="List models in ~/.monster/models/")
    models_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    board_p = sub.add_parser("board", help="Kanban job board operations")
    board_sub = board_p.add_subparsers(dest="board_cmd")

    board_list_p = board_sub.add_parser("list", help="List board tasks")
    board_list_p.add_argument("--level", choices=["epic", "task", "unit"], help="Filter by level")
    board_list_p.add_argument("--state", choices=["backlog", "ready", "in_progress", "blocked", "done", "archived"], help="Filter by state")

    board_post_p = board_sub.add_parser("post", help="Post a new task to the board")
    board_post_p.add_argument("level", choices=["epic", "task", "unit"], help="Task level")
    board_post_p.add_argument("title", help="Task title")
    board_post_p.add_argument("--prompt", help="Task prompt (defaults to title)")

    board_show_p = board_sub.add_parser("show", help="Show task details")
    board_show_p.add_argument("task_id", help="Task ID")

    board_claim_p = board_sub.add_parser("claim", help="Claim next available task")
    board_claim_p.add_argument("level", choices=["epic", "task", "unit"], help="Level to claim from")
    board_claim_p.add_argument("--caste", help="Caste tag to mark on task")

    board_complete_p = board_sub.add_parser("complete", help="Mark task as done")
    board_complete_p.add_argument("task_id", help="Task ID")
    board_complete_p.add_argument("--result", help="Result text")

    board_serve_p = board_sub.add_parser("serve", help="Start Kanban web UI")
    board_serve_p.add_argument("--port", type=int, default=8080, help="HTTP port (default 8080)")

    daemon_p = sub.add_parser("daemon", help="Control the monster background daemon")
    daemon_sub = daemon_p.add_subparsers(dest="daemon_cmd")
    daemon_sub.add_parser("start", help="Start monsterd in background")
    daemon_sub.add_parser("stop", help="Stop monsterd")
    daemon_sub.add_parser("status", help="Check if monsterd is running")

    sched_p = sub.add_parser("schedule", help="Manage scheduled tasks")
    sched_sub = sched_p.add_subparsers(dest="sched_cmd")
    sched_sub.add_parser("list", help="List all schedules")
    sched_add_p = sched_sub.add_parser("add", help="Add a schedule")
    sched_add_p.add_argument("when_type", choices=["interval", "daily_at"], help="Trigger type")
    sched_add_p.add_argument("title", help="Schedule title / board task title")
    sched_add_p.add_argument("--every", type=int, default=3600, help="Seconds between ticks (for interval)")
    sched_add_p.add_argument("--at", default="02:00", help="HH:MM time (for daily_at)")
    sched_add_p.add_argument("--level", choices=["epic", "task", "unit"], default="task", help="Board task level")
    sched_add_p.add_argument("--prompt", help="Task prompt text")
    sched_add_p.add_argument("--action", choices=["post_to_board"], default="post_to_board", help="Action type")
    sched_rm_p = sched_sub.add_parser("remove", help="Remove a schedule")
    sched_rm_p.add_argument("schedule_id", help="Schedule ID")
    sched_hist_p = sched_sub.add_parser("history", help="Show schedule firing history")
    sched_hist_p.add_argument("--id", dest="schedule_id", help="Filter by schedule ID")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init(args)
    elif args.command == "session":
        cmd_session(args)
    elif args.command == "skills":
        cmd_skills(args)
    elif args.command == "infer":
        cmd_infer(args)
    elif args.command == "api":
        cmd_api(args)
    elif args.command == "modules":
        cmd_modules(args)
    elif args.command == "cloud":
        cmd_cloud(args)
    elif args.command == "patch":
        cmd_patch(args)
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "board":
        cmd_board(args)
    elif args.command == "daemon":
        cmd_daemon(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    else:
        parser.print_help()

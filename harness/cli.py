from __future__ import annotations
import sys
import argparse
from pathlib import Path

from harness import __version__
from harness.config import load_config, ensure_huxley_dirs, HUXLEY_MODELS_DIR, resolve_path
from harness.memory import SessionStore
from harness.comms import Message, Caste, Action, ContextHint
from harness.comms.router import Router
from harness.skill.registry import SkillRegistry
from harness.selfmod.introspect import module_map, api_surface
from harness.selfmod.patcher import Patcher, PATCH_DIR
from harness.board import JobBoard, Task, Level as BLevel, State as BState
from harness.board.serve import serve as board_serve
from harness.board.lifecycle import start_boardd, stop_boardd, boardd_status
from harness.daemon.lifecycle import start_daemon, stop_daemon, daemon_status, is_running, DAEMON_PORT


def cmd_init(args):
    ensure_huxley_dirs()
    sid, work_dir = SessionStore.resolve_session(args.dir)
    dot_huxley = work_dir / ".huxley"
    target = Path.home() / ".huxley" / "sessions" / sid
    if not dot_huxley.exists():
        dot_huxley.symlink_to(target, target_is_directory=True)
    print(f"γ|init|{sid[:12]}|{work_dir}", flush=True)


def cmd_session(args):
    sid, work_dir = SessionStore.resolve_session(args.dir)
    print(f"γ|session|{sid[:12]}|{work_dir}", flush=True)


def cmd_compact(args):
    sid, work_dir = SessionStore.resolve_session(args.dir)
    caste_tag = Caste.from_alias(args.caste or "b").name.lower()
    from harness.memory.persistence import SessionJournal
    journal = SessionJournal(sid, caste_tag)
    if not journal.needs_compaction():
        print(f"γ|compact|skipped|{journal.entry_count()} entries < 30", flush=True)
        return
    text = journal.build_compactable_text()
    if text is None:
        print("γ|compact|skipped|too few entries", flush=True)
        return
    cprompt = ("Condense this conversation into one paragraph preserving "
               "key facts, decisions, results, and current state. "
               "Drop greetings, pleasantries, and step-by-step reasoning:\n\n" + text)
    router = Router()
    msg = Message(
        caste=Caste.from_alias(args.caste or "b"),
        action=Action.INFER,
        payload={"prompt": cprompt},
        context_hint=ContextHint.FULL,
        session=sid,
    )
    resp = router.dispatch(msg)
    payload = resp.payload
    if "error" in payload:
        print(f"γ|compact|err|{payload['error']}", flush=True)
        return
    summary = payload.get("result", "")
    if not summary:
        print(f"γ|compact|err|empty summary|{journal.entry_count()} entries", flush=True)
        return
    count = journal.entry_count()
    if count > 30:
        journal.compact(summary)
        print(f"γ|compact|ok|{journal.entry_count()} entries", flush=True)
    else:
        print(f"γ|compact|ok|{count} entries (auto-compacted during infer)", flush=True)


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
    sid, work_dir = SessionStore.resolve_session(args.dir)
    msg = Message(
        caste=Caste.from_alias(args.caste),
        action=Action.INFER,
        payload={"prompt": args.prompt},
        context_hint=ContextHint(args.context),
        session=sid,
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
    from harness.cloud.router import CloudRouter
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
    if getattr(args, "list", False) or getattr(args, "rollback", None):
        if args.file or getattr(args, "review", False) or not args.dry_run:
            print("γ|patch|err|--list/--rollback cannot be combined with --apply, --review, or <file>", flush=True)
            return 1
    # list known patches
    if getattr(args, "list", False):
        if not PATCH_DIR.exists():
            print("γ|patch|list|empty", flush=True)
            return 0
        baks = sorted(PATCH_DIR.glob("*_*.bak"))
        if not baks:
            print("γ|patch|list|empty", flush=True)
            return 0
        for b in baks:
            pid = b.name.split("_")[0]
            meta = PATCH_DIR / f"{pid}.meta"
            if meta.exists():
                fname = "_".join(b.name.split("_")[1:])
                if fname.endswith('.bak'):
                    fname = fname[:-4]
                print(f"γ|patch|entry|{pid}|{fname}|{b.stat().st_mtime}", flush=True)
            else:
                print(f"γ|patch|entry_legacy|{pid}|{b.stat().st_mtime}", flush=True)
        return 0

    # rollback
    if getattr(args, "rollback", None):
        patcher = Patcher()
        ok = patcher.rollback(args.rollback)
        print(f"γ|patch|rollback|{'ok' if ok else 'not_found'}|{args.rollback}", flush=True)
        return 0 if ok else 1

    patcher = Patcher()

    # normal patch flow: read new content from stdin, validate file argument
    if not args.file:
        print("γ|patch|err|file argument required", flush=True)
        return 1
    if sys.stdin.isatty():
        print("γ|patch|err|pipe new content via stdin (e.g., echo 'new_code()' | huxley patch file.py)", flush=True)
        return 1
    content = sys.stdin.read()
    if not content.strip():
        print("γ|patch|err|empty content", flush=True)
        return 1
    # validate .py targets before applying (skip for dry-run, only block on apply)
    if not args.dry_run and args.file.endswith(".py"):
        from harness.selfmod.validator import validate_patch
        val = validate_patch(args.file, content)
        if not val.get("ok"):
            for e in val.get("errors", []):
                print(f"γ|patch|err|validate|{e}", flush=True)
            return 1
    result = patcher.apply(args.file, content, dry_run=args.dry_run)
    ok = result.get("ok", False)
    err = result.get("error", "")
    status = "ok" if ok else "err"
    if ok and args.dry_run and result.get("patch_id"):
        print("γ|patch|ok|preview", flush=True)
    else:
        print(f"γ|patch|{status}|{result.get('patch_id', '')}", flush=True)
    if err:
        print(f"γ|patch|error|{err}", flush=True)
        return 1
    if "diff" in result and result.get("diff"):
        print(result["diff"], flush=True)

    # optionally post to board for human review
    if ok and result.get("changed") and getattr(args, "review", False):
        from harness.selfmod.validator import validate_patch
        board = JobBoard()
        pid = result.get("patch_id", "")
        title = f"Review patch {pid} -> {Path(args.file).name}"
        difftext = result.get("diff", f"Patch {pid} for {args.file}")
        report_lines = []
        if args.file.endswith(".py"):
            val = validate_patch(args.file, content)
            if val.get("ok"):
                report_lines.append("Validator: OK")
            else:
                for e in val.get("errors", []):
                    report_lines.append(f"ERROR: {e}")
            for w in val.get("warnings", []):
                report_lines.append(f"WARN: {w}")
        else:
            report_lines.append("Validator: skipped (non-Python file)")
        prompt = difftext + "\n\n" + "\n".join(report_lines)
        t = Task(level=BLevel.TASK, title=title, prompt=prompt)
        board.create(t)
        print(f"γ|patch|posted|{t.id[:12]}|{title}", flush=True)
    return 0


def cmd_models(args):
    mp = Path(resolve_path("~/.huxley/models"))
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
            print("γ|huxleyd|start|ok", flush=True)
        else:
            print("γ|huxleyd|start|already_running" if is_running() else "γ|huxleyd|start|fail", flush=True)
    elif args.daemon_cmd == "stop":
        ok = stop_daemon()
        print("γ|huxleyd|stop|ok" if ok else "γ|huxleyd|stop|not_running", flush=True)
    elif args.daemon_cmd == "status":
        st = daemon_status()
        if st["running"]:
            api = st.get("openai_api", {})
            models = ",".join(api.get("models", [])) or "none"
            print(
                f"γ|huxleyd|running|scheduler={st.get('scheduler_running', False)}|"
                f"schedules={st.get('schedules', 0)}|openai={api.get('url', f'http://127.0.0.1:{DAEMON_PORT}/v1')}|"
                f"models={models}",
                flush=True,
            )
        else:
            print("γ|huxleyd|stopped", flush=True)


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


# -- swarm commands --

def _swarm_api(path: str) -> dict | list | None:
    import urllib.request, urllib.error, json
    url = f"http://127.0.0.1:{DAEMON_PORT}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, ConnectionError, OSError):
        return None


def cmd_swarm(args):
    if args.swarm_cmd == "peers":
        data = _swarm_api("/v1/swarm/peers")
        if data is None:
            print("γ|swarm|err|daemon not running", flush=True)
            return
        if not data:
            print("γ|swarm|peers|none", flush=True)
            return
        for p in data:
            icon = "○" if p.get("lost") else "●"
            print(f"γ|swarm|peer|{icon}|{p['hostname']:<20}|:{p['port']}|castes={p['castes']}|load={p['load']}|age={p['age']}s{' LOST' if p.get('lost') else ''}", flush=True)
    elif args.swarm_cmd == "status":
        data = _swarm_api("/v1/swarm/status")
        if data is None:
            print("γ|swarm|err|daemon not running", flush=True)
            return
        print(f"γ|swarm|status|total={data.get('peers',0)}|active={data.get('active_peers',0)}", flush=True)
    elif args.swarm_cmd == "test":
        from harness.swarm.discovery import test_multicast, _lan_ips, MULTICAST_PORT
        import socket
        r = test_multicast()
        hostname = socket.gethostname()
        print(f"γ|swarm|test|hostname={hostname}", flush=True)
        ips = _lan_ips()
        for ip in ips:
            print(f"γ|swarm|test|iface|{ip}", flush=True)
        if r.get("error"):
            print(f"γ|swarm|test|error={r['error']}", flush=True)
        else:
            print(f"γ|swarm|test|send={r['send_ok']}|recv={r['recv_ok']}|loopback={r['loopback']}", flush=True)
        fw = r.get("firewall")
        if fw:
            print(f"γ|swarm|test|firewall|{fw}", flush=True)
        if not r.get("loopback"):
            print(f"γ|swarm|test|hint|no loopback — packets not reaching self", flush=True)
            print(f"γ|swarm|test|hint|firewall or NECP blocking UDP on port {MULTICAST_PORT}", flush=True)
    elif args.swarm_cmd == "announce":
        from harness.swarm.discovery import send_manual_announce, _lan_ips
        import socket
        port = args.port if args.port is not None else 8083
        send_manual_announce(socket.gethostname(), port, castes=args.castes or "αβγ")
        print(f"γ|swarm|announce|done|ifaces={_lan_ips()}:{port}", flush=True)


def cmd_project(args):
    if args.proj_cmd == "list":
        from harness.projects import list_projects
        projects = list_projects()
        if not projects:
            print("γ|project|list|none", flush=True)
            return
        for p in projects:
            print(f"γ|project|{p['dir']}|{p['title'][:50]}|tasks={p['task_count']}|suggestions={p.get('suggestion_count', 0)}|result={p['result_len']}b", flush=True)
    elif args.proj_cmd == "show":
        from harness.projects import get_project
        p = get_project(args.name)
        if p is None:
            print(f"γ|project|not_found|{args.name}", flush=True)
            return
        print(f"γ|project|title|{p['title']}", flush=True)
        print(f"γ|project|dir|{p['dir']}", flush=True)
        print(f"γ|project|prompt|{p.get('prompt','')[:100]}", flush=True)
        print(f"γ|project|summary_len|{p['result_len']}b", flush=True)
        for suggestion in p.get("suggestions", []):
            print(
                f"γ|project|suggestion|{suggestion['folder']}|files={suggestion['file_count']}|{suggestion['path']}",
                flush=True,
            )
        for t in p.get("tasks", []):
            icon = "●" if t["unit_count"] > 0 else "○"
            print(f"γ|project|task|{icon}|{t['id']}|{t['title'][:60]}|units={t['unit_count']}", flush=True)
            for u in t.get("units", []):
                print(f"γ|project|unit|  |{u['id']}|{u['title'][:50]}", flush=True)
    elif args.proj_cmd == "path":
        from harness.projects import get_project
        p = get_project(args.name)
        if p is None:
            print(f"γ|project|not_found|{args.name}", flush=True)
            return
        print(p["path"], flush=True)
    elif args.proj_cmd == "summary":
        from harness.projects import get_project
        p = get_project(args.name)
        if p is None:
            print(f"γ|project|not_found|{args.name}", flush=True)
            return
        print(p.get("summary", "(no summary)"), flush=True)
    elif args.proj_cmd == "materialize":
        from harness.projects import materialize_project
        try:
            result = materialize_project(args.name, destination=args.into, overwrite=args.force)
        except (FileExistsError, ValueError) as e:
            print(f"γ|project|materialize|err|{e}", flush=True)
            return
        if result is None:
            print(f"γ|project|not_found|{args.name}", flush=True)
            return
        print(f"γ|project|materialize|root|{result['root']}", flush=True)
        for suggestion in result["suggestions"]:
            print(
                f"γ|project|materialize|suggestion|{suggestion['folder']}|files={suggestion['file_count']}|{suggestion['path']}",
                flush=True,
            )


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
    elif args.board_cmd == "delete":
        _board_delete(board, args)
    elif args.board_cmd == "serve":
        if args.serve_cmd == "start":
            ok = start_boardd(port=args.port)
            if not ok:
                st = boardd_status()
                print(f"γ|boardd|start|already_running|:{st.get('port', '?')}" if st["running"] else "γ|boardd|start|fail", flush=True)
        elif args.serve_cmd == "stop":
            ok = stop_boardd()
            print("γ|boardd|stop|ok" if ok else "γ|boardd|stop|not_running", flush=True)
        elif args.serve_cmd == "status":
            st = boardd_status()
            if st["running"]:
                print(f"γ|boardd|running|:{st.get('port', '?')}|pid={st.get('pid', '?')}", flush=True)
            else:
                print("γ|boardd|stopped", flush=True)


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


def _board_delete(board: JobBoard, args):
    if board.delete(args.task_id):
        print(f"γ|board|deleted|{args.task_id[:12]}", flush=True)
    else:
        print(f"γ|board|not_found|{args.task_id}", flush=True)


def main():
    parser = argparse.ArgumentParser(
        prog="huxley",
        description="Huxley — hyper-efficient local-first AI agent harness",
    )
    parser.add_argument("--version", action="version", version=__version__)

    sub = parser.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Init .huxley session in directory")
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

    patch_p = sub.add_parser("patch", help="Self-mod patch (pipe new content via stdin, dry-run by default)")
    patch_p.add_argument("file", nargs='?', help="Target file to patch")
    patch_p.add_argument("--apply", dest="dry_run", action="store_false", help="Apply the patch")
    patch_p.add_argument("--review", action="store_true", help="Post patch diff to board for review")
    patch_group = patch_p.add_mutually_exclusive_group()
    patch_group.add_argument("--list", action="store_true", help="List known patches/backups")
    patch_group.add_argument("--rollback", help="Rollback patch by patch id")
    patch_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    models_p = sub.add_parser("models", help="List models in ~/.huxley/models/")
    models_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

    compact_p = sub.add_parser("compact", help="Compact session journal via summarization")
    compact_p.add_argument("--caste", choices=["a", "b", "g", "alpha", "beta", "gamma"], default="b", help="Caste to summarize with (default beta)")
    compact_p.add_argument("--dir", default=None, help=argparse.SUPPRESS)

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

    board_delete_p = board_sub.add_parser("delete", help="Delete a task from the board")
    board_delete_p.add_argument("task_id", help="Task ID (full UUID or prefix)")

    board_serve_p = board_sub.add_parser("serve", help="Manage Kanban web UI daemon")
    board_serve_sub = board_serve_p.add_subparsers(dest="serve_cmd")
    board_serve_start_p = board_serve_sub.add_parser("start", help="Start board daemon in background")
    board_serve_start_p.add_argument("--port", type=int, default=8080, help="HTTP port (default 8080)")
    board_serve_sub.add_parser("stop", help="Stop board daemon")
    board_serve_sub.add_parser("status", help="Check if board daemon is running")

    daemon_p = sub.add_parser("daemon", help="Control the huxley background daemon")
    daemon_sub = daemon_p.add_subparsers(dest="daemon_cmd")
    daemon_sub.add_parser("start", help="Start huxleyd in background")
    daemon_sub.add_parser("stop", help="Stop huxleyd")
    daemon_sub.add_parser("status", help="Check if huxleyd is running")

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

    swarm_p = sub.add_parser("swarm", help="LAN peer discovery and swarm status")
    swarm_sub = swarm_p.add_subparsers(dest="swarm_cmd")
    swarm_sub.add_parser("peers", help="List known LAN peers")
    swarm_sub.add_parser("status", help="Show swarm status")
    swarm_sub.add_parser("test", help="Test multicast/broadcast connectivity")
    announce_p = swarm_sub.add_parser("announce", help="Send immediate announce packet")
    announce_p.add_argument("--port", type=int, default=None, help="Daemon port to announce")
    announce_p.add_argument("--castes", type=str, default=None, help="Castes e.g. βγ (default: αβγ)")

    proj_p = sub.add_parser("project", help="Browse completed project artefacts")
    proj_sub = proj_p.add_subparsers(dest="proj_cmd")
    proj_sub.add_parser("list", help="List completed projects")
    show_p = proj_sub.add_parser("show", help="Show project details")
    show_p.add_argument("name", help="Project directory name (partial match)")
    path_p = proj_sub.add_parser("path", help="Print project filesystem path")
    path_p.add_argument("name", help="Project directory name (partial match)")
    summary_p = proj_sub.add_parser("summary", help="Print project summary.md")
    summary_p.add_argument("name", help="Project directory name (partial match)")
    materialize_p = proj_sub.add_parser("materialize", help="Copy generated project suggestions into working folders")
    materialize_p.add_argument("name", help="Project directory name (partial match)")
    materialize_p.add_argument("--into", help="Destination root (default: ./materialized-projects/<project>)")
    materialize_p.add_argument("--force", action="store_true", help="Replace existing materialized suggestion folders")

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
        sys.exit(cmd_patch(args))
    elif args.command == "models":
        cmd_models(args)
    elif args.command == "compact":
        cmd_compact(args)
    elif args.command == "board":
        cmd_board(args)
    elif args.command == "daemon":
        cmd_daemon(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    elif args.command == "swarm":
        cmd_swarm(args)
    elif args.command == "project":
        cmd_project(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

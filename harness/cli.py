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
        caste=Caste(args.caste),
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
    infer_p.add_argument("caste", choices=["α", "β", "γ"], help="Caste to infer from")
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
    else:
        parser.print_help()

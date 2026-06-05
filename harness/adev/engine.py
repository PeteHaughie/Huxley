from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any, Optional, Callable

from harness.comms.message import Message, Caste, Action


@dataclass
class RoleConfig:
    caste: Caste = Caste.GAMMA
    tools: bool = True
    token_input: int = 32768
    token_output: int = 8192


DEFAULT_ROLES: dict[str, RoleConfig] = {
    "programmer": RoleConfig(caste=Caste.ALPHA, tools=True),
    "roaster": RoleConfig(caste=Caste.ALPHA, tools=True),
    "adjudicator": RoleConfig(
        caste=Caste.ALPHA, tools=False, token_input=16384, token_output=4096
    ),
}

PROGRAMMER_SYSTEM = """You are an expert programmer implementing a feature or fix.

You have tools to read, write, and search files. Use them to:
1. Read existing code to understand the codebase
2. Write new code or edit existing files
3. Search for relevant patterns

Rules:
- Write clean, production-quality code
- Follow existing code style and conventions
- After implementing, summarize what you changed and list all files created/modified
- DO NOT make unrelated changes
- You can run bash commands if needed (build, test, lint)
"""

PROGRAMMER_SYSTEM_NO_TOOLS = """You are an expert programmer writing code.

Rules:
- Output the code directly in your response — do not describe a plan, do not reference tools or files
- Write clean, production-quality code
- Follow existing code style and conventions
- DO NOT make unrelated changes
"""

ROASTER_SYSTEM = """You are a harsh but fair code reviewer. Review code changes and identify issues.

Inspect the codebase using your read-only tools (read_file, grep, glob_files, list_directory).
Evaluate for:
- Correctness: Does the code work? Are there bugs or edge cases?
- Security: Any vulnerabilities?
- Style: Does it follow project conventions?
- Design: Is the approach sound?
- Completeness: Fully implemented? Any TODOs or stubs?

Your response format:
VERDICT: APPROVED or DENIED
ISSUES:
- description of each issue (severity: high/medium/low)

If APPROVED, list zero issues.
Only DENY if there are concrete, actionable problems.
"""

ADJUDICATOR_SYSTEM = """You are a final adjudicator. The programmer and reviewer disagree after multiple rounds.

Consider:
- Is the reviewer being too strict about non-critical issues?
- Is the programmer ignoring valid concerns?
- Is the implementation good enough to ship?

Verdict options:
APPROVE — code is acceptable, ship it
REJECT — serious problems, abandon this approach
CONTINUE — one more round might resolve remaining issues

Briefly explain your reasoning.
"""

_CASTE_ALIAS = {
    "a": Caste.ALPHA,
    "alpha": Caste.ALPHA,
    "\u03b1": Caste.ALPHA,
    "b": Caste.BETA,
    "beta": Caste.BETA,
    "\u03b2": Caste.BETA,
    "g": Caste.GAMMA,
    "gamma": Caste.GAMMA,
    "\u03b3": Caste.GAMMA,
}


def _parse_caste(raw: str | Caste) -> Caste:
    if isinstance(raw, Caste):
        return raw
    key = raw.strip().lower()
    if key not in _CASTE_ALIAS:
        raise ValueError(f"unknown caste: {raw} (use a/b/g or alpha/beta/gamma)")
    return _CASTE_ALIAS[key]


def _parse_review(text: str) -> dict:
    upper = text.strip().upper()
    verdict_line = [line for line in upper.split("\n") if "VERDICT:" in line]
    approved_tokens = ("APPROVED", "APPROVE")
    if verdict_line:
        verdict = (
            "APPROVED"
            if any(token in verdict_line[0] for token in approved_tokens)
            else "DENIED"
        )
    else:
        verdict = (
            "APPROVED"
            if any(upper.startswith(token) for token in approved_tokens)
            else "DENIED"
        )
    return {"verdict": verdict, "feedback": text}


class AdversarialDevEngine:
    def __init__(
        self,
        tool_service=None,
        router=None,
        roles: Optional[dict[str, RoleConfig | dict]] = None,
        delegate: Optional[Callable] = None,
    ):
        from harness.tool.engine import ToolService
        from harness.comms.router import Router

        self._tool_service = tool_service or ToolService()
        self._router = router or Router(tool_service=self._tool_service)
        self._roles: dict[str, RoleConfig] = self._resolve_roles(roles)
        self._delegate = delegate

    @staticmethod
    def _resolve_roles(overrides: Optional[dict]) -> dict[str, RoleConfig]:
        roles = {}
        for name, default in DEFAULT_ROLES.items():
            if overrides and name in overrides:
                raw = overrides[name]
                if isinstance(raw, RoleConfig):
                    roles[name] = raw
                elif isinstance(raw, dict):
                    parsed: dict[str, Any] = {}
                    for k, v in raw.items():
                        parsed[k] = _parse_caste(v) if k == "caste" else v
                    roles[name] = RoleConfig(
                        caste=parsed.get("caste", default.caste),
                        tools=parsed.get("tools", default.tools),
                        token_input=parsed.get("token_input", default.token_input),
                        token_output=parsed.get("token_output", default.token_output),
                    )
                else:
                    roles[name] = default
            else:
                roles[name] = default
        return roles

    def run(
        self,
        task: str,
        workdir: Optional[str] = None,
        max_rounds: int = 5,
        **role_overrides,
    ) -> dict:
        root = workdir or os.getcwd()

        from harness.tool.builtins.filesystem import allow_path as allow_fs_path

        allow_fs_path(root)
        if self._tool_service.registry.has_tool("grep"):
            from harness.tool.builtins.search import allow_path as allow_search_path

            allow_search_path(root)
        if self._tool_service.registry.has_tool("bash"):
            from harness.tool.builtins.shell import allow_path as allow_shell_path

            allow_shell_path(root)
        roles = self._resolve_roles(role_overrides) if role_overrides else self._roles

        history: list[dict] = []
        code_result = ""

        for round_ in range(1, max_rounds + 1):
            code_result = self._programmer_round(task, history, round_, roles)
            review = self._roaster_round(task, code_result, roles)

            if review["verdict"] == "APPROVED":
                return {
                    "status": "approved",
                    "code_result": code_result,
                    "rounds": round_,
                    "history": history,
                }

            history.append(review)

        final = self._adjudicator_round(task, code_result, history, max_rounds, roles)
        return {
            "status": final.get("verdict", "unknown"),
            "code_result": code_result,
            "rounds": max_rounds,
            "history": history,
            "adjudication": final.get("feedback", ""),
        }

    def _programmer_round(
        self, task: str, history: list[dict], round_: int, roles: dict
    ) -> str:
        cfg = roles["programmer"]
        critique_lines = []
        for h in history:
            fb = h.get("feedback", "")
            first_line = fb.split("\n")[0].strip()
            critique_lines.append(f"--- Previous review ---\n{first_line}")
        critique = (
            "\n".join(critique_lines) if critique_lines else "No previous critique."
        )

        sys_prompt = PROGRAMMER_SYSTEM if cfg.tools else PROGRAMMER_SYSTEM_NO_TOOLS
        inst = (
            "Use tools to read, write, and search files. When done, summarize what you changed."
            if cfg.tools
            else "Output the code directly in your response."
        )
        prompt = (
            f"{sys_prompt}\n\nTask: {task}\n\nRound {round_}:\n{critique}\n\n{inst}"
        )
        return self._call_agent(prompt, cfg)

    def _roaster_round(self, task: str, code_result: str, roles: dict) -> dict:
        cfg = roles["roaster"]
        prompt = (
            f"{ROASTER_SYSTEM}\n\n"
            f"Task: {task}\n\n"
            f"Programmer's summary of changes:\n{code_result}\n\n"
            f"Inspect the codebase and provide your review. "
            f"Read files using read_file, search with grep, etc. "
            f"Then output VERDICT: APPROVED or DENIED with your issues list."
        )
        result = self._call_agent(prompt, cfg)
        return _parse_review(result)

    def _adjudicator_round(
        self, task: str, code_result: str, history: list[dict], rounds: int, roles: dict
    ) -> dict:
        cfg = roles["adjudicator"]
        review_lines = []
        for i, h in enumerate(history):
            fb = h.get("feedback", "")
            review_lines.append(f"--- Round {i + 1} review ---\n{fb[:2000]}")

        prompt = (
            f"{ADJUDICATOR_SYSTEM}\n\n"
            f"Task: {task}\n\n"
            f"Rounds completed: {rounds}\n\n"
            f"Latest code summary:\n{code_result[:2000]}\n\n"
            f"Review history:\n{chr(10).join(review_lines)}\n\n"
            f"Make your final decision."
        )
        result = self._call_agent(prompt, cfg)
        return _parse_review(result)

    def _call_agent(self, prompt: str, cfg: RoleConfig) -> str:
        if self._delegate:
            result = self._delegate(cfg, prompt)
            if result is not None:
                return result

        payload: dict = {"prompt": prompt}
        if cfg.tools:
            payload["tools"] = True
        msg = Message(
            caste=cfg.caste,
            action=Action.INFER,
            payload=payload,
            token_budget={"input": cfg.token_input, "output": cfg.token_output},
        )
        resp = self._router.dispatch(msg)
        if "error" in resp.payload:
            raise RuntimeError(resp.payload["error"])
        return resp.payload.get("result", "")

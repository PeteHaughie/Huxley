from __future__ import annotations
import re
import sys
import time
import yaml
from typing import Iterator, TYPE_CHECKING
from harness.comms.message import Message, Caste, Action
from harness.skill.loader import load_skill

if TYPE_CHECKING:
    from harness.caste.alpha import Alpha
    from harness.caste.beta import Beta
    from harness.caste.gamma import Gamma
    from harness.caste._base import CasteBase
    from harness.tool.engine import ToolService
    from harness.skill.registry import SkillRegistry


class OpenAIRequestError(Exception):
    def __init__(
        self, message: str, status: int = 400, error_type: str = "invalid_request_error"
    ):
        super().__init__(message)
        self.status = status
        self.error_type = error_type


def _match_skills(prompt: str, all_skills: list[dict]) -> list[dict]:
    prompt_lower = prompt.lower()
    matches = []
    for skill in all_skills:
        for trigger in skill["triggers"]:
            if trigger.lower() in prompt_lower:
                matches.append(skill)
                break
    return matches


def _requests_openai_tools(request_options: dict | None) -> bool:
    if not isinstance(request_options, dict):
        return False
    if request_options.get("tools") or request_options.get("functions"):
        return True
    tool_choice = request_options.get("tool_choice")
    if tool_choice not in (None, False, "none"):
        return True
    function_call = request_options.get("function_call")
    return function_call not in (None, False, "none")


class Router:
    _alpha: Alpha
    _beta: Beta
    _gamma: Gamma
    _ts: ToolService
    _routes: dict[Caste, CasteBase]

    def __init__(self, tool_service=None):
        from harness.caste.gamma import Gamma
        from harness.caste.beta import Beta
        from harness.caste.alpha import Alpha
        from harness.tool.engine import ToolService

        # import config at runtime so tests can patch harness.config.load_config
        try:
            import harness.config as _hc

            _cfg = _hc.load_config()
            api_cfg = _cfg.get("api", {})
            raw_tools_cfg = _cfg.get("tools", {})
            if isinstance(raw_tools_cfg, dict):
                tools_cfg = dict(raw_tools_cfg)
            elif isinstance(raw_tools_cfg, bool):
                tools_cfg = {"enabled": raw_tools_cfg}
            else:
                tools_cfg = {}
        except (FileNotFoundError, OSError, yaml.YAMLError) as e:
            print(
                f"γ|router|config_err|{type(e).__name__}: {e}",
                file=sys.stderr,
                flush=True,
            )
            api_cfg = {}
            tools_cfg = {}
        self._api_cfg = dict(api_cfg) if isinstance(api_cfg, dict) else {}
        self._tools_enabled = bool(tools_cfg.get("enabled", True))

        self._ts = tool_service or ToolService(tools_cfg=tools_cfg)
        self._gamma = Gamma(tool_service=self._ts)
        self._beta = Beta(tool_service=self._ts)
        self._alpha = Alpha(tool_service=self._ts)
        self._routes: dict[Caste, CasteBase] = {
            Caste.GAMMA: self._gamma,
            Caste.BETA: self._beta,
            Caste.ALPHA: self._alpha,
        }
        self._skill_cache: list[dict] | None = None
        self._skill_cache_lock = __import__("threading").Lock()
        try:
            import os
            import traceback

            if os.environ.get("HUXLEY_DEBUG_ROUTER_INIT") and not getattr(
                Router, "_debug_printed", False
            ):
                stack = traceback.format_stack()
                caller = stack[-3].strip() if len(stack) >= 3 else stack[0].strip()
                print(
                    "γ|router|debug|api_cfg_keys=",
                    list(self._api_cfg.keys()),
                    "caller=",
                    caller,
                    file=sys.stderr,
                    flush=True,
                )
                Router._debug_printed = True
        except Exception:
            pass

    def _get_all_skills(self) -> list[dict]:
        """Return cached skill list, populating the cache on first call."""
        if self._skill_cache is not None:
            return self._skill_cache
        with self._skill_cache_lock:
            if self._skill_cache is not None:
                return self._skill_cache
            from harness.skill.registry import SkillRegistry
            self._skill_cache = SkillRegistry().all_with_triggers()
            return self._skill_cache

    def refresh_skills(self) -> None:
        """Invalidate the cached skill list so the next dispatch re-scans."""
        with self._skill_cache_lock:
            self._skill_cache = None

    def dispatch(self, msg: Message) -> Message:
        handler = self._routes.get(msg.caste)
        if handler is None:
            response_caste = msg.caste if isinstance(msg.caste, Caste) else Caste.ALPHA
            return Message(
                caste=response_caste,
                action=Action.ROUTE,
                payload={"error": f"unknown caste: {msg.caste}"},
                session=msg.session,
            )

        prompt = ""
        if isinstance(msg.payload, dict):
            prompt = str(msg.payload.get("prompt", ""))

        all_skills = self._get_all_skills() if self._tools_enabled else []
        matched_names = set(s["name"] for s in _match_skills(prompt, all_skills))
        if matched_names:
            catalog = self._build_skill_catalog(all_skills, matched_names)
            augmented_prompt = f"{catalog}\n\n{prompt}" if prompt else catalog
            requires_tools = any(
                s.get("requires_tools", False)
                for s in all_skills
                if s["name"] in matched_names
            )
            if isinstance(msg.payload, dict):
                msg.payload["prompt"] = augmented_prompt
                if requires_tools and not msg.payload.get("tools"):
                    msg.payload["tools"] = True

        if isinstance(msg.payload, dict):
            prompt = str(msg.payload.get("prompt", ""))
        requests_tools = isinstance(msg.payload, dict) and bool(msg.payload.get("tools"))
        if requests_tools and not self._tools_enabled:
            return Message(
                caste=msg.caste,
                action=Action.ROUTE,
                payload={"error": "tool execution is disabled in configuration"},
                session=msg.session,
            )
        if requests_tools and not getattr(handler, "supports_tools", False):
            return Message(
                caste=msg.caste,
                action=Action.ROUTE,
                payload={"error": f"{msg.caste.value} does not support tool execution"},
                session=msg.session,
            )

        response = handler.infer(msg)

        if isinstance(response.payload, dict):
            content = str(response.payload.get("result", response.payload.get("content", "")))
            m = re.search(r"USE_SKILL\(([\w-]+),\s*(.+?)\)", content)
            if m:
                skill_name = m.group(1)
                task = m.group(2).strip().strip('"').strip("'")
                return self._delegate_skill(skill_name, task, msg)

        return response

    def _build_skill_catalog(self, all_skills: list[dict], matched_names: set[str]) -> str:
        lines = ["<available_skills>"]
        for s in all_skills:
            triggers_str = ", ".join(s.get("triggers", []))
            desc = s.get("description", "")
            matched = " *" if s["name"] in matched_names else ""
            lines.append(
                f"  - {s['name']}{matched}: {desc}"
                + (f" (triggers: {triggers_str})" if triggers_str else "")
            )
        lines.append(
            "</available_skills>\n\n"
            "To use a skill, respond with: USE_SKILL(skill_name, task_description)\n"
            "The system will execute the skill and return the result."
        )
        return "\n".join(lines)

    def _delegate_skill(self, skill_name: str, task: str, original_msg: Message) -> Message:
        from harness.tool.engine import ToolService

        body = load_skill(skill_name)
        if not body:
            return Message(
                caste=original_msg.caste,
                action=Action.ROUTE,
                payload={"error": f"skill '{skill_name}' not found"},
                session=original_msg.session,
            )

        augmented_prompt = f"<skill:{skill_name}>\n{body}\n</skill:{skill_name}>\n\n{task}"
        ts = self._ts
        ts.registry.scan_skills(skill_name=skill_name)

        delegate_msg = Message(
            caste=Caste.BETA,
            action=Action.INFER,
            payload={
                "prompt": augmented_prompt,
                "tools": True,
                "skill_name": skill_name,
            },
            session=original_msg.session,
            token_budget=original_msg.token_budget,
        )

        handler = self._routes.get(Caste.BETA)
        if handler is None or not getattr(handler, "supports_tools", False):
            return Message(
                caste=original_msg.caste,
                action=Action.ROUTE,
                payload={"error": "beta cannot handle delegated skill"},
                session=original_msg.session,
            )

        return handler.infer(delegate_msg)

    @property
    def tools_enabled(self) -> bool:
        return self._tools_enabled

    def health(self, caste: Caste) -> bool:
        handler = self._routes.get(caste)
        if handler is None:
            return False
        return handler.health()

    def openai_models(self) -> list[dict]:
        registry = self._openai_model_registry()
        seen = set()
        models = []
        for item in registry:
            model_id = str(item["id"]).strip()
            if not model_id or model_id in seen:
                continue
            seen.add(model_id)
            models.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": 0,
                    "owned_by": item["owned_by"],
                    "permission": [],
                    "root": item["root"],
                    "parent": item.get("parent"),
                }
            )
        return models

    def _get_system_tools(self) -> list[dict] | None:
        ts = self._ts
        if ts is None:
            return None
        try:
            ts.registry.scan_skills()
            tools = ts.registry.definitions()
            return tools if tools else None
        except Exception as e:
            print(f"\u03b3|router|tools_err|{e}", flush=True)
            return None

    @staticmethod
    def _merge_tools(client_tools: list[dict], system_tools: list[dict]) -> list[dict]:
        seen: dict[str, dict] = {}
        for t in client_tools:
            seen[t["function"]["name"]] = t
        for st in system_tools:
            fn_name = st.get("function", {}).get("name", "")
            if fn_name and fn_name not in seen:
                seen[fn_name] = st
        return list(seen.values())

    def openai_chat_completion(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_options: dict | None = None,
    ) -> dict:
        canonical_model, handler = self._resolve_openai_model(model)
        max_output = max_tokens if max_tokens is not None else 512
        created = int(time.time())
        caller_requested_tools = _requests_openai_tools(request_options)

        if (
            handler is self._alpha
            and caller_requested_tools
            and self._tools_enabled
            and self._ts is not None
        ):
            system_tools = self._get_system_tools()
            if system_tools:
                client_tools = list(request_options.get("tools", [])) if request_options else []
                if client_tools:
                    all_tools = self._merge_tools(client_tools, system_tools)
                else:
                    all_tools = system_tools
                def model_fn(messages, **kw):
                    kw.pop("tool_choice", None)
                    resp = handler.complete_chat(
                        messages=messages,
                        max_tokens=max_output,
                        temperature=temperature,
                        request_options=kw if kw else None,
                    )
                    if not isinstance(resp, dict):
                        raise RuntimeError(
                            f"invalid response from {canonical_model} model backend"
                        )
                    return resp
                resp = self._ts.run_loop(
                    model_fn=model_fn, messages=messages, tools=all_tools
                )
                resp["model"] = canonical_model
                resp.setdefault("object", "chat.completion")
                resp.setdefault("created", created)
                resp.setdefault("id", f"chatcmpl-{created}")
                return resp

        if handler is self._alpha:
            response = self._alpha.complete_chat(
                messages,
                max_output,
                temperature=temperature,
                request_options=request_options,
            )
            if isinstance(response, dict):
                if caller_requested_tools:
                    result = self._try_text_tool_execution(
                        response, messages, max_output, temperature, canonical_model
                    )
                    if result is not None:
                        return result
                response["model"] = canonical_model
                response.setdefault("object", "chat.completion")
                response.setdefault("created", created)
                response.setdefault("id", f"chatcmpl-{created}")
                return response
            raise RuntimeError("invalid response from alpha model backend")
        if handler is self._beta:
            response = self._beta.complete_chat(
                messages,
                max_output,
                temperature=temperature,
                request_options=request_options,
            )
            if isinstance(response, dict):
                response["model"] = canonical_model
                response.setdefault("object", "chat.completion")
                response.setdefault("created", created)
                response.setdefault("id", f"chatcmpl-{created}")
                return response
            raise RuntimeError("invalid response from beta model backend")
        raise RuntimeError("invalid model backend")

    def openai_chat_completion_stream(
        self,
        model: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float = 0.0,
        request_options: dict | None = None,
    ) -> Iterator[dict]:
        canonical_model, handler = self._resolve_openai_model(model)
        max_output = max_tokens if max_tokens is not None else 512
        created = int(time.time())
        completion_id = f"chatcmpl-{created}"
        caller_requested_tools = _requests_openai_tools(request_options)

        if (
            handler is self._alpha
            and caller_requested_tools
            and self._tools_enabled
            and self._ts is not None
        ):
            system_tools = self._get_system_tools()
            if system_tools:
                client_tools = list(request_options.get("tools", [])) if request_options else []
                if client_tools:
                    all_tools = self._merge_tools(client_tools, system_tools)
                else:
                    all_tools = system_tools
                def model_fn(messages, **kw):
                    kw.pop("tool_choice", None)
                    resp = handler.complete_chat(
                        messages=messages,
                        max_tokens=max_output,
                        temperature=temperature,
                        request_options=kw if kw else None,
                    )
                    if not isinstance(resp, dict):
                        raise RuntimeError(
                            f"invalid response from {canonical_model} model backend"
                        )
                    return resp
                resp = self._ts.run_loop(
                    model_fn=model_fn, messages=messages, tools=all_tools
                )
                content = resp.get("choices", [{}])[0].get("message", {}).get("content", "")
                yield {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": canonical_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": content},
                            "finish_reason": "stop",
                        }
                    ],
                }
                return

        if handler is self._alpha:
            for chunk in self._alpha.stream_chat(
                messages, max_output, temperature=temperature,
                request_options=request_options,
            ):
                yield self._normalize_alpha_stream_chunk(
                    chunk, canonical_model, created, completion_id
                )
            return

        if handler is self._beta:
            for item in self._beta.stream_chat(
                messages, max_output, temperature=temperature,
                request_options=request_options,
            ):
                delta = {}
                content = item.get("delta", "")
                if content:
                    delta["content"] = content
                tool_calls = item.get("tool_calls")
                if tool_calls:
                    delta["tool_calls"] = tool_calls
                yield {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": canonical_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": item.get("finish_reason"),
                        }
                    ],
                }
            return
        raise RuntimeError("invalid model backend")

    def _try_text_tool_execution(
        self,
        response: dict,
        messages: list[dict],
        max_output: int,
        temperature: float,
        canonical_model: str,
    ) -> dict | None:
        if self._ts is None or not self._tools_enabled:
            return None
        msg = response.get("choices", [{}])[0].get("message", {})
        if msg.get("tool_calls"):
            return None
        from harness.tool.engine import _parse_text_tool

        text_tool = _parse_text_tool(msg.get("content", ""))
        if not text_tool:
            return None
        tools = self._get_system_tools()
        if not tools:
            return None

        created = int(time.time())

        def model_fn(messages, **kw):
            kw.pop("tool_choice", None)
            _, handler = self._resolve_openai_model(canonical_model)
            resp = handler.complete_chat(
                messages=messages,
                max_tokens=max_output,
                temperature=temperature,
                request_options=kw if kw else None,
            )
            if not isinstance(resp, dict):
                raise RuntimeError(
                    f"invalid response from {canonical_model} model backend"
                )
            return resp

        resp = self._ts.run_loop(
            model_fn=model_fn, messages=messages, tools=tools
        )
        resp["model"] = canonical_model
        resp.setdefault("object", "chat.completion")
        resp.setdefault("created", created)
        resp.setdefault("id", f"chatcmpl-{created}")
        return resp

    def _normalize_alpha_stream_chunk(
        self, chunk: dict, model: str, created: int, completion_id: str
    ) -> dict:
        normalized = dict(chunk)
        normalized["id"] = chunk.get("id", completion_id)
        normalized["object"] = "chat.completion.chunk"
        normalized["created"] = chunk.get("created", created)
        normalized["model"] = model
        choices = []
        for index, choice in enumerate(chunk.get("choices", [])):
            delta = choice.get("delta", {})
            if not isinstance(delta, dict):
                delta = {}
            choices.append(
                {
                    "index": choice.get("index", index),
                    "delta": delta,
                    "finish_reason": choice.get("finish_reason"),
                }
            )
        normalized["choices"] = choices or [
            {"index": 0, "delta": {}, "finish_reason": "stop"}
        ]
        return normalized

    def _resolve_openai_model(self, model: str) -> tuple[str, object]:
        alias_map = {
            item["id"].strip().lower(): (item["id"], item["handler"])
            for item in self._openai_model_registry()
        }
        resolved = alias_map.get(str(model).strip().lower())
        if resolved is None:
            try:
                import os

                if os.environ.get("HUXLEY_DEBUG_RESOLVE"):
                    print(
                        "γ|router|resolve|unknown model",
                        model,
                        "api_cfg_keys=",
                        list(self._api_cfg.keys()),
                        file=sys.stderr,
                        flush=True,
                    )
                    regs = self._openai_model_registry()
                    print(
                        "γ|router|resolve|registry ids=",
                        [r.get("id") for r in regs],
                        file=sys.stderr,
                        flush=True,
                    )
                    print(
                        "γ|router|resolve|alias_map_keys=",
                        list(alias_map.keys()),
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception:
                pass
            raise ValueError(f"unknown model: {model}")
        return resolved

    def _openai_model_registry(self) -> list[dict]:
        alpha_backend = "gemma-4-12b"
        beta_backend = "ternary-bonsai-8b"
        registry = [
            {
                "id": alpha_backend,
                "root": alpha_backend,
                "parent": None,
                "owned_by": "huxley-alpha",
                "handler": self._alpha,
            },
            {
                "id": "alpha",
                "root": alpha_backend,
                "parent": alpha_backend,
                "owned_by": "huxley-alpha",
                "handler": self._alpha,
            },
            {
                "id": beta_backend,
                "root": beta_backend,
                "parent": None,
                "owned_by": "huxley-beta",
                "handler": self._beta,
            },
            {
                "id": "beta",
                "root": beta_backend,
                "parent": beta_backend,
                "owned_by": "huxley-beta",
                "handler": self._beta,
            },
        ]
        alpha_alias = self._configured_openai_alias("alpha_model_id")
        if alpha_alias is not None and not self._has_model_id(registry, alpha_alias):
            registry.insert(
                1,
                {
                    "id": alpha_alias,
                    "root": alpha_backend,
                    "parent": alpha_backend,
                    "owned_by": "huxley-alpha",
                    "handler": self._alpha,
                },
            )
        beta_alias = self._configured_openai_alias("beta_model_id")
        if beta_alias is not None and not self._has_model_id(registry, beta_alias):
            registry.insert(
                len(registry) - 1,
                {
                    "id": beta_alias,
                    "root": beta_backend,
                    "parent": beta_backend,
                    "owned_by": "huxley-beta",
                    "handler": self._beta,
                },
            )
        return registry

    def _configured_openai_alias(self, key: str) -> str | None:
        raw_value = self._api_cfg.get(key)
        if raw_value is None:
            return None
        alias = str(raw_value).strip()
        return alias or None

    def _has_model_id(self, registry: list[dict], model_id: str) -> bool:
        target = model_id.strip().lower()
        return any(
            str(item.get("id", "")).strip().lower() == target for item in registry
        )

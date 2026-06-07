from __future__ import annotations
import sys
import time
import yaml
from typing import Iterator, TYPE_CHECKING
from harness.comms.message import Message, Caste, Action

if TYPE_CHECKING:
    from harness.caste.alpha import Alpha
    from harness.caste.beta import Beta
    from harness.caste.gamma import Gamma
    from harness.caste._base import CasteBase
    from harness.tool.engine import ToolService


class OpenAIRequestError(Exception):
    def __init__(
        self, message: str, status: int = 400, error_type: str = "invalid_request_error"
    ):
        super().__init__(message)
        self.status = status
        self.error_type = error_type


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
        return handler.infer(msg)

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
        if handler is self._alpha:
            response = self._alpha.complete_chat(
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
            raise RuntimeError("invalid response from alpha model backend")
        if handler is self._beta:
            if request_options and any(
                key in request_options
                for key in ("tools", "tool_choice", "functions", "function_call")
            ):
                raise OpenAIRequestError(
                    "tool calling is not supported for beta via the OpenAI-compatible API"
                )
            content = self._beta.complete_chat(
                messages, max_output, temperature=temperature
            )
            response = {
                "id": f"chatcmpl-{created}",
                "object": "chat.completion",
                "created": created,
                "model": canonical_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
            return response
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

        if handler is self._alpha:
            for chunk in self._alpha.stream_chat(
                messages,
                max_output,
                temperature=temperature,
                request_options=request_options,
            ):
                yield self._normalize_alpha_stream_chunk(
                    chunk, canonical_model, created, completion_id
                )
            return

        if handler is self._beta:
            if request_options and any(
                key in request_options
                for key in ("tools", "tool_choice", "functions", "function_call")
            ):
                raise OpenAIRequestError(
                    "tool calling is not supported for beta via the OpenAI-compatible API"
                )
            for item in self._beta.stream_chat(
                messages, max_output, temperature=temperature
            ):
                yield {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": canonical_model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": item.get("delta", "")}
                            if item.get("delta", "")
                            else {},
                            "finish_reason": item.get("finish_reason"),
                        }
                    ],
                }
            return
        raise RuntimeError("invalid model backend")

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
        alpha_backend = "gemma-4-e4b"
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

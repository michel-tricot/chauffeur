"""Command registry and dispatcher: browser-initiated RPC lands here.

Handlers are registered with @registry.command(...); the transport (channel)
feeds incoming envelopes to dispatch() and sends the returned reply back if
the message carried an id. Handler exceptions become error replies, a JS
`await py.call(...)` must always resolve or reject, never hang.
"""

from __future__ import annotations

import dataclasses
import inspect
import typing
from collections.abc import Callable
from typing import Any

from chauffeur import serde


@dataclasses.dataclass
class _Handler:
    fn: Callable
    has_params: bool
    params_type: Any
    strict: bool


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, _Handler] = {}

    def command(self, name: str | Callable | None = None, *, strict: bool = False):
        """Register a handler. Usable as @command, @command() or @command("name").

        If the handler's first parameter is annotated with a dataclass, incoming
        params are converted (and validated) before the call; a dataclass return
        value is serialized back. Unsupported annotations fail here, not on the
        first message.
        """
        if callable(name):
            return self._register(name, None, strict)

        def register(fn: Callable) -> Callable:
            return self._register(fn, name, strict)

        return register

    def _register(self, fn: Callable, name: str | None, strict: bool) -> Callable:
        cmd = name or getattr(fn, "__name__", None)
        if cmd is None:
            raise ValueError("cannot infer a command name for this callable; pass one explicitly")
        if cmd in self._commands:
            raise ValueError(f"command {cmd!r} already registered")
        hints = typing.get_type_hints(fn)
        first_param = next(iter(inspect.signature(fn).parameters), None)
        params_type: Any = Any
        if first_param is not None:
            params_type = hints.get(first_param, Any)
            serde.validate_schema(params_type)
        self._commands[cmd] = _Handler(fn, first_param is not None, params_type, strict)
        return fn

    async def dispatch(self, msg: dict) -> dict:
        msg_id = msg.get("id")
        name = msg.get("command")
        handler = self._commands.get(name)
        if handler is None:
            return {"id": msg_id, "error": {"type": "UnknownCommand", "message": f"no handler for {name!r}"}}
        try:
            if handler.has_params:
                params = msg.get("params")
                if handler.params_type is not Any:
                    params = serde.from_wire(handler.params_type, params, strict=handler.strict)
                result = handler.fn(params)
            else:
                result = handler.fn()
            if inspect.isawaitable(result):
                result = await result
            return {"id": msg_id, "result": serde.to_wire(result)}
        except serde.SerdeError as exc:
            return {"id": msg_id, "error": {"type": "InvalidParams", "message": str(exc)}}
        except Exception as exc:
            return {"id": msg_id, "error": {"type": type(exc).__name__, "message": str(exc)}}

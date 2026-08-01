"""Bidirectional channel to one target (page or extension service worker).

Browser -> Python rides Runtime.addBinding: page JS calls
__chauffeur_dispatch(json), which surfaces as a Runtime.bindingCalled event;
the envelope is dispatched to the CommandRegistry and the reply is delivered
back by evaluating py._deliver(...). Python -> browser is Runtime.evaluate of
py._handle(...) with awaitPromise. Same JSON envelope both ways.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

from chauffeur import serde
from chauffeur.cdp import CDPClient, CDPError
from chauffeur.dispatch import CommandRegistry

BINDING = "__chauffeur_dispatch"

_PY_JS = resources.files("chauffeur").joinpath("js/py.js").read_text(encoding="utf-8")


class ChannelError(RuntimeError):
    """Evaluation failed in the browser context."""


class BindingChannel:
    def __init__(self, cdp: CDPClient, session_id: str, registry: CommandRegistry, target_id: str) -> None:
        self._cdp = cdp
        self._session_id = session_id
        self._registry = registry
        self.target_id = target_id

    @classmethod
    async def open(cls, cdp: CDPClient, session_id: str, registry: CommandRegistry, target_id: str) -> BindingChannel:
        channel = cls(cdp, session_id, registry, target_id)
        await cdp.send("Runtime.enable", session_id=session_id)
        await cdp.send("Runtime.addBinding", {"name": BINDING}, session_id=session_id)
        try:
            # Page domain only exists on page targets; workers just get the
            # direct evaluate below.
            await cdp.send("Page.enable", session_id=session_id)
            await cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": _PY_JS}, session_id=session_id)
        except CDPError:
            pass
        await cdp.send("Runtime.evaluate", {"expression": _PY_JS}, session_id=session_id)
        cdp.on("Runtime.bindingCalled", channel._on_binding, session_id=session_id)
        return channel

    async def _on_binding(self, params: dict) -> None:
        if params.get("name") != BINDING:
            return
        try:
            msg = json.loads(params.get("payload", ""))
        except json.JSONDecodeError:
            return
        reply = await self._registry.dispatch(msg)
        if msg.get("id") is not None:
            await self._cdp.send(
                "Runtime.evaluate",
                {"expression": f"py._deliver({json.dumps(reply)})"},
                session_id=self._session_id,
            )

    async def call(self, command: str, params: Any = None, *, timeout: float = 30.0) -> Any:
        """Python-initiated RPC into the browser: runs the py.on(...) handler."""
        envelope = {"command": command, "params": serde.to_wire(params)}
        return await self.evaluate(f"py._handle({json.dumps(envelope)})", timeout=timeout)

    async def evaluate(self, expression: str, *, await_promise: bool = True, timeout: float = 30.0) -> Any:
        result = await self._cdp.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
            session_id=self._session_id,
            timeout=timeout,
        )
        details = result.get("exceptionDetails")
        if details:
            description = (details.get("exception") or {}).get("description") or details.get("text", "evaluation failed")
            raise ChannelError(description)
        return (result.get("result") or {}).get("value")

    async def navigate(self, url: str) -> None:
        await self._cdp.send("Page.navigate", {"url": url}, session_id=self._session_id)

    async def close(self) -> None:
        await self._cdp.close_target(self.target_id)

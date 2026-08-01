"""Top-level façade: launch a browser, wire a bidirectional channel, expose
the decorator API.

    browser = Browser(LaunchSpec(profile=...))

    @browser.command()
    async def save_password(params: SavePassword) -> SaveResult: ...

    @browser.on("Page.frameNavigated")
    async def navigated(event: dict): ...

    async with browser:
        await browser.serve()

The browser->python channel rides on Runtime.addBinding: page/worker JS calls
window.__chauffeur_dispatch(json), which surfaces as a Runtime.bindingCalled
event; we route it through the command registry and send the reply back with
Runtime.evaluate(py._deliver(...)). browser.call() runs the mirror direction.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from importlib.resources import files
from typing import Any

from chauffeur import serde
from chauffeur.cdp import CDPClient
from chauffeur.dispatch import CommandRegistry
from chauffeur.launch import BrowserHandle, launch
from chauffeur.spec import LaunchSpec
from chauffeur.ua import save_user_agent

_BINDING = "__chauffeur_dispatch"
_PY_JS = files("chauffeur.js").joinpath("py.js").read_text()


class Browser:
    def __init__(self, spec: LaunchSpec) -> None:
        self._spec = spec
        self._registry = CommandRegistry()
        self._cdp_listeners: list[tuple[str, Callable]] = []
        self.handle: BrowserHandle | None = None
        self.cdp: CDPClient | None = None
        self._session_id: str | None = None

    # -- decorator API -------------------------------------------------------

    def command(self, name: str | Callable | None = None, *, strict: bool = False):
        """Register a handler for a browser-initiated command (py.call/py.notify)."""
        return self._registry.command(name, strict=strict)

    def on(self, event: str) -> Callable[[Callable], Callable]:
        """Register a listener for a raw CDP event (delivered as a dict)."""

        def register(fn: Callable) -> Callable:
            self._cdp_listeners.append((event, fn))
            if self.cdp is not None:
                self.cdp.on(event, fn)
            return fn

        return register

    # -- python -> browser ---------------------------------------------------

    async def call(self, command: str, params: Any = None, *, timeout: float = 30.0) -> Any:
        """Invoke a JS handler registered via py.on(command, ...)."""
        assert self.cdp and self._session_id, "browser not started"
        envelope = json.dumps({"command": command, "params": serde.to_wire(params)})
        result = await self.cdp.send(
            "Runtime.evaluate",
            {"expression": f"py._handle({envelope})", "awaitPromise": True, "returnByValue": True},
            session_id=self._session_id,
            timeout=timeout,
        )
        remote = result.get("result", {})
        if result.get("exceptionDetails"):
            raise RuntimeError(remote.get("description", "browser handler failed"))
        return remote.get("value")

    async def evaluate(self, expression: str, *, await_promise: bool = True, timeout: float = 30.0) -> Any:
        """Run arbitrary JS in the primary session and return its value."""
        assert self.cdp and self._session_id, "browser not started"
        result = await self.cdp.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
            session_id=self._session_id,
            timeout=timeout,
        )
        return result.get("result", {}).get("value")

    async def capture_user_agent(self) -> str | None:
        """Persist this browser's real UA next to the profile for later replay.

        Call after a headed login completes; subsequent headless launches with
        ``user_agent="auto"`` will replay it (with the Headless marker stripped).
        """
        ua = await self.evaluate("navigator.userAgent")
        if ua:
            save_user_agent(self._spec.profile, str(ua))
        return ua

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> Browser:
        self.handle = await asyncio.to_thread(launch, self._spec)
        self.cdp = await CDPClient.connect(self.handle.port)
        for event, fn in self._cdp_listeners:
            self.cdp.on(event, fn)
        target_id = await self._primary_target()
        self._session_id = await self.cdp.attach(target_id)
        await self._install_channel(self._session_id)
        return self

    async def _primary_target(self) -> str:
        for target in await self.cdp.targets():
            if target.get("type") == "page":
                return target["targetId"]
        return await self.cdp.create_target(self._spec.url or "about:blank")

    async def _install_channel(self, session_id: str) -> None:
        self.cdp.on("Runtime.bindingCalled", self._on_binding, session_id=session_id)
        await self.cdp.send("Runtime.enable", session_id=session_id)
        await self.cdp.send("Page.enable", session_id=session_id)
        await self.cdp.send("Runtime.addBinding", {"name": _BINDING}, session_id=session_id)
        # Install py.js for future navigations, and in the current document.
        await self.cdp.send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": _PY_JS}, session_id=session_id
        )
        await self.cdp.send("Runtime.evaluate", {"expression": _PY_JS}, session_id=session_id)

    def _on_binding(self, params: dict) -> None:
        if params.get("name") != _BINDING:
            return
        try:
            msg = json.loads(params["payload"])
        except (KeyError, ValueError):
            return
        asyncio.ensure_future(self._handle_binding(params.get("executionContextId"), msg))

    async def _handle_binding(self, _ctx: Any, msg: dict) -> None:
        reply = await self._registry.dispatch(msg)
        if msg.get("id") is None:  # notify(): no reply expected
            return
        expression = f"py._deliver({json.dumps(reply)})"
        try:
            await self.cdp.send(
                "Runtime.evaluate", {"expression": expression}, session_id=self._session_id
            )
        except Exception:
            pass

    async def serve(self) -> None:
        """Block until the browser connection closes."""
        assert self.cdp, "browser not started"
        await self.cdp.wait_closed()

    async def aclose(self) -> None:
        if self.cdp is not None:
            await self.cdp.close()
        if self.handle is not None:
            await asyncio.to_thread(self.handle.terminate)

    async def __aenter__(self) -> Browser:
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

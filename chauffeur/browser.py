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
Runtime.evaluate(py_chauffeur._deliver(...)). browser.call() runs the mirror direction.
"""

from __future__ import annotations

import asyncio
import contextlib
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
        self.extension_ids: list[str] = []
        self._session_id: str | None = None
        self._target_id: str | None = None
        # Set when the primary window/tab is closed. Chrome itself may keep
        # running (macOS keeps the process alive with zero windows), so this,
        # not the connection dropping, is the "user closed the app" signal.
        self._page_closed = asyncio.Event()

    # -- decorator API -------------------------------------------------------

    def command(self, name: str | Callable | None = None, *, strict: bool = False):
        """Register a handler for a browser-initiated command (py_chauffeur.call/py_chauffeur.notify)."""
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
        """Invoke a JS handler registered via py_chauffeur.on(command, ...)."""
        envelope = json.dumps({"command": command, "params": serde.to_wire(params)})
        return await self.evaluate(f"py_chauffeur._handle({envelope})", timeout=timeout)

    async def evaluate(self, expression: str, *, await_promise: bool = True, timeout: float = 30.0) -> Any:
        """Run arbitrary JS in the primary session and return its value."""
        assert self.cdp and self._session_id, "browser not started"
        result = await self.cdp.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
            session_id=self._session_id,
            timeout=timeout,
        )
        details = result.get("exceptionDetails")
        if details:
            description = (details.get("exception") or {}).get("description") or details.get("text", "evaluation failed")
            raise RuntimeError(description)
        return (result.get("result") or {}).get("value")

    async def navigate(self, url: str) -> None:
        """Navigate the primary target."""
        assert self.cdp and self._session_id, "browser not started"
        await self.cdp.send("Page.navigate", {"url": url}, session_id=self._session_id)

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
        # defer_page: a page/app_page starts on about:blank and is navigated
        # below, after the channel exists, its scripts can use py_chauffeur right away.
        self.handle = await asyncio.to_thread(launch, self._spec, defer_page=True)
        try:
            cdp = self.cdp = await CDPClient.connect(self.handle.port)
            for event, fn in self._cdp_listeners:
                cdp.on(event, fn)
            # Branded Chrome 137+ ignores --load-extension; CDP is the only
            # reliable way to load unpacked extensions.
            self.extension_ids = []
            for ext_path in self.handle.extensions:
                loaded = await cdp.send("Extensions.loadUnpacked", {"path": str(ext_path)})
                self.extension_ids.append(loaded["id"])
            target_id = await self._primary_target(cdp)
            self._target_id = target_id
            cdp.on("Target.targetDestroyed", self._on_target_destroyed)
            await cdp.send("Target.setDiscoverTargets", {"discover": True})
            self._session_id = await cdp.attach(target_id)
            await self._install_channel(cdp, self._session_id)
            if self.handle.deferred_url:
                await self.navigate(self.handle.deferred_url)
        except BaseException:
            await self.aclose()
            raise
        return self

    async def _primary_target(self, cdp: CDPClient) -> str:
        for target in await cdp.targets():
            if target.get("type") == "page":
                return target["targetId"]
        return await cdp.create_target(self._spec.url or "about:blank")

    async def _install_channel(self, cdp: CDPClient, session_id: str) -> None:
        # The primary target is always a page, so the Page domain is available.
        cdp.on("Runtime.bindingCalled", self._on_binding, session_id=session_id)
        await cdp.send("Runtime.enable", session_id=session_id)
        await cdp.send("Runtime.addBinding", {"name": _BINDING}, session_id=session_id)
        await cdp.send("Page.enable", session_id=session_id)
        # Install py.js for future navigations, and in the current document.
        await cdp.send(
            "Page.addScriptToEvaluateOnNewDocument", {"source": _PY_JS}, session_id=session_id
        )
        await cdp.send("Runtime.evaluate", {"expression": _PY_JS}, session_id=session_id)

    async def _on_binding(self, params: dict) -> None:
        # Async on purpose: CDPClient._emit spawns, tracks, and error-logs
        # coroutine handlers, so dispatch needs no task bookkeeping here.
        if params.get("name") != _BINDING:
            return
        try:
            msg = json.loads(params["payload"])
        except (KeyError, ValueError):
            return
        await self._handle_binding(params.get("executionContextId"), msg)

    async def _handle_binding(self, context_id: int | None, msg: dict) -> None:
        reply = await self._registry.dispatch(msg)
        if msg.get("id") is None:  # notify(): no reply expected
            return
        cdp = self.cdp
        if cdp is None:  # shut down while the handler ran
            return
        # Deliver into the context that called the binding, iframes and
        # non-default contexts have their own py_chauffeur object with the pending promise.
        params: dict[str, Any] = {"expression": f"py_chauffeur._deliver({json.dumps(reply)})"}
        if context_id is not None:
            params["contextId"] = context_id
        with contextlib.suppress(Exception):
            await cdp.send("Runtime.evaluate", params, session_id=self._session_id)

    def _on_target_destroyed(self, params: dict) -> None:
        if params.get("targetId") == self._target_id:
            self._page_closed.set()

    async def serve(self, *, until: asyncio.Event | None = None) -> None:
        """Block until the primary window/tab is closed, the browser
        connection drops, or `until` is set.

        Watching the window (not just the connection) matters: on macOS the
        browser process outlives its last window, so the connection alone
        never signals "the user closed the app". After serve() returns,
        aclose() terminates the browser process.
        """
        assert self.cdp, "browser not started"
        waiters = [
            asyncio.create_task(self.cdp.wait_closed()),
            asyncio.create_task(self._page_closed.wait()),
        ]
        if until is not None:
            waiters.append(asyncio.create_task(until.wait()))
        try:
            await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for waiter in waiters:
                waiter.cancel()

    async def aclose(self) -> None:
        try:
            if self.cdp is not None:
                await self.cdp.close()
        finally:
            # Terminate even when closing the CDP connection fails; otherwise the
            # browser process would outlive its owner.
            if self.handle is not None:
                await asyncio.to_thread(self.handle.terminate)

    async def __aenter__(self) -> Browser:
        return await self.start()

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

"""Synchronous facade over `chauffeur.Browser`.

The async core is unchanged: SyncBrowser runs an asyncio event loop on a
background thread and bridges each call with run_coroutine_threadsafe. Use it
when you don't want to write async code.

    with SyncBrowser(spec) as browser:
        browser.evaluate("2 + 2")
        browser.call("refresh_ui", {"section": "vault"})
        browser.serve()

Note: registered @command / @on handlers run on the background loop thread,
not the caller's, keep them quick and don't block the loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Literal

from chauffeur.browser import Browser, ServeReason
from chauffeur.launch import BrowserHandle
from chauffeur.spec import LaunchSpec


class SyncBrowser:
    """Synchronous facade over `Browser`: the same API without async code.

    The async core runs on a background thread's event loop and every method
    bridges into it, so nothing here needs `await`; enter the session with
    ``with`` (which calls `start()`). Registered `@command` / `@on` handlers
    run on that loop thread, not the caller's — keep them quick and don't
    block.
    """

    def __init__(self, spec: LaunchSpec) -> None:
        self._async = Browser(spec)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name="chauffeur-loop")

    def _run(self, coro: Any, timeout: float | None = None) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # -- decorator API (forwarded; handlers run on the loop thread) -----------

    def command(self, name: str | Callable | None = None, *, strict: bool = False):
        """Register a handler for a browser-initiated command (`py_chauffeur.call` / `py_chauffeur.notify`)."""
        return self._async.command(name, strict=strict)

    def on(self, event: str) -> Callable[[Callable], Callable]:
        """Register a listener for a raw CDP event (delivered as a `dict`)."""
        return self._async.on(event)

    # -- python -> browser ---------------------------------------------------

    def call(self, command: str, params: Any = None, *, timeout: float = 30.0) -> Any:
        """Invoke a JS handler registered via `py_chauffeur.on(command, ...)` in the primary page."""
        return self._run(self._async.call(command, params, timeout=timeout), timeout + 5)

    def evaluate(self, expression: str, *, await_promise: bool = True, timeout: float = 30.0) -> Any:
        """Run arbitrary JS in the primary session and return its value."""
        return self._run(self._async.evaluate(expression, await_promise=await_promise, timeout=timeout), timeout + 5)

    def navigate(self, url: str, *, wait: Literal["load"] | None = None, timeout: float = 30.0) -> None:
        """Navigate the primary target; `wait="load"` blocks until the destination loads."""
        self._run(self._async.navigate(url, wait=wait, timeout=timeout), timeout + 5)

    def capture_user_agent(self) -> str | None:
        """Persist this browser's real UA next to the profile for later replay."""
        return self._run(self._async.capture_user_agent())

    @property
    def handle(self) -> BrowserHandle | None:
        """The launched process (`port`, `terminate()`); `None` until `start()`."""
        return self._async.handle

    @property
    def extension_ids(self) -> list[str]:
        """Ids of the loaded extensions, in `LaunchSpec.extensions` order."""
        return self._async.extension_ids

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> SyncBrowser:
        """Start the background event loop and launch the browser; returns `self`.
        ``with`` calls this."""
        self._thread.start()
        try:
            self._run(self._async.start())
        except BaseException:
            self._stop_loop()
            raise
        return self

    def serve(self, *, until: threading.Event | None = None) -> ServeReason:
        """Block the calling thread until the window/connection closes, or
        ``until`` (a `threading.Event`) is set; returns why it stopped
        (`"page-closed"`, `"connection-lost"`, or `"until"`)."""
        stop = asyncio.Event()
        watcher: threading.Thread | None = None
        if until is not None:
            # Bridge the threading.Event onto the loop's asyncio.Event.
            def _watch() -> None:
                until.wait()
                self._loop.call_soon_threadsafe(stop.set)

            watcher = threading.Thread(target=_watch, daemon=True, name="chauffeur-serve")
            watcher.start()
        try:
            return self._run(self._async.serve(until=stop))
        finally:
            if until is not None and watcher is not None:
                until.set()  # release the watcher if serve ended for another reason
                watcher.join()

    def close(self) -> None:
        """Shut the browser down and stop the background loop; safe to call twice."""
        if not self._thread.is_alive():
            return
        try:
            self._run(self._async.aclose())
        finally:
            self._stop_loop()

    def _stop_loop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()

    def __enter__(self) -> SyncBrowser:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

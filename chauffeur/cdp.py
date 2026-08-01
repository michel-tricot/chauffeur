"""Async Chrome DevTools Protocol client.

One WebSocket to the browser endpoint; per-target sessions are multiplexed
over it via Target.attachToTarget(flatten=True) + sessionId routing. Commands
are id-matched request/response; unsolicited events fan out to registered
listeners, that event stream is half of the bidirectional story.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import json
import logging
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from websockets.asyncio.client import connect as ws_connect

log = logging.getLogger(__name__)


class CDPError(RuntimeError):
    """The browser rejected a command or the connection failed."""


def _http_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=2) as resp:
        return json.loads(resp.read())


async def _debugger_url(port: int, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    while True:
        try:
            version = await asyncio.to_thread(_http_json, f"http://127.0.0.1:{port}/json/version")
            return version["webSocketDebuggerUrl"]
        except OSError:
            if time.monotonic() > deadline:
                raise CDPError(f"DevTools endpoint on port {port} never came up") from None
            await asyncio.sleep(0.25)


class CDPClient:
    def __init__(self, ws) -> None:
        self._ws = ws
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._listeners: dict[tuple[str, str | None], list[Callable]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._closed = asyncio.Event()
        self._reader = asyncio.create_task(self._read_loop())

    @classmethod
    async def connect(cls, port: int, *, timeout: float = 15.0) -> CDPClient:
        """Connect to the browser's DevTools endpoint on ``port``."""
        url = await _debugger_url(port, timeout)
        ws = await ws_connect(url, max_size=64 * 1024 * 1024)
        return cls(ws)

    async def send(
        self,
        method: str,
        params: dict | None = None,
        *,
        session_id: str | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """Send a CDP command and return its result; raises CDPError when the
        browser rejects it. session_id routes to an attached target's session."""
        self._next_id += 1
        msg_id = self._next_id
        msg: dict[str, Any] = {"id": msg_id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        future = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = future
        try:
            await self._ws.send(json.dumps(msg))
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(msg_id, None)

    def on(self, event: str, handler: Callable, *, session_id: str | None = None) -> None:
        """Register a listener for a CDP event; handler(params) may be a coroutine.

        session_id=None receives the event from every session.
        """
        self._listeners.setdefault((event, session_id), []).append(handler)

    def off(self, event: str, handler: Callable, *, session_id: str | None = None) -> None:
        """Remove a listener registered with on(); unknown handlers are ignored."""
        handlers = self._listeners.get((event, session_id), [])
        if handler in handlers:
            handlers.remove(handler)

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    log.warning("dropping non-JSON CDP frame")
                    continue
                if "id" in msg:
                    future = self._pending.get(msg["id"])
                    if future is None or future.done():
                        continue
                    if "error" in msg:
                        error = msg["error"]
                        future.set_exception(CDPError(f"{error.get('message')} ({error.get('code')})"))
                    else:
                        future.set_result(msg.get("result", {}))
                elif "method" in msg:
                    self._emit(msg)
        except Exception:
            log.debug("CDP read loop ended", exc_info=True)
        finally:
            self._closed.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CDPError("CDP connection closed"))

    def _emit(self, msg: dict) -> None:
        params = msg.get("params", {})
        session = msg.get("sessionId")
        keys = [(msg["method"], session)]
        if session is not None:  # unscoped listeners see every session's events
            keys.append((msg["method"], None))
        for key in keys:
            for handler in self._listeners.get(key, []):
                try:
                    result = handler(params)
                except Exception:
                    log.exception("CDP event handler for %s failed", msg["method"])
                    continue
                if inspect.isawaitable(result):
                    task = asyncio.ensure_future(result)
                    self._tasks.add(task)
                    task.add_done_callback(functools.partial(self._finish_task, msg["method"]))

    def _finish_task(self, method: str, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("async CDP event handler for %s failed", method, exc_info=task.exception())

    # -- target helpers ------------------------------------------------------

    async def targets(self) -> list[dict]:
        """The browser's current targets (pages, workers, ...) as raw dicts."""
        result = await self.send("Target.getTargets")
        return result.get("targetInfos", [])

    async def create_target(self, url: str = "about:blank") -> str:
        """Open a new page target at ``url``; returns its target id."""
        result = await self.send("Target.createTarget", {"url": url})
        return result["targetId"]

    async def attach(self, target_id: str) -> str:
        """Attach to a target (flattened session); returns the session id for send()."""
        result = await self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return result["sessionId"]

    async def close_target(self, target_id: str) -> None:
        """Close a target (page, tab, ...)."""
        await self.send("Target.closeTarget", {"targetId": target_id})

    # -- lifecycle -----------------------------------------------------------

    async def wait_closed(self) -> None:
        """Block until the connection to the browser is gone."""
        await self._closed.wait()

    async def close(self) -> None:
        """Close the WebSocket; pending commands fail with CDPError."""
        await self._ws.close()
        with contextlib.suppress(Exception):
            await self._reader

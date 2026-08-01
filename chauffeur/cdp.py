"""Async Chrome DevTools Protocol client.

One WebSocket to the browser endpoint; per-target sessions are multiplexed
over it via Target.attachToTarget(flatten=True) + sessionId routing. Commands
are id-matched request/response; unsolicited events fan out to registered
listeners — that event stream is half of the bidirectional story.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any

from websockets.asyncio.client import connect as ws_connect


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

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                msg = json.loads(raw)
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
            pass
        finally:
            self._closed.set()
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(CDPError("CDP connection closed"))

    def _emit(self, msg: dict) -> None:
        params = msg.get("params", {})
        for key in ((msg["method"], msg.get("sessionId")), (msg["method"], None)):
            for handler in self._listeners.get(key, []):
                result = handler(params)
                if inspect.isawaitable(result):
                    task = asyncio.ensure_future(result)
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)

    # -- target helpers ------------------------------------------------------

    async def targets(self) -> list[dict]:
        result = await self.send("Target.getTargets")
        return result.get("targetInfos", [])

    async def create_target(self, url: str = "about:blank") -> str:
        result = await self.send("Target.createTarget", {"url": url})
        return result["targetId"]

    async def attach(self, target_id: str) -> str:
        result = await self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        return result["sessionId"]

    async def close_target(self, target_id: str) -> None:
        await self.send("Target.closeTarget", {"targetId": target_id})

    # -- lifecycle -----------------------------------------------------------

    async def wait_closed(self) -> None:
        await self._closed.wait()

    async def close(self) -> None:
        await self._ws.close()
        try:
            await self._reader
        except Exception:
            pass

import asyncio
import json

import pytest

from chauffeur.cdp import CDPClient, CDPError


class FakeWS:
    """Just enough websocket for CDPClient: an async frame iterator + send/close."""

    def __init__(self, frames=()):
        self._queue = asyncio.Queue()
        for frame in frames:
            self._queue.put_nowait(frame)
        self.sent = []
        self.closed = False

    def feed(self, msg: dict) -> None:
        self._queue.put_nowait(json.dumps(msg))

    def end(self) -> None:
        self._queue.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        frame = await self._queue.get()
        if frame is None:
            raise StopAsyncIteration
        return frame

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def close(self):
        self.closed = True
        self.end()


async def test_send_receives_matched_response():
    ws = FakeWS()
    client = CDPClient(ws)
    task = asyncio.create_task(client.send("Target.getTargets"))
    await asyncio.sleep(0)
    ws.feed({"id": ws.sent[0]["id"], "result": {"ok": True}})
    assert await task == {"ok": True}
    await client.close()


async def test_error_response_raises():
    ws = FakeWS()
    client = CDPClient(ws)
    task = asyncio.create_task(client.send("Page.navigate"))
    await asyncio.sleep(0)
    ws.feed({"id": ws.sent[0]["id"], "error": {"message": "nope", "code": -32000}})
    with pytest.raises(CDPError, match="nope"):
        await task
    await client.close()


async def test_pending_command_fails_when_connection_closes():
    ws = FakeWS()
    client = CDPClient(ws)
    task = asyncio.create_task(client.send("Page.enable"))
    await asyncio.sleep(0)
    ws.end()
    with pytest.raises(CDPError, match="closed"):
        await task


async def test_sync_handler_crash_does_not_kill_connection():
    ws = FakeWS()
    client = CDPClient(ws)
    got = []
    client.on("Boom.event", lambda _p: 1 / 0)
    client.on("Ok.event", got.append)
    ws.feed({"method": "Boom.event", "params": {"n": 1}})
    ws.feed({"method": "Ok.event", "params": {"n": 2}})
    ws.end()
    await client.wait_closed()
    assert got == [{"n": 2}]


async def test_async_handler_crash_does_not_kill_connection():
    ws = FakeWS()
    client = CDPClient(ws)
    got = []

    async def boom(params):
        raise RuntimeError("bad handler")

    client.on("Boom.event", boom)
    client.on("Ok.event", got.append)
    ws.feed({"method": "Boom.event", "params": {}})
    ws.feed({"method": "Ok.event", "params": {"n": 2}})
    ws.end()
    await client.wait_closed()
    await asyncio.gather(*client._tasks, return_exceptions=True)
    assert got == [{"n": 2}]


async def test_malformed_frame_is_dropped():
    ws = FakeWS(frames=["not json"])
    client = CDPClient(ws)
    got = []
    client.on("Ok.event", got.append)
    ws.feed({"method": "Ok.event", "params": {"n": 1}})
    ws.end()
    await client.wait_closed()
    assert got == [{"n": 1}]


async def test_session_scoped_listener_only_sees_its_session():
    ws = FakeWS()
    client = CDPClient(ws)
    scoped, all_sessions = [], []
    client.on("Ev.x", scoped.append, session_id="s1")
    client.on("Ev.x", all_sessions.append)
    ws.feed({"method": "Ev.x", "sessionId": "s1", "params": {"n": 1}})
    ws.feed({"method": "Ev.x", "sessionId": "s2", "params": {"n": 2}})
    ws.end()
    await client.wait_closed()
    assert scoped == [{"n": 1}]
    assert all_sessions == [{"n": 1}, {"n": 2}]

import asyncio
import threading
import time

from chauffeur.spec import LaunchSpec
from chauffeur.sync import SyncBrowser


class StubCDP:
    def __init__(self):
        self.sent = []
        self._closed = asyncio.Event()

    async def send(self, method, params=None, *, session_id=None, timeout=30.0):
        self.sent.append((method, params))
        return {"result": {"value": "ok"}}

    async def wait_closed(self):
        await self._closed.wait()

    async def close(self):
        self._closed.set()


def _started(tmp_path):
    """A SyncBrowser with its loop running but a stub CDP swapped in for start()."""
    sb = SyncBrowser(LaunchSpec(profile=tmp_path / "p"))
    sb._thread.start()
    sb._async.cdp = StubCDP()
    sb._async._session_id = "sess"
    sb._async._target_id = "t1"
    return sb


def test_evaluate_forwards_and_returns(tmp_path):
    sb = _started(tmp_path)
    try:
        assert sb.evaluate("1 + 1") == "ok"
        assert sb._async.cdp.sent[-1][0] == "Runtime.evaluate"
    finally:
        sb.close()


def test_call_forwards(tmp_path):
    sb = _started(tmp_path)
    try:
        sb.call("do_thing", {"x": 1})
        method, params = sb._async.cdp.sent[-1]
        assert method == "Runtime.evaluate"
        assert "py._handle" in params["expression"]
    finally:
        sb.close()


def test_navigate_forwards(tmp_path):
    sb = _started(tmp_path)
    try:
        sb.navigate("https://x")
        assert sb._async.cdp.sent[-1] == ("Page.navigate", {"url": "https://x"})
    finally:
        sb.close()


def test_serve_unblocks_on_event(tmp_path):
    sb = _started(tmp_path)
    try:
        done = threading.Event()
        server = threading.Thread(target=sb.serve, kwargs={"until": done})
        server.start()
        time.sleep(0.1)
        assert server.is_alive()  # still blocking
        done.set()
        server.join(timeout=2)
        assert not server.is_alive()
    finally:
        sb.close()


def test_serve_unblocks_on_connection_close(tmp_path):
    sb = _started(tmp_path)
    try:
        server = threading.Thread(target=sb.serve)
        server.start()
        time.sleep(0.1)
        # window/connection gone, set the loop-owned event on the loop thread
        sb._loop.call_soon_threadsafe(sb._async.cdp._closed.set)
        server.join(timeout=2)
        assert not server.is_alive()
    finally:
        sb.close()


def test_close_is_idempotent(tmp_path):
    sb = _started(tmp_path)
    sb.close()
    sb.close()  # no error, no hang
    assert not sb._thread.is_alive()


def test_command_registration_forwards(tmp_path):
    sb = SyncBrowser(LaunchSpec(profile=tmp_path / "p"))

    @sb.command()
    def ping(params: dict):
        return "pong"

    assert "ping" in sb._async._registry._commands

import asyncio
import json

from chauffeur.browser import _BINDING, Browser
from chauffeur.spec import LaunchSpec


class StubCDP:
    def __init__(self):
        self.sent = []
        self._closed = asyncio.Event()

    async def send(self, method, params=None, *, session_id=None, timeout=30.0):
        self.sent.append((method, params, session_id))
        return {}

    async def wait_closed(self):
        await self._closed.wait()


def _browser(tmp_path):
    browser = Browser(LaunchSpec(profile=tmp_path / "p"))
    browser.cdp = StubCDP()
    browser._session_id = "sess"
    return browser


def _delivered(params):
    """The reply envelope inside a py._deliver(...) evaluate expression."""
    return json.loads(params["expression"].removeprefix("py._deliver(").removesuffix(")"))


async def test_binding_reply_targets_calling_context(tmp_path):
    browser = _browser(tmp_path)

    @browser.command()
    def ping(params: dict):
        return {"pong": True}

    payload = json.dumps({"id": "js1", "command": "ping", "params": {}})
    await browser._on_binding({"name": _BINDING, "payload": payload, "executionContextId": 7})

    method, params, session = browser.cdp.sent[-1]
    assert method == "Runtime.evaluate"
    assert session == "sess"
    assert params["contextId"] == 7
    assert _delivered(params) == {"id": "js1", "result": {"pong": True}}


async def test_navigate_uses_primary_session(tmp_path):
    browser = _browser(tmp_path)
    await browser.navigate("https://x")
    assert browser.cdp.sent == [("Page.navigate", {"url": "https://x"}, "sess")]


async def test_serve_unblocks_on_event(tmp_path):
    browser = _browser(tmp_path)
    done = asyncio.Event()
    task = asyncio.create_task(browser.serve(until=done))
    await asyncio.sleep(0)
    assert not task.done()
    done.set()
    await asyncio.wait_for(task, 1)


async def test_serve_unblocks_when_window_closes(tmp_path):
    browser = _browser(tmp_path)
    browser._target_id = "t1"
    task = asyncio.create_task(browser.serve())
    await asyncio.sleep(0)
    browser._on_target_destroyed({"targetId": "other-tab"})
    await asyncio.sleep(0)
    assert not task.done()
    browser._on_target_destroyed({"targetId": "t1"})
    await asyncio.wait_for(task, 1)


async def test_serve_unblocks_on_connection_close(tmp_path):
    browser = _browser(tmp_path)
    task = asyncio.create_task(browser.serve(until=asyncio.Event()))
    await asyncio.sleep(0)
    browser.cdp._closed.set()  # window closed -> CDP connection gone
    await asyncio.wait_for(task, 1)


async def test_notify_sends_no_reply(tmp_path):
    browser = _browser(tmp_path)

    @browser.command()
    def fire(params: dict):
        return "ignored"

    payload = json.dumps({"id": None, "command": "fire", "params": {}})
    await browser._on_binding({"name": _BINDING, "payload": payload, "executionContextId": 7})
    assert browser.cdp.sent == []


async def test_other_bindings_are_ignored(tmp_path):
    browser = _browser(tmp_path)
    await browser._on_binding({"name": "someone_else", "payload": "{}", "executionContextId": 1})
    assert browser.cdp.sent == []


async def test_unknown_command_still_gets_error_reply(tmp_path):
    browser = _browser(tmp_path)
    payload = json.dumps({"id": "js2", "command": "nope", "params": {}})
    await browser._on_binding({"name": _BINDING, "payload": payload, "executionContextId": 3})

    _, params, _ = browser.cdp.sent[-1]
    assert _delivered(params)["error"]["type"] == "UnknownCommand"

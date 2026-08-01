import asyncio
import json
from types import SimpleNamespace

import pytest

from chauffeur.browser import _BINDING, Browser, JSError
from chauffeur.cdp import CDPError
from chauffeur.spec import LaunchSpec


class StubCDP:
    def __init__(self):
        self.sent = []
        self.replies = {}  # method -> reply dict
        self.listeners = {}
        self._closed = asyncio.Event()

    async def send(self, method, params=None, *, session_id=None, timeout=30.0):
        self.sent.append((method, params, session_id))
        return dict(self.replies.get(method, {}))

    def on(self, event, handler, *, session_id=None):
        self.listeners.setdefault((event, session_id), []).append(handler)

    def off(self, event, handler, *, session_id=None):
        handlers = self.listeners.get((event, session_id), [])
        if handler in handlers:
            handlers.remove(handler)

    def emit(self, event, params, session_id=None):
        for handler in list(self.listeners.get((event, session_id), [])):
            handler(params)

    async def close(self):
        self._closed.set()

    async def wait_closed(self):
        await self._closed.wait()


def _browser(tmp_path):
    browser = Browser(LaunchSpec(profile=tmp_path / "p"))
    browser.cdp = StubCDP()
    browser._session_id = "sess"
    return browser


def _delivered(params):
    """The reply envelope inside a py_chauffeur._deliver(...) evaluate expression."""
    return json.loads(params["expression"].removeprefix("py_chauffeur._deliver(").removesuffix(")"))


async def test_binding_reply_targets_calling_context(tmp_path):
    browser = _browser(tmp_path)

    @browser.command()
    def ping(params: dict):
        return {"pong": True}

    payload = json.dumps({"id": "js1", "command": "ping", "params": {}})
    await browser._binding_handler(browser._session_id)({"name": _BINDING, "payload": payload, "executionContextId": 7})

    method, params, session = browser.cdp.sent[-1]
    assert method == "Runtime.evaluate"
    assert session == "sess"
    assert params["contextId"] == 7
    assert _delivered(params) == {"id": "js1", "result": {"pong": True}}


async def test_navigate_uses_primary_session(tmp_path):
    browser = _browser(tmp_path)
    await browser.navigate("https://x")
    assert browser.cdp.sent == [("Page.navigate", {"url": "https://x"}, "sess")]


async def test_navigate_raises_when_chrome_refuses(tmp_path):
    browser = _browser(tmp_path)
    browser.cdp.replies["Page.navigate"] = {"errorText": "net::ERR_NAME_NOT_RESOLVED"}
    with pytest.raises(CDPError, match="ERR_NAME_NOT_RESOLVED"):
        await browser.navigate("https://nope.invalid")


async def test_navigate_wait_blocks_until_frame_stops(tmp_path):
    browser = _browser(tmp_path)
    browser.cdp.replies["Page.navigate"] = {"frameId": "f1"}
    task = asyncio.create_task(browser.navigate("https://x", wait="load"))
    await asyncio.sleep(0)
    assert not task.done()
    browser.cdp.emit("Page.frameStoppedLoading", {"frameId": "other"}, session_id="sess")
    await asyncio.sleep(0)
    assert not task.done()  # a different frame's stop must not release the wait
    browser.cdp.emit("Page.frameStoppedLoading", {"frameId": "f1"}, session_id="sess")
    await asyncio.wait_for(task, 1)
    assert browser.cdp.listeners[("Page.frameStoppedLoading", "sess")] == []  # unsubscribed


async def test_navigate_wait_tolerates_stop_racing_the_reply(tmp_path):
    # The frame can finish loading before the Page.navigate reply is
    # processed (fast file:// pages); the buffered stop must still release.
    browser = _browser(tmp_path)
    stub = browser.cdp
    stub.replies["Page.navigate"] = {"frameId": "f1"}
    original_send = stub.send

    async def send(method, params=None, **kwargs):
        result = await original_send(method, params, **kwargs)
        if method == "Page.navigate":
            stub.emit("Page.frameStoppedLoading", {"frameId": "f1"}, session_id="sess")
        return result

    stub.send = send
    await asyncio.wait_for(browser.navigate("https://x", wait="load"), 1)


async def test_evaluate_raises_jserror_on_page_exception(tmp_path):
    browser = _browser(tmp_path)
    browser.cdp.replies["Runtime.evaluate"] = {
        "exceptionDetails": {"exception": {"description": "ReferenceError: nope is not defined"}}
    }
    with pytest.raises(JSError, match="nope is not defined"):
        await browser.evaluate("nope()")


async def test_serve_unblocks_on_event(tmp_path):
    browser = _browser(tmp_path)
    done = asyncio.Event()
    task = asyncio.create_task(browser.serve(until=done))
    await asyncio.sleep(0)
    assert not task.done()
    done.set()
    assert await asyncio.wait_for(task, 1) == "until"


async def test_serve_unblocks_when_window_closes(tmp_path):
    browser = _browser(tmp_path)
    browser._target_id = "t1"
    task = asyncio.create_task(browser.serve())
    await asyncio.sleep(0)
    browser._on_target_destroyed({"targetId": "other-tab"})
    await asyncio.sleep(0)
    assert not task.done()
    browser._on_target_destroyed({"targetId": "t1"})
    assert await asyncio.wait_for(task, 1) == "page-closed"


async def test_serve_unblocks_on_connection_close(tmp_path):
    browser = _browser(tmp_path)
    task = asyncio.create_task(browser.serve(until=asyncio.Event()))
    await asyncio.sleep(0)
    browser.cdp._closed.set()  # window closed -> CDP connection gone
    assert await asyncio.wait_for(task, 1) == "connection-lost"


async def test_aclose_asks_browser_to_exit_before_terminating(tmp_path):
    browser = _browser(tmp_path)
    await browser.aclose()
    assert browser.cdp.sent[0][0] == "Browser.close"  # orderly exit first
    assert browser.cdp._closed.is_set()


class TargetsStubCDP(StubCDP):
    """targets() serves scripted batches; the last batch repeats."""

    def __init__(self, batches):
        super().__init__()
        self.batches = list(batches)

    async def targets(self):
        return self.batches.pop(0) if len(self.batches) > 1 else self.batches[0]

    async def create_target(self, url):
        self.sent.append(("Target.createTarget", {"url": url}, None))
        return "created"


async def test_primary_target_prefers_launch_tab_over_restored(tmp_path):
    browser = Browser(LaunchSpec(profile=tmp_path / "p"))
    browser.handle = SimpleNamespace(primary_url="file:///scratch/blank.html")
    cdp = TargetsStubCDP(
        [
            [
                {"type": "page", "url": "about:blank", "targetId": "restored"},
                {"type": "page", "url": "file:///scratch/blank.html", "targetId": "launch-tab"},
            ]
        ]
    )
    assert await browser._primary_target(cdp) == "launch-tab"


async def test_primary_target_waits_for_lagging_launch_tab(tmp_path):
    browser = Browser(LaunchSpec(profile=tmp_path / "p"))
    browser.handle = SimpleNamespace(primary_url="file:///scratch/blank.html")
    cdp = TargetsStubCDP(
        [
            [{"type": "page", "url": "about:blank", "targetId": "restored"}],
            [
                {"type": "page", "url": "about:blank", "targetId": "restored"},
                {"type": "page", "url": "file:///scratch/blank.html", "targetId": "launch-tab"},
            ],
        ]
    )
    assert await browser._primary_target(cdp) == "launch-tab"


async def test_primary_target_without_marker_keeps_old_behavior(tmp_path):
    browser = Browser(LaunchSpec(profile=tmp_path / "p"))
    cdp = TargetsStubCDP([[{"type": "page", "url": "about:blank", "targetId": "first"}]])
    assert await browser._primary_target(cdp) == "first"
    cdp = TargetsStubCDP([[]])
    assert await browser._primary_target(cdp) == "created"


async def test_notify_sends_no_reply(tmp_path):
    browser = _browser(tmp_path)

    @browser.command()
    def fire(params: dict):
        return "ignored"

    payload = json.dumps({"id": None, "command": "fire", "params": {}})
    await browser._binding_handler(browser._session_id)({"name": _BINDING, "payload": payload, "executionContextId": 7})
    assert browser.cdp.sent == []


async def test_other_bindings_are_ignored(tmp_path):
    browser = _browser(tmp_path)
    await browser._binding_handler(browser._session_id)({"name": "someone_else", "payload": "{}", "executionContextId": 1})
    assert browser.cdp.sent == []


async def test_unknown_command_still_gets_error_reply(tmp_path):
    browser = _browser(tmp_path)
    payload = json.dumps({"id": "js2", "command": "nope", "params": {}})
    await browser._binding_handler(browser._session_id)({"name": _BINDING, "payload": payload, "executionContextId": 3})

    _, params, _ = browser.cdp.sent[-1]
    assert _delivered(params)["error"]["type"] == "UnknownCommand"


async def test_worker_binding_sets_caller_context(tmp_path):
    from chauffeur import caller

    browser = _browser(tmp_path)
    seen = {}

    @browser.command()
    def whoami(params: dict) -> str:
        c = caller()
        seen["ext"] = c.extension_id
        seen["is_ext"] = c.is_extension
        return "ok"

    # A binding handler bound to a worker session + extension id (what
    # _on_attached wires up for an extension service worker).
    handler = browser._binding_handler("worker-sess", extension_id="abcdef")
    payload = json.dumps({"id": "w1", "command": "whoami", "params": {}})
    await handler({"name": _BINDING, "payload": payload, "executionContextId": 1})

    assert seen == {"ext": "abcdef", "is_ext": True}
    assert browser.cdp.sent[-1][2] == "worker-sess"  # reply delivered to the worker session


async def test_caller_is_none_outside_dispatch():
    from chauffeur import caller

    assert caller() is None


async def test_page_binding_has_no_extension_id(tmp_path):
    from chauffeur import caller

    browser = _browser(tmp_path)
    seen = {}

    @browser.command()
    def whoami(params: dict) -> str:
        seen["ext"] = caller().extension_id
        return "ok"

    payload = json.dumps({"id": "p1", "command": "whoami", "params": {}})
    await browser._binding_handler(browser._session_id)({"name": _BINDING, "payload": payload})
    assert seen["ext"] is None


def test_extension_without_worker_raises(tmp_path):
    browser = _browser(tmp_path)
    with pytest.raises(LookupError, match="no attached service worker"):
        browser.extension("nope")


async def test_on_attached_installs_and_readopts_worker(tmp_path):
    browser = _browser(tmp_path)
    browser.extension_ids = ["abcdef"]
    worker = {"targetInfo": {"type": "service_worker", "url": "chrome-extension://abcdef/sw.js"}}

    await browser._on_attached({**worker, "sessionId": "w1"})
    assert browser._ext_sessions["abcdef"] == "w1"
    assert ("Runtime.addBinding", {"name": _BINDING}, "w1") in browser.cdp.sent
    assert ("Runtime.runIfWaitingForDebugger", None, "w1") in browser.cdp.sent  # resumed

    # Respawn: the worker reappears as a new target/session; it is re-adopted.
    await browser._on_attached({**worker, "sessionId": "w2"})
    assert browser._ext_sessions["abcdef"] == "w2"
    assert ("Runtime.addBinding", {"name": _BINDING}, "w2") in browser.cdp.sent


async def test_on_attached_ignores_foreign_worker_but_resumes_it(tmp_path):
    browser = _browser(tmp_path)
    browser.extension_ids = ["abcdef"]
    other = {"targetInfo": {"type": "service_worker", "url": "chrome-extension://other/sw.js"}, "sessionId": "w9"}
    await browser._on_attached(other)
    assert "other" not in browser._ext_sessions
    # Still resumed, so a worker we don't own is never left hanging on the debugger.
    assert ("Runtime.runIfWaitingForDebugger", None, "w9") in browser.cdp.sent
    assert not any(m == "Runtime.addBinding" and s == "w9" for m, _, s in browser.cdp.sent)


def test_extension_id_of():
    from chauffeur.browser import _extension_id_of

    assert _extension_id_of("chrome-extension://abcdef/service_worker.js") == "abcdef"
    assert _extension_id_of("chrome-extension://abcdef/") == "abcdef"
    assert _extension_id_of("https://example.com/x") == ""


def test_attach_extensions_defaults_true(tmp_path):
    assert LaunchSpec(profile=tmp_path / "p").attach_extensions is True
    assert LaunchSpec(profile=tmp_path / "p", attach_extensions=False).attach_extensions is False

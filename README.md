<div align="center">

# 🚗 chauffeur

**Drive a local Chromium browser from Python — your launch, your lifecycle, both directions.**

[![CI](https://github.com/michel-tricot/chauffeur/actions/workflows/ci.yml/badge.svg)](https://github.com/michel-tricot/chauffeur/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![Platforms: macOS · Linux](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux-lightgrey.svg)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

</div>

`chauffeur` is a **control plane, not an automation framework** — no selectors,
no waits, no daemon. You decide how the browser spins up, patch and load
extensions, and talk to it in both directions with a decorator-based command
API. Lifecycle is yours to own.

Good for local-first desktop-style apps with a Chromium UI, browser-backed
tooling, extension harnesses, and keeping your own logged-in session alive.

## Features

- 🚀 **Launch your way** — headless or headed, chromeless app windows, any
  installed Chromium (Chrome/Chromium/Brave/Edge), a dedicated profile with
  guardrails against clobbering your real one.
- 🔌 **Bidirectional commands** — `py.call(...)` into Python and
  `browser.call(...)` into JS over one JSON envelope, with dataclass
  validation and error replies that never hang.
- 🧵 **Async or sync** — the async `Browser`, or a drop-in `SyncBrowser` with
  no `async`/`await`.
- 📄 **Local pages, no server** — show an HTML file (with its css/js) over
  `file://`, including UIs packaged inside a wheel.
- 🧩 **Extension patching** — take a local dir or pull one from the Chrome Web
  Store, inject config, rewrite or add files, load over CDP.
- 🕵️ **User-Agent capture/replay** — keep a `cf_clearance` cookie valid across
  headless runs.
- 🪶 **Tiny** — one runtime dependency (`websockets`), no daemon, no magic.

## Install

```bash
uv add chauffeur   # or: pip install chauffeur
```

Requires Python 3.12+ and a Chromium-family browser (Chrome, Chromium, Brave,
or Edge). macOS and Linux.

## Quickstart

```python
import asyncio
from pathlib import Path
from chauffeur import Browser, LaunchSpec


async def main():
    spec = LaunchSpec(profile=Path("~/.myapp/profile"), headless=True)
    async with Browser(spec) as browser:
        print(await browser.evaluate("navigator.userAgent"))


asyncio.run(main())
```

## Launch a browser your way

```python
from pathlib import Path
from chauffeur import Browser, LaunchSpec, Window

spec = LaunchSpec(
    profile=Path("~/.myapp/profile"),   # dedicated profile you own (required)
    browser="auto",                     # or "chrome" / a binary Path
    headless=True,
    devtools_port=0,                    # 0 = pick a free port
    window=Window(size=(390, 320), position="center"),
    minimal_footprint=True,             # trim the process down
    show_browser_ui=False,              # headed windows start clean (default)
)
```

The profile is required on purpose: there is no default, so a launch can
never silently land on the browser profile you use daily. Pointing it at a
real user data dir works, but is deliberate — and logged with a warning,
since chauffeur opens a debugging port on it and rewrites its Preferences.

Headed windows start without the bookmarks bar and open about:blank instead
of the New Tab Page; pass `show_browser_ui=True` to restore Chrome's regular
UI. Tabbed windows always keep the toolbar — `app_url` / `app_page` open a
toolbar-less window.

## Talk to the browser both ways

The browser calls into Python with `py.call(...)`; Python calls into the
browser with `browser.call(...)`. Same JSON envelope in both directions.

```python
from dataclasses import dataclass, field
from chauffeur import Browser, LaunchSpec

browser = Browser(spec)

@dataclass
class SavePassword:
    url: str
    username: str
    secret: str
    tags: list[str] = field(default_factory=list)

@dataclass
class SaveResult:
    ok: bool
    entry_id: str

@browser.command()                       # name defaults to "save_password"
async def save_password(params: SavePassword) -> SaveResult:
    entry = await vault.store(params.url, params.username, params.secret)
    return SaveResult(ok=True, entry_id=entry.id)

@browser.command("get_config")
def get_config(params: dict):            # annotate with dict for the raw payload
    return {"theme": "dark"}

@browser.on("Page.frameNavigated")       # raw CDP events stay dicts
async def navigated(event: dict):
    print("now at", event["frame"]["url"])

async def main():
    async with browser:
        # Python -> browser
        await browser.call("refresh_ui", {"section": "vault"})
        await browser.serve()            # block until the browser closes
```

Prefer no `async`/`await`? `SyncBrowser` is a drop-in synchronous facade over
the same core (it runs the event loop on a background thread); every method
loses its `a`-prefix — `browser.evaluate(...)`, `browser.call(...)`,
`browser.serve()` — and `@command`/`@on` handlers still work (they run on the
loop thread, so keep them quick).

Browser side (injected `py` global is available in every document):

```javascript
const res = await py.call("save_password", {url, username, secret});
py.notify("telemetry", {event: "unlock"});   // fire-and-forget, no reply
py.on("refresh_ui", async ({section}) => { /* handles browser.call() */ });
```

Annotate a handler's `params` with a dataclass and you get a validated
dataclass; annotate it with `dict` (or leave it off) and you get the raw
payload. Dataclass return values are serialized back automatically. Unknown
commands, bad params, and handler exceptions always produce an error reply so a
`await py.call(...)` never hangs.

## Show a local page — no server

Point the browser at an HTML file; its relative css/js/images load over
file://. `app_page` opens it as a chromeless app window, `page` as a tab:

```python
spec = LaunchSpec(profile=..., headless=False, app_page=Path("ui/app.html"))
```

Packaged UIs work the same — pass an importlib.resources traversable and
chauffeur extracts it (siblings included) for the browser's lifetime, even
from a zipped install:

```python
from importlib.resources import files

spec = LaunchSpec(profile=..., app_page=files("myapp") / "ui" / "app.html")
```

With `Browser`, the page is navigated only after the py channel is installed,
so its scripts can call `py.on(...)` / `py.notify(...)` from their first line.

## Patch and load an extension

The source is a local unpacked directory or an id pulled from the Chrome Web
Store; both take the same patches:

An `ExtensionSpec` describes the source and the patches; you hand it to
`LaunchSpec.extensions` and the launch builds it for you (call
`build_extension(spec, workdir)` yourself only if you want the dir directly).

```python
from chauffeur import ExtensionSpec, find_installed_extension

# local: an unpacked dir, or a copy from an installed browser
ext = ExtensionSpec(find_installed_extension("pejdijmoenmkgeppbflobdenhhabjlaj"))

# or pull it from the Web Store by id (downloaded once, cached)
ext = ExtensionSpec.from_store("pejdijmoenmkgeppbflobdenhhabjlaj")

ext = (
    ext
    .inject_config("background.js", {"port": 8765, "token": "…"})  # prepend a config global
    .append("background.js", bridge_js)                            # modify an existing file
    .add_file("content/inject.js", inject_js)                      # add a new file
    .patch_manifest(lambda m: {**m, "name": m["name"] + " (patched)"})
)
spec = LaunchSpec(profile=..., extensions=(ext,))
```

The build lands beside the profile (`<profile>.extensions/<name>`) — one
path anchors all of the app's browser state, nothing to configure twice —
and is rebuilt on every launch, so a bumped installed version is picked up
automatically. Loading happens over CDP (`Extensions.loadUnpacked`, ids on
`browser.extension_ids`) because branded Chrome 137+ silently ignores
`--load-extension`; this means extensions load when driving the browser
through `Browser`, not bare `launch()`.

## Replay a captured User-Agent (Cloudflare)

Headless Chromium sends a `HeadlessChrome/x.y` UA that Cloudflare rejects, and a
`cf_clearance` cookie earned in a headed login is bound to the exact UA that
session sent. Capture the real UA during login, then replay it on headless runs:

```python
# 1. Headed login — capture the real UA once the user is signed in.
login = LaunchSpec(profile=profile, headless=False, app_url="https://example.com/login")
async with Browser(login) as browser:
    await wait_until_signed_in(browser)
    await browser.capture_user_agent()      # writes <profile>.ua

# 2. Headless runs — replay it automatically.
work = LaunchSpec(profile=profile, headless=True, user_agent="auto")
async with Browser(work) as browser:
    ...                                      # same profile, same UA, cookie stays valid
```

`user_agent="auto"` replays the cached UA (Headless marker stripped) on headless
launches only — headed browsers send their real UA. Pass an explicit string to
force one verbatim, or leave it `None` (default) to not touch the UA at all. If
nothing was captured, replay falls back to a per-platform reconstruction, so a
missing capture never breaks a launch.

## Examples

Runnable, self-contained scripts live in [`examples/`](examples/) — from a
one-liner launch to a live-updating packaged UI and Web Store extension
patching. Run any with `uv run examples/<name>/main.py`.

## License

MIT © Michel Tricot

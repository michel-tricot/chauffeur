<div align="center">

# 🚗 chauffeur

**A Python control plane for a local Chromium browser you launch and own.**

[![PyPI](https://img.shields.io/pypi/v/chauffeur.svg)](https://pypi.org/project/chauffeur/)
[![CI](https://github.com/michel-tricot/chauffeur/actions/workflows/ci.yml/badge.svg)](https://github.com/michel-tricot/chauffeur/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![Platforms: macOS · Linux](https://img.shields.io/badge/platform-macOS%20%C2%B7%20Linux-lightgrey.svg)

</div>

`chauffeur` is a **control plane, not an automation framework**. You decide how the browser spins up, patch and load
extensions, and talk to it in both directions with a decorator-based command
API.

## Why chauffeur?

Reach for it when you want a real browser engine under Python control, without
a selector-based automation framework or an Electron-sized bundle. Things
people build with it:

- **Desktop-style apps with a web UI.** Ship an HTML/CSS/JS front end backed by
  Python in a chromeless window, using the browser already on the machine: a
  local dashboard, a media organizer, a password vault.
- **Tools that reuse your real logged-in session.** Sign in once in a headed
  window, then run headless against the same profile with the cookies and
  User-Agent intact, including sites behind Cloudflare or an MFA wall.
- **Extension harnesses.** Pull an extension from the Web Store or a local dir,
  patch it, load it, and drive or observe it from Python for testing or to add
  behavior.
- **Browser-backed jobs.** Render pages, run real JavaScript, or reach web APIs
  from a genuine engine, orchestrated by Python instead of a headless HTTP
  client.
- **Human-in-the-loop flows.** Open a window for someone to sign in or approve
  something, then take back over programmatically.

## Features

- 🚀 **Launch your way.** Headless or headed, chromeless app windows, any
  installed Chromium (Chrome, Chromium, Brave, Edge). A dedicated profile with
  guardrails against clobbering your real one.
- 🔌 **Bidirectional commands.** `py_chauffeur.call(...)` into Python and
  `browser.call(...)` into JS over one JSON envelope, with dataclass
  validation and error replies that never hang.
- 🧵 **Async or sync.** The async `Browser`, or a drop-in `SyncBrowser` with no
  `async`/`await`.
- 📄 **Local pages, no server.** Show an HTML file (with its css/js) over
  `file://`, including UIs packaged inside a wheel.
- 🧩 **Extension patching.** Take a local dir or pull one from the Chrome Web
  Store, inject config, rewrite or add files, load over CDP.
- 🕵️ **User-Agent capture and replay.** Keep a `cf_clearance` cookie valid
  across headless runs.
- 🪶 **Tiny.** One runtime dependency (`websockets`) and no daemon.

## Install

```bash
uv add chauffeur   # or: pip install chauffeur
```

Requires Python 3.12+ and a Chromium-family browser (Chrome, Chromium, Brave,
or Edge). macOS and Linux.

## Quickstart

Register a Python command, then have the browser call it and get a reply:

```python
import asyncio
from pathlib import Path
from chauffeur import Browser, LaunchSpec


async def main():
    browser = Browser(LaunchSpec(profile=Path("~/.myapp/profile")))

    # the page can call this via py_chauffeur.call("greet", ...)
    @browser.command()
    def greet(params: dict) -> str:
        return f"Hello, {params['name']}!"

    async with browser:
        reply = await browser.evaluate(
            "py_chauffeur.call('greet', {name: 'world'})"
        )
        print(reply)  # -> Hello, world!


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
    show_browser_ui=False,              # present as an app/dialog, not a browser
)
```

The profile is required on purpose: there is no default, so a launch can
never silently land on the browser profile you use daily. Pointing it at a
real user data dir works but must be deliberate, and it logs a warning, since
chauffeur opens a debugging port on it and rewrites its Preferences.

Headed windows start clean by default, with no bookmarks bar or startup
clutter, so a window reads as an app or dialog rather than a browser. Pass
`show_browser_ui=True` for Chrome's normal browsing UI, or use `app_url` /
`app_page` for a fully chromeless window.

## Talk to the browser both ways

The browser calls into Python with `py_chauffeur.call(...)`; Python calls into the
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
the same core (it runs the event loop on a background thread). Every method
loses its `a`-prefix (`browser.evaluate(...)`, `browser.call(...)`,
`browser.serve()`), and `@command`/`@on` handlers still work. They run on the
loop thread, so keep them quick.

Browser side (injected `py_chauffeur` global is available in every document):

```javascript
const res = await py_chauffeur.call("save_password", {url, username, secret});
py_chauffeur.notify("telemetry", {event: "unlock"});   // fire-and-forget, no reply
py_chauffeur.on("refresh_ui", async ({section}) => { /* handles browser.call() */ });
```

Annotate a handler's `params` with a dataclass and you get a validated
dataclass; annotate it with `dict` (or leave it off) and you get the raw
payload. Dataclass return values are serialized back automatically. Unknown
commands, bad params, and handler exceptions always produce an error reply so a
`await py_chauffeur.call(...)` never hangs.

## Show a local page, no server

Point the browser at an HTML file; its relative css/js/images load over
file://. `app_page` opens it as a chromeless app window, `page` as a tab:

```python
spec = LaunchSpec(profile=..., headless=False, app_page=Path("ui/app.html"))
```

Packaged UIs work the same way: pass an importlib.resources traversable and
chauffeur extracts it (siblings included) for the browser's lifetime, even
from a zipped install:

```python
from importlib.resources import files

spec = LaunchSpec(profile=..., app_page=files("myapp") / "ui" / "app.html")
```

With `Browser`, the page is navigated only after the py_chauffeur channel is installed,
so its scripts can call `py_chauffeur.on(...)` / `py_chauffeur.notify(...)` from their first line.

## Patch and load an extension

An `ExtensionSpec` describes a source and the patches to apply. The source is
a local unpacked directory or an id pulled from the Chrome Web Store; both
take the same patches. Hand the spec to `LaunchSpec.extensions` and the launch
builds it for you (call `build_extension(spec, workdir)` yourself only if you
want the dir directly).

```python
from chauffeur import ExtensionSpec, find_installed_extension

# local: an unpacked dir, or a copy from an installed browser
ext = ExtensionSpec(find_installed_extension("pejdijmoenmkgeppbflobdenhhabjlaj"))

# or pull it from the Web Store by id (downloaded once, cached)
ext = ExtensionSpec.from_store("pejdijmoenmkgeppbflobdenhhabjlaj")

ext = (
    ext
    .inject_config("background.js", {"port": 8765, "token": "..."})  # prepend a config global
    .append("background.js", bridge_js)                            # modify an existing file
    .add_file("content/inject.js", inject_js)                      # add a new file
    .patch_manifest(lambda m: {**m, "name": m["name"] + " (patched)"})
)
spec = LaunchSpec(profile=..., extensions=(ext,))
```

The build lands beside the profile (`<profile>.extensions/<name>`), so one
path anchors all of the app's browser state with nothing to configure twice,
and it is rebuilt on every launch so a bumped installed version is picked up
automatically. Loading happens over CDP (`Extensions.loadUnpacked`, ids on
`browser.extension_ids`) because branded Chrome 137+ silently ignores
`--load-extension`. Extensions therefore load when driving the browser
through `Browser`, not bare `launch()`.

## Replay a captured User-Agent (Cloudflare)

Headless Chromium sends a `HeadlessChrome/x.y` UA that Cloudflare rejects, and a
`cf_clearance` cookie earned in a headed login is bound to the exact UA that
session sent. Capture the real UA during login, then replay it on headless runs:

```python
# 1. Headed login: capture the real UA once the user is signed in.
login = LaunchSpec(profile=profile, headless=False, app_url="https://example.com/login")
async with Browser(login) as browser:
    await wait_until_signed_in(browser)
    await browser.capture_user_agent()      # writes <profile>.ua

# 2. Headless runs: replay it automatically.
work = LaunchSpec(profile=profile, headless=True, user_agent="auto")
async with Browser(work) as browser:
    ...                                      # same profile, same UA, cookie stays valid
```

`user_agent="auto"` replays the cached UA (Headless marker stripped) on headless
launches only; headed browsers send their real UA. Pass an explicit string to
force one verbatim, or leave it `None` (default) to not touch the UA at all. If
nothing was captured, replay falls back to a per-platform reconstruction, so a
missing capture never breaks a launch.

## Examples

Runnable, self-contained scripts live in [`examples/`](examples/), from a
one-liner launch to a live-updating packaged UI and Web Store extension
patching. Run any with `uv run examples/<name>/main.py`.

## Contributing

Contributions are welcome. The project uses [uv](https://docs.astral.sh/uv/)
for everything. Set up a checkout:

```bash
git clone https://github.com/michel-tricot/chauffeur
cd chauffeur
uv sync --dev            # runtime + dev tools into .venv
```

Day-to-day commands:

```bash
uv run pytest            # tests (no real browser needed; the CDP layer is faked)
uv run ruff check .      # lint (add --fix to autofix)
uv run ty check          # type check (chauffeur/ only)
uv run deptry .          # dependency check
```

Lint, types, and tests run in CI across Python 3.12 to 3.14 and must pass
before a change lands. Run an example against a real browser:

```bash
uv run examples/01_headless_launch_and_evaluate/main.py
```

Work on the docs (MkDocs Material):

```bash
uv sync --group docs
uv run mkdocs serve      # live preview at http://127.0.0.1:8000
```

If you change public API, usage, or the pitch, update the README and the
matching page under `docs/` in the same PR; the API reference is generated
from docstrings. See [`AGENTS.md`](AGENTS.md) for architecture notes,
conventions, and the release process.

## License

MIT © Michel Tricot

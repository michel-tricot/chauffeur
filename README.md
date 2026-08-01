# chauffeur

Control a local Chromium-family browser from Python. You decide how it spins
up, patch and load extensions, and talk to it in **both directions** with a
decorator-based command API.

`chauffeur` is a control plane, not an automation framework — there are no
selectors or waits, and no daemon. Lifecycle is the consumer's to own.

## Install

```bash
uv add chauffeur   # or: pip install chauffeur
```

Requires Python 3.11+ and a Chromium-family browser (Chrome, Chromium, Brave,
or Edge). macOS and Linux.

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

```python
from chauffeur import ExtensionBuild, find_installed_extension

src = find_installed_extension("pejdijmoenmkgeppbflobdenhhabjlaj")
ext = (
    ExtensionBuild(src, workdir=Path("~/.myapp/extension").expanduser())
    .inject_config("background.js", {"port": 8765, "token": "…"})
    .append("background.js", bridge_js)
    .patch_manifest(lambda m: {**m, "name": m["name"] + " (patched)"})
)
spec = LaunchSpec(profile=..., load_extensions=(ext.build(),))
```

`build()` is idempotent and re-copies from source, so a bumped installed
version is picked up on the next run.

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

## License

MIT

# Guide

## Launch a browser your way

```python
from pathlib import Path
from chauffeur import Browser, LaunchSpec, Window

spec = LaunchSpec(
    profile=Path("~/.myapp/profile"),   # dedicated profile you own (required)
    browser="auto",                     # or "chrome" / a binary Path
    headless=True,
    devtools_port=0,                    # 0 = pick a free port
    window=Window(size=(390, 320), position="center"),  # or "top" / "dialog" (above center)
    minimal_footprint=True,             # trim the process down
    show_browser_ui=False,              # present as an app/dialog, not a browser
)

async with Browser(spec) as browser:    # launches here; exiting closes it
    await browser.navigate("https://example.com")
```

Entering the `async with` block launches the browser, connects over CDP, and
installs the `py_chauffeur` channel; leaving it shuts everything down. If you
only want the process — no channel, no CDP client — bare `launch(spec)` returns
a `BrowserHandle` with the DevTools port and a `terminate()` method.

The profile is required on purpose: there is no default, so a launch can never
silently land on the browser profile you use daily. Pointing it at a real user
data dir works but must be deliberate, and it logs a warning, since chauffeur
opens a debugging port on it and rewrites its Preferences.

Headed windows start clean by default, with no bookmarks bar or startup
clutter, so a window reads as an app or dialog rather than a browser. Pass
`show_browser_ui=True` for Chrome's normal browsing UI, or use `app=True` for a
fully chromeless window.

## Talk to the browser both ways

The browser calls into Python with `py_chauffeur.call(...)`; Python calls into
the browser with `browser.call(...)`. Same JSON envelope in both directions.

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

Browser side (the injected `py_chauffeur` global is available in every
document):

```javascript
const res = await py_chauffeur.call("save_password", {url, username, secret});
py_chauffeur.notify("telemetry", {event: "unlock"});   // fire-and-forget, no reply
py_chauffeur.on("refresh_ui", async ({section}) => { /* handles browser.call() */ });
```

Annotate a handler's `params` with a dataclass and you get a validated
dataclass; annotate it with `dict` (or leave it off) and you get the raw
payload. Dataclass return values are serialized back automatically. Unknown
commands, bad params, and handler exceptions always produce an error reply, so
`await py_chauffeur.call(...)` never hangs.

!!! note "Synchronous variant"
    `SyncBrowser` mirrors `Browser` without `async`/`await`: it runs the event
    loop on a background thread. Every method loses its `a`-prefix
    (`browser.evaluate(...)`, `browser.call(...)`, `browser.serve()`), and
    `@command`/`@on` handlers still work. They run on the loop thread, so keep
    them quick.

## Show a local page, no server

Point `url` at an HTML file (a `Path`); its relative css/js/images load over
`file://`. Add `app=True` for a chromeless app window, or omit it for a tab:

```python
spec = LaunchSpec(profile=..., headless=False, url=Path("ui/app.html"), app=True)
```

Packaged UIs work the same way: pass an `importlib.resources` traversable and
chauffeur extracts it (siblings included) for the browser's lifetime, even from
a zipped install:

```python
from importlib.resources import files

spec = LaunchSpec(profile=..., url=files("myapp") / "ui" / "app.html", app=True)
```

With `Browser`, the page is navigated only after the `py_chauffeur` channel is
installed, so its scripts can call `py_chauffeur.on(...)` /
`py_chauffeur.notify(...)` from their first line.

!!! warning "file:// and CORS"
    Relative css/js/images load fine, but `fetch()` and ES modules are
    CORS-blocked from a `file://` origin unless the remote sends permissive
    CORS. Route data through `py_chauffeur.call` instead of adding
    `--disable-web-security`.

## Patch and load an extension

An `ExtensionSpec` describes a source and the patches to apply. The source is a
local unpacked directory or an id pulled from the Chrome Web Store; both take
the same patches. Hand the spec to `LaunchSpec.extensions` and the launch builds
it for you (call `build_extension(spec, workdir)` yourself only if you want the
dir directly).

```python
from chauffeur import ExtensionSpec

# local: any unpacked extension directory (packaged with your app or on disk)
ext = ExtensionSpec("path/to/unpacked-extension")

# or pull it from the Web Store by id (downloaded once, cached). refresh=True
# re-downloads on each launch and keeps the cache when the store is unreachable;
# cache_dir= pins the pristine download to a fixed location
ext = ExtensionSpec.from_store("pejdijmoenmkgeppbflobdenhhabjlaj", refresh=True)

ext = (
    ext
    .inject_config("background.js", {"port": 8765, "token": "..."})  # prepend a config global
    .append("background.js", bridge_js)                              # modify an existing file
    .add_file("content/inject.js", inject_js)                        # add a new file
    .patch_manifest(lambda m: {**m, "name": m["name"] + " (patched)"})
)
spec = LaunchSpec(profile=..., extensions=(ext,))
```

The build lands beside the profile (`<profile>.extensions/<name>`), so one path
anchors all of the app's browser state with nothing to configure twice, and it
is rebuilt on every launch so a bumped installed version is picked up
automatically. Loading happens over CDP (`Extensions.loadUnpacked`, ids on
`browser.extension_ids`) because branded Chrome 137+ silently ignores
`--load-extension`. Extensions therefore load when driving the browser through
`Browser`, not bare `launch()`.

### Talk to an extension's service worker

Loading an extension also gives its MV3 service worker a `py_chauffeur` channel,
installed before the worker's own code runs and re-installed if the worker
respawns. So the extension's worker can call your `@command` handlers, and you
can drive handlers it registered:

```python
# In the worker (e.g. background.js), py_chauffeur is already available:
#   py_chauffeur.on("sign", async ({payload}) => { ... });
#   py_chauffeur.call("worker_ready", {});     // -> your @browser.command

async with browser:
    ext_id = browser.extension_ids[0]
    signed = await browser.extension(ext_id).call("sign", {"payload": data})
```

Inbound worker calls land in the shared command registry; `caller()` tells a
handler which extension invoked it (`caller().extension_id`). Pass
`ExtensionSpec(..., worker_channel=False)` to load an extension without a channel.

Service workers attach lazily and can be evicted and respawned, so the channel
may not exist the instant an extension loads. `browser.extension(id)` raises
`LookupError` until the worker has attached; poll `browser.extension_ready(id)`
(or let inbound calls arrive first) before the first Python -> worker call.

Chrome evicts an idle MV3 worker after ~30 seconds, and eviction loses the
worker's in-memory state and stalls its in-flight work. While a worker holds a
channel, chauffeur therefore keeps it awake with a cheap liveness poke every
`keep_alive` seconds (default 25, driven from Python — an in-worker timer would
itself be suspended). Tune it per extension:

```python
ExtensionSpec(source, keep_alive=2.0)   # aggressive: protect short-lived in-flight state
ExtensionSpec(source, keep_alive=None)  # allow dormancy; a respawn re-installs the
                                        # channel, but the worker's state is gone
```

## Replay a captured User-Agent (Cloudflare)

Headless Chromium sends a `HeadlessChrome/x.y` UA that Cloudflare rejects, and a
`cf_clearance` cookie earned in a headed login is bound to the exact UA that
session sent. Capture the real UA during login, then replay it on headless runs:

```python
# 1. Headed login: capture the real UA once the user is signed in.
login = LaunchSpec(profile=profile, headless=False, url="https://example.com/login")
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

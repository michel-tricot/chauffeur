# AGENTS.md

Guidance for AI coding agents (and new contributors) working on chauffeur.

## What this is

A Python control plane for local Chromium-family browsers: launching
(`spec.py` + `launch.py`), an async CDP client (`cdp.py`), a bidirectional
JSON command channel (`browser.py` + `js/py.js`), extension discovery and
patching (`extension.py`), UA capture/replay (`ua.py`), and local-page /
app-window support. No selectors, no waits, no daemon — consumers own the
lifecycle.

## Commands

- Tests: `uv run pytest`
- Lint: `uv run ruff check .` (autofix with `--fix`)
- Types: `uv run ty check` — gates `chauffeur/` only; tests are excluded on
  purpose (they stub internals)
- Examples: `uv run examples/<name>/main.py` — directories are numbered in
  reading order and tagged by kind: `*_headless_*` are safe to run
  unattended, `*_ui_*` open a real window and block until it is closed.

All three checks must pass before a change is done. CI
(`.github/workflows/ci.yml`) runs lint, types, deptry, and tests on
Python 3.12–3.14; unit tests never need a browser, so they pass on bare
runners.

## Architecture notes

- `browser.py` is the façade: launches via `launch.py`, connects `cdp.py`,
  attaches to the primary target, and installs the channel
  (`Runtime.addBinding` + `js/py.js`). Command replies are delivered into the
  execution context that made the call — iframes have their own `py` object.
- `dispatch.py` + `serde.py`: command registry and dataclass ↔ JSON
  validation. Wire types are deliberately limited to what survives a JSON
  round trip; schema mistakes fail at decoration time, not on first message.
- `page` / `app_page` on `LaunchSpec` are resolved in `launch.py`
  (`_prepare_pages`): packaged (zip/wheel) resources are extracted — siblings
  included — for the browser's lifetime via an `ExitStack` on
  `BrowserHandle`. With `Browser`, navigation is deferred until the channel
  is installed so page scripts can use `py.*` from their first line.
- `Browser.serve()` unblocks on: primary window/tab closed, CDP connection
  dropped, or an optional `until` event.
- `SyncBrowser` (`chauffeur/sync.py`) is a synchronous facade — it runs the
  async core on a background thread and bridges via
  `run_coroutine_threadsafe`; do not fork a second CDP implementation for it.
  Its `serve(until=threading.Event)` bridges the threading event onto a
  loop-owned `asyncio.Event`. Registered handlers run on the loop thread.

## Gotchas (learned the hard way)

- Chrome silently ignores `--app=about:blank` and opens a *tabbed* window;
  deferred app pages therefore launch on a real placeholder file.
- `ExtensionBuild` source is a local dir (a Path) or `from_store(id)` which
  downloads the CRX from the Chrome Web Store (`download_extension`, cached
  in `<profile>.extensions/<id>.src`) and strips the CRX2/CRX3 header. Patch
  ops: inject_config/append/patch modify existing files, add_file adds new
  ones, patch_manifest edits the manifest.
- Branded Google Chrome 137+ silently ignores `--load-extension`, so
  chauffeur never uses it: `LaunchSpec.extensions` builds into
  `<profile>.extensions/<key>` at launch and `Browser.start()` loads each
  over CDP (`Extensions.loadUnpacked`). Chromium and
  dev builds still honor the flag.
- On macOS the browser process outlives its last window. "User closed the
  app" is detected via `Target.targetDestroyed` on the primary target — the
  connection dropping is not a reliable close signal.
- `file://` pages: relative css/js/images load fine; `fetch()` and ES modules
  are CORS-blocked (opaque origin) unless the remote sends permissive CORS.
  Route data through `py.call` instead. Never add `--disable-web-security`.
- The DevTools port is unauthenticated and `py.js` is injected into every
  document: treat incoming commands as untrusted input.
- `LaunchSpec.profile` is required by design — never give it a default, so a
  launch can never silently target someone's daily browser profile. Pointing
  it at a real user data dir is allowed but deliberate; `launch()` logs a
  warning when it happens (`_warn_if_real_profile`).
- The New Tab Page force-shows the bookmarks bar; bare headed launches open
  `about:blank` instead, and the bar is disabled via profile Preferences
  (`_apply_ui_prefs`) unless `show_browser_ui=True`.

## Conventions

- Comments state constraints the code can't express; the sanctioned
  best-effort `try/except` patterns are documented in the pyproject lint
  ignores — don't "fix" them, and don't add new broad excepts outside
  cleanup/delivery paths.
- Unit tests never launch a real browser: the websocket is faked
  (`tests/test_cdp.py` `FakeWS`) and the CDP client stubbed
  (`tests/test_browser_channel.py` `StubCDP`). Behavior needing a real
  browser is exercised by the examples.
- Many ruff groups are enabled at zero violations — keep them there; fix
  findings rather than adding ignores unless the pattern is deliberate and
  gets a comment.

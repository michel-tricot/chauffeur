# Examples

One directory per example, numbered in reading order and tagged by kind:
`*_headless_*` run unattended in a terminal; `*_ui_*` open a real window
(desktop session required) and block until you close it. Run any of them from
the repo root:

```bash
uv run examples/01_headless_launch_and_evaluate/main.py
```

Ordered roughly by depth — headless fundamentals, then windowed UIs, then the
more advanced extension use cases last.

| Example | Shows |
| --- | --- |
| `00_headless_list_browsers` | Which Chromium-family browsers chauffeur can drive |
| `01_headless_launch_and_evaluate` | Launch headless, evaluate JS, clean shutdown |
| `02_headless_bidirectional` | `py.call` into Python commands, `browser.call` into JS handlers, dataclass validation, error replies |
| `03_headless_cdp_events` | Raw CDP event listeners; `py` surviving navigation |
| `04_headless_ua_capture_replay` | Capture a User-Agent and replay it with the Headless marker stripped |
| `05_headless_sync_browser` | The synchronous `SyncBrowser` API — same capabilities, no async/await |
| `06_ui_app_window` | A centered chromeless app window; its button counts clicks and notifies Python |
| `07_ui_packaged_ui` | A local page with separate css/js via `app_page`, shown as a modal dialog; close it from the UI |
| `08_ui_live_updates` | Python pushes updates into the page every second — clock, load average, pulse |
| `09_headless_extension_build` | Patch a local extension with `ExtensionBuild` and load it via `Extensions.loadUnpacked` |
| `10_headless_extension_store` | Pull an extension from the Chrome Web Store by id, patch it, and load it (needs network) |

All examples use a throwaway profile in a temp directory; nothing touches your
real browser profile.

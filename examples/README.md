# Examples

One directory per example, each a self-contained script. The prefix tells you
what to expect: `headless_*` run unattended in a terminal; `ui_*` open a real
window (desktop session required) and block until you close it. Run any of
them from the repo root:

```bash
uv run examples/headless_01_launch_and_evaluate/main.py
```

## Headless — safe to run anywhere

| Example | Shows |
| --- | --- |
| `headless_00_list_browsers` | Which Chromium-family browsers chauffeur can drive |
| `headless_01_launch_and_evaluate` | Launch headless, evaluate JS, clean shutdown |
| `headless_02_bidirectional` | `py.call` into Python commands, `browser.call` into JS handlers, dataclass validation, error replies |
| `headless_03_cdp_events` | Raw CDP event listeners; `py` surviving navigation |
| `headless_05_extension_build` | Patch an extension with `ExtensionBuild` and load it via `Extensions.loadUnpacked` |
| `headless_06_ua_capture_replay` | Capture a User-Agent and replay it with the Headless marker stripped |

## UI — opens a window

| Example | Shows |
| --- | --- |
| `ui_04_app_window` | A centered chromeless app window; its button counts clicks and notifies Python |
| `ui_07_packaged_ui` | A local page with separate css/js via `app_page`, shown as a modal dialog; close it from the UI |
| `ui_08_live_updates` | Python pushes updates into the page every second — clock, load average, pulse |

All examples use a throwaway profile in a temp directory; nothing touches your
real browser profile.

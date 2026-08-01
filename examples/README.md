# Examples

One directory per example, each a self-contained script. Run any of them from
the repo root:

```bash
uv run examples/01_launch_and_evaluate/main.py
```

| Example | Shows |
| --- | --- |
| `00_list_browsers` | Which Chromium-family browsers chauffeur can drive |
| `01_launch_and_evaluate` | Launch headless, evaluate JS, clean shutdown |
| `02_bidirectional` | `py.call` into Python commands, `browser.call` into JS handlers, dataclass validation, error replies |
| `03_cdp_events` | Raw CDP event listeners; `py` surviving navigation |
| `04_app_window` | A small centered app window whose button notifies Python (needs a desktop session) |
| `05_extension_build` | Patch an extension with `ExtensionBuild` and load it via `Extensions.loadUnpacked` |
| `06_ua_capture_replay` | Capture a User-Agent and replay it with the Headless marker stripped |
| `07_packaged_ui` | A local page with separate css/js via `app_page` — no server, `py` available at load; close it from a UI button (needs a desktop session) |
| `08_live_updates` | Python pushes updates into the page every second — clock, load average, pulse (needs a desktop session) |

All of them use a throwaway profile in a temp directory and a headless browser —
except `04_app_window`, `07_packaged_ui`, and `08_live_updates`, which open a
real window and block until you close it (or click 07's button).

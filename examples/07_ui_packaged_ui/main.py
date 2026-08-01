"""Show a local page, HTML with separate CSS and JS, without a server.

LaunchSpec(app_page=...) (or page=... for a tab) takes an HTML file; sibling
css/js load relatively over file://. A filesystem Path is used in place, and
an importlib.resources traversable (data packaged in a wheel/zip) is
extracted automatically for the browser's lifetime:

    LaunchSpec(profile=..., app_page=files("myapp") / "ui" / "app.html")

With Browser, the page is navigated only after the py channel is installed,
so its scripts can use py.on / py.notify from their first line, no polling.

Headed: needs a desktop session. The UI starts as a native modal <dialog>
(shown via showModal() at load); closing it (the button or the Esc key) shuts
everything down.

    uv run examples/07_ui_packaged_ui/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec, Window

HTML = """<!doctype html>
<html>
<head>
  <title>packaged ui</title>
  <link rel="stylesheet" href="style.css">
  <script defer src="app.js"></script>
</head>
<body>
  <dialog id="dlg">
    <h1 id="status">booting...</h1>
    <form method="dialog"><button>Close</button></form>
  </dialog>
</body>
</html>
"""

CSS = """:root { color-scheme: dark; }
body {
  margin: 0; height: 100vh;
  background: radial-gradient(120% 90% at 50% -10%, #1e293b, #0f172a);
}
dialog {
  font-family: system-ui;
  text-align: center;
  padding: 2rem 2.6rem;
  border: 1px solid rgb(148 163 184 / 0.18);
  border-radius: 1rem;
  background: linear-gradient(180deg, #253044, #1b2334);
  color: #e2e8f0;
  box-shadow: 0 24px 60px rgb(0 0 0 / 0.6);
}
dialog::backdrop { background: rgb(2 6 23 / 0.6); backdrop-filter: blur(4px); }
h1 { margin: 0 0 1.4rem; font-size: 1.05rem; font-weight: 600; color: #cbd5e1; }
button {
  font-size: 1rem; font-weight: 600; padding: 0.7rem 1.3rem; border: none;
  border-radius: 0.7rem; background: #6366f1; color: #fff; cursor: pointer;
  box-shadow: 0 8px 24px rgb(99 102 241 / 0.3);
  transition: background 0.15s, transform 0.05s;
}
button:hover { background: #818cf8; }
button:active { transform: translateY(1px); }
button:focus-visible { outline: 2px solid rgb(129 140 248 / 0.7); outline-offset: 3px; }
"""

JS = """const dlg = document.querySelector("#dlg");
py.on("set_status", async ({ text }) => {
  document.querySelector("#status").textContent = text;
  return "status set to: " + text;
});
// Fires for the form button and for Esc alike.
dlg.addEventListener("close", () => py.notify("close_clicked", {}));
dlg.showModal();
py.notify("ui_ready", { title: document.title });
"""


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ui = Path(tmp) / "ui"
        ui.mkdir()
        (ui / "app.html").write_text(HTML)
        (ui / "style.css").write_text(CSS)
        (ui / "app.js").write_text(JS)

        spec = LaunchSpec(
            profile=Path(tmp) / "profile",
            headless=False,
            app_page=ui / "app.html",
            window=Window(size=(460, 300), position="center"),
        )
        browser = Browser(spec)
        ready = asyncio.Event()
        done = asyncio.Event()

        @browser.command()
        def ui_ready(params: dict) -> None:
            print("page says it is ready:", params)
            ready.set()

        @browser.command()
        def close_clicked() -> None:
            print("dialog closed, shutting down")
            done.set()

        async with browser:
            await asyncio.wait_for(ready.wait(), timeout=15)
            print("js replied:", await browser.call("set_status", {"text": "close this dialog to exit"}))
            # Unblocks on the dialog closing OR the window being closed.
            await browser.serve(until=done)
        print("bye")


if __name__ == "__main__":
    asyncio.run(main())

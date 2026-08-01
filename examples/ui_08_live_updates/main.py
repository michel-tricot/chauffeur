"""Python pushes live updates into the page, once a second.

The visible direction of the channel: a Python loop calls
browser.call("tick", {...}) and the page's handler updates the DOM — clock,
load average, update counter, and a pulse on every beat. The page never
polls; Python drives.

Headed: needs a desktop session. Close the window to exit.

    uv run examples/ui_08_live_updates/main.py
"""

import asyncio
import contextlib
import os
import tempfile
import time
from pathlib import Path

from chauffeur import Browser, LaunchSpec, Window

HTML = """<!doctype html>
<html>
<head>
  <title>chauffeur live</title>
  <link rel="stylesheet" href="style.css">
  <script defer src="app.js"></script>
</head>
<body>
<main>
  <header><span id="dot"></span>fed by Python</header>
  <div id="clock">--:--:--</div>
  <div class="row">
    <div class="card"><div class="label">load avg</div><div id="load" class="value">-</div></div>
    <div class="card"><div class="label">updates</div><div id="beats" class="value">0</div></div>
  </div>
</main>
</body>
</html>
"""

CSS = """:root { color-scheme: dark; }
body {
  margin: 0; height: 100vh; display: grid; place-items: center;
  background: radial-gradient(120% 90% at 50% -10%, #1e293b, #0f172a);
  color: #e2e8f0; font-family: system-ui;
}
main { text-align: center; display: grid; gap: 1.2rem; }
header {
  display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  font-size: 0.85rem; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase; color: #94a3b8;
}
#dot {
  width: 0.55rem; height: 0.55rem; border-radius: 50%;
  background: #475569;
}
#dot.pulse { animation: pulse 0.9s ease-out; }
@keyframes pulse {
  0% { background: #4ade80; box-shadow: 0 0 0 0 rgb(74 222 128 / 0.6); }
  100% { background: #475569; box-shadow: 0 0 0 0.7rem rgb(74 222 128 / 0); }
}
#clock {
  font-size: 3.4rem; font-weight: 700;
  font-variant-numeric: tabular-nums; letter-spacing: 0.02em;
}
.row { display: flex; gap: 0.8rem; justify-content: center; }
.card {
  background: rgb(148 163 184 / 0.08); border: 1px solid rgb(148 163 184 / 0.15);
  border-radius: 0.8rem; padding: 0.8rem 1.4rem; min-width: 6.5rem;
}
.label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em;
         color: #94a3b8; margin-bottom: 0.2rem; }
.value { font-size: 1.5rem; font-weight: 700; font-variant-numeric: tabular-nums; }
"""

JS = """const $ = (sel) => document.querySelector(sel);
py.on("tick", async ({ clock, load, beats }) => {
  $("#clock").textContent = clock;
  $("#load").textContent = load.toFixed(2);
  $("#beats").textContent = beats;
  const dot = $("#dot");
  dot.classList.remove("pulse");
  void dot.offsetWidth;  // restart the animation
  dot.classList.add("pulse");
});
py.notify("ui_ready", {});
"""


async def feed(browser: Browser) -> None:
    beats = 0
    while True:
        beats += 1
        payload = {
            "clock": time.strftime("%H:%M:%S"),
            "load": os.getloadavg()[0],
            "beats": beats,
        }
        with contextlib.suppress(Exception):  # window may be mid-close
            await browser.call("tick", payload)
        await asyncio.sleep(1)


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
            window=Window(size=(420, 340), position="center"),
        )
        browser = Browser(spec)
        ready = asyncio.Event()

        @browser.command()
        def ui_ready() -> None:
            ready.set()

        async with browser:
            await asyncio.wait_for(ready.wait(), timeout=15)
            print("feeding the page — close the window to exit")
            feeder = asyncio.create_task(feed(browser))
            await browser.serve()
            feeder.cancel()
        print("bye")


if __name__ == "__main__":
    asyncio.run(main())

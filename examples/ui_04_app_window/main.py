"""Open a small centered app window whose button talks to Python.

Headed: needs a desktop session (macOS or Linux with a display). The window
is chromeless (--app), sized and centered by the spec. Close it to exit.

    uv run examples/ui_04_app_window/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec, Window

PAGE = """<!doctype html>
<html>
<head>
<title>chauffeur</title>
<style>
  :root { color-scheme: dark; }
  body {
    margin: 0; height: 100vh; display: grid; place-items: center;
    background: radial-gradient(120% 90% at 50% -10%, #1e293b, #0f172a);
    color: #e2e8f0; font-family: system-ui;
  }
  main { text-align: center; display: grid; gap: 1.1rem; }
  h1 { margin: 0; font-size: 0.95rem; font-weight: 600; letter-spacing: 0.06em;
       text-transform: uppercase; color: #94a3b8; }
  #count { font-size: 3rem; font-weight: 700; font-variant-numeric: tabular-nums; }
  button {
    font-size: 1rem; font-weight: 600; padding: 0.8rem 1.4rem; border: none;
    border-radius: 0.7rem; background: #6366f1; color: #fff; cursor: pointer;
    box-shadow: 0 8px 24px rgb(99 102 241 / 0.35);
    transition: background 0.15s, transform 0.05s;
  }
  button:hover { background: #818cf8; }
  button:active { transform: translateY(1px); }
</style>
</head>
<body>
<main>
  <h1>clicks seen by Python</h1>
  <div id="count">0</div>
  <button id="btn">Tell Python about it</button>
</main>
<script>
  let n = 0;
  document.querySelector("#btn").addEventListener("click", () => {
    document.querySelector("#count").textContent = ++n;
    py.notify("clicked", { count: n });
  });
</script>
</body>
</html>
"""


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "app.html"
        page.write_text(PAGE)
        spec = LaunchSpec(
            profile=Path(tmp) / "profile",
            headless=False,
            app_page=page,
            window=Window(size=(420, 320), position="center"),
        )
        browser = Browser(spec)

        @browser.command()
        def clicked(params: dict) -> None:
            print("button clicked, count =", params["count"])

        async with browser:
            print("window is up — click the button, close the window to exit")
            await browser.serve()


if __name__ == "__main__":
    asyncio.run(main())

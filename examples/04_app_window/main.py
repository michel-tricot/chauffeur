"""Open a small centered app window whose button talks to Python.

Headed: needs a desktop session (macOS or Linux with a display). The window
is chromeless (--app), sized and centered by the spec. Close it to exit.

    uv run examples/04_app_window/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec, Window

PAGE = """<!doctype html>
<title>chauffeur</title>
<body style="font-family: system-ui; display: grid; place-items: center; height: 90vh">
  <button style="font-size: 1.1rem; padding: 0.8rem 1.2rem"
          onclick="py.notify('clicked', {count: ++this.dataset.n || (this.dataset.n = 1)})">
    Tell Python about it
  </button>
</body>
"""


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "app.html"
        page.write_text(PAGE)
        spec = LaunchSpec(
            profile=Path(tmp) / "profile",
            headless=False,
            app_url=page.as_uri(),
            window=Window(size=(420, 260), position="center"),
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

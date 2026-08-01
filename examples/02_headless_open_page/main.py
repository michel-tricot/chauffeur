"""Point the browser at a page with `url`, then read from it.

`url` takes a string URL used verbatim (http(s)://, file://, chrome://, ...),
a local Path, or a packaged importlib.resources traversable. It opens as a
chromeless app window by default; pass `app=False` for a normal browser tab
(the difference is only visible when headed).

Needs network (loads example.com). Swap in any URL, or a local Path.

    uv run examples/02_headless_open_page/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec = LaunchSpec(profile=Path(tmp) / "profile", headless=True, url="https://example.com")
        async with Browser(spec) as browser:
            print("title:", await browser.evaluate("document.title"))
            print("heading:", await browser.evaluate("document.querySelector('h1')?.textContent"))
            print("url:", await browser.evaluate("location.href"))


if __name__ == "__main__":
    asyncio.run(main())

"""Subscribe to raw CDP events while driving navigation.

@browser.on(...) delivers any DevTools event as a plain dict. The py channel
is re-injected on every new document, so it survives navigation.

    uv run examples/headless_03_cdp_events/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        pages = []
        for name in ("first", "second"):
            page = Path(tmp) / f"{name}.html"
            page.write_text(f"<!doctype html><title>{name}</title><h1>{name}</h1>")
            pages.append(page)

        browser = Browser(LaunchSpec(profile=Path(tmp) / "profile", headless=True))
        loaded = asyncio.Event()

        @browser.on("Page.frameNavigated")
        def on_navigated(event: dict) -> None:
            frame = event["frame"]
            if "parentId" not in frame:  # top frame only
                print("navigated:", frame["url"])

        @browser.on("Page.loadEventFired")
        def on_loaded(_event: dict) -> None:
            loaded.set()

        async with browser:
            for page in pages:
                loaded.clear()
                await browser.navigate(page.as_uri())
                await loaded.wait()
                print("  title:", await browser.evaluate("document.title"))
                print("  py is still a", await browser.evaluate("typeof py"))


if __name__ == "__main__":
    asyncio.run(main())

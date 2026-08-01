"""Launch a headless browser, run some JS in it, and shut it down.

    uv run examples/01_headless_launch_and_evaluate/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        spec = LaunchSpec(profile=Path(tmp) / "profile", headless=True)
        async with Browser(spec) as browser:
            print("user agent:", await browser.evaluate("navigator.userAgent"))
            print("2 + 2 =", await browser.evaluate("2 + 2"))
            print("promise:", await browser.evaluate("Promise.resolve('promises are awaited by default')"))


if __name__ == "__main__":
    asyncio.run(main())

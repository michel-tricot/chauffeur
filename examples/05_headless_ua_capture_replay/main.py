"""Capture a browser's User-Agent and replay it on a later headless run.

The real flow captures during a *headed* login so a Cloudflare cf_clearance
cookie stays bound to the UA that earned it (see the README). To stay
self-contained this captures from a headless browser, the cache holds the
HeadlessChrome marker, and replay strips it.

    uv run examples/05_headless_ua_capture_replay/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, LaunchSpec
from chauffeur.ua import ua_cache_path


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        profile = Path(tmp) / "profile"

        async with Browser(LaunchSpec(profile=profile, headless=True)) as browser:
            captured = await browser.capture_user_agent()
            print("captured:", captured)
        print("cached at:", ua_cache_path(profile))

        async with Browser(LaunchSpec(profile=profile, headless=True, user_agent="auto")) as browser:
            print("replayed:", await browser.evaluate("navigator.userAgent"))


if __name__ == "__main__":
    asyncio.run(main())

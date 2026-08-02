"""Talk to the browser in both directions with the same JSON envelope.

Python registers commands with @browser.command; the page calls them with
py_chauffeur.call(...). The page registers handlers with py_chauffeur.on(...); Python calls them
with browser.call(...). Dataclass annotations get validated params and
serialized results; bad input comes back as a rejection, never a hang.

    uv run examples/03_headless_bidirectional/main.py
"""

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from chauffeur import Browser, LaunchSpec


@dataclass
class Bookmark:
    url: str
    title: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Saved:
    ok: bool
    entry_id: str


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        browser = Browser(LaunchSpec(profile=Path(tmp) / "profile", headless=True))
        vault: list[Bookmark] = []

        @browser.command()
        async def save_bookmark(params: Bookmark) -> Saved:
            vault.append(params)
            return Saved(ok=True, entry_id=f"bm-{len(vault)}")

        @browser.command()
        def stats() -> dict:  # handlers can also take no params at all
            return {"saved": len(vault)}

        async with browser:
            # Browser -> Python: the page calls py_chauffeur.call and awaits the reply.
            saved = await browser.evaluate("py_chauffeur.call('save_bookmark', {url: 'https://example.com', title: 'Example', tags: ['demo']})")
            print("page got:", saved)
            print("stats:", await browser.evaluate("py_chauffeur.call('stats')"))

            # Validation errors come back as rejections with a type, not hangs.
            err = await browser.evaluate("py_chauffeur.call('save_bookmark', {url: 42}).catch(e => `${e.type}: ${e.message}`)")
            print("bad params ->", err)

            # Python -> browser: the page registers a handler, Python calls it.
            await browser.evaluate("py_chauffeur.on('shout', async ({text}) => text.toUpperCase())")
            print("browser said:", await browser.call("shout", {"text": "hello from python"}))


if __name__ == "__main__":
    asyncio.run(main())

# chauffeur

**A Python control plane for a local Chromium browser you launch and own.**

`chauffeur` is a control plane, not an automation framework: no selectors, no
waits, no daemon. You decide how the browser spins up, patch and load
extensions, and talk to it in both directions with a decorator-based command
API. Starting and stopping the browser is your job, not the library's.

Use it for local-first apps with a Chromium UI, browser-backed tooling,
extension harnesses, or keeping your own logged-in session alive.

## Install

```bash
uv add chauffeur   # or: pip install chauffeur
```

Requires Python 3.12+ and a Chromium-family browser (Chrome, Chromium, Brave,
or Edge). macOS and Linux.

## Quickstart

Register a Python command, then have the browser call it and get a reply:

```python
import asyncio
from pathlib import Path
from chauffeur import Browser, LaunchSpec


async def main():
    browser = Browser(LaunchSpec(profile=Path("~/.myapp/profile"), headless=True))

    @browser.command()                       # the page can now call py_chauffeur.call("greet", ...)
    def greet(params: dict) -> str:
        return f"Hello, {params['name']}!"

    async with browser:
        reply = await browser.evaluate("py_chauffeur.call('greet', {name: 'world'})")
        print(reply)                         # -> Hello, world!


asyncio.run(main())
```

Prefer no `async`/`await`? [`SyncBrowser`](reference.md#chauffeur.SyncBrowser) is
a drop-in synchronous facade over the same core.

## Where to next

- **[Guide](guide.md)** — launching, the bidirectional command API, local
  pages, extension patching, and User-Agent replay.
- **[API reference](reference.md)** — every public class and function,
  generated from the source.
- **Examples** — runnable scripts in
  [`examples/`](https://github.com/michel-tricot/chauffeur/tree/main/examples).

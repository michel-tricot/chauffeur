# chauffeur

**A Python control plane for a local Chromium browser you launch and own.**

`chauffeur` is a **control plane, not an automation framework**. You decide how
the browser spins up, patch and load extensions, and talk to it in both
directions with a decorator-based command API.

## Why chauffeur?

Reach for it when you want a real browser engine under Python control, without
a selector-based automation framework or an Electron-sized bundle. Things
people build with it:

- **Desktop-style apps with a web UI.** Ship an HTML/CSS/JS front end backed by
  Python in a chromeless window, using the browser already on the machine: a
  local dashboard, a media organizer, a password vault.
- **Tools that reuse your real logged-in session.** Sign in once in a headed
  window, then run headless against the same profile with the cookies and
  User-Agent intact, including sites behind Cloudflare or an MFA wall.
- **Extension harnesses.** Pull an extension from the Web Store or a local dir,
  patch it, load it, and drive or observe it from Python for testing or to add
  behavior.
- **Browser-backed jobs.** Render pages, run real JavaScript, or reach web APIs
  from a genuine engine, orchestrated by Python instead of a headless HTTP
  client.
- **Human-in-the-loop flows.** Open a window for someone to sign in or approve
  something, then take back over programmatically.

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
    browser = Browser(LaunchSpec(profile=Path("~/.myapp/profile")))

    # the page can call this via py_chauffeur.call("greet", ...)
    @browser.command()
    def greet(params: dict) -> str:
        return f"Hello, {params['name']}!"

    async with browser:
        reply = await browser.evaluate(
            "py_chauffeur.call('greet', {name: 'world'})"
        )
        print(reply)  # -> Hello, world!


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

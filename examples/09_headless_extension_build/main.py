"""Patch a local extension, load it, and watch the injection change behavior.

A tiny hello-world extension ships a page whose script greets whoever
globalThis.__chauffeur_config says, defaulting to "stranger". We inject that
config at build time, so the extension's own code greets "chauffeur" instead,
and it proves it ran by calling the Python `greet` command over the channel.

chauffeur builds the spec into <profile>.extensions/<name> and loads it over
CDP (branded Chrome 137+ ignores --load-extension). We then point the primary
page at the extension's own chrome-extension:// page, where `py_chauffeur` is available.

    uv run examples/09_headless_extension_build/main.py
"""

import asyncio
import json
import tempfile
from pathlib import Path

from chauffeur import Browser, ExtensionSpec, LaunchSpec

MANIFEST = {"manifest_version": 3, "name": "chauffeur hello", "version": "1.0.0"}

HELLO_HTML = '<!doctype html><meta charset="utf-8"><title>hello</title><h1 id="msg">...</h1><script src="hello.js"></script>'

# The extension's own behavior: greet whoever the injected config names, and
# prove it ran by calling back into Python.
HELLO_JS = """const name = globalThis.__chauffeur_config?.name ?? "stranger";
(async () => {
  const reply = await py_chauffeur.call("greet", { name });
  document.querySelector("#msg").textContent = reply;
})();
"""


def make_source(root: Path) -> Path:
    src = root / "ext-src"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps(MANIFEST, indent=2))
    (src / "hello.html").write_text(HELLO_HTML)
    (src / "hello.js").write_text(HELLO_JS)
    return src


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Without inject_config the page would greet "stranger"; injecting the
        # config changes what the extension's own code does.
        ext = ExtensionSpec(make_source(root)).inject_config("hello.js", {"name": "chauffeur"})
        spec = LaunchSpec(profile=root / "profile", headless=True, extensions=(ext,))
        browser = Browser(spec)

        @browser.command()
        def greet(params: dict) -> str:
            print("[python] extension called greet with:", params)
            return f"Hello from Python, {params['name']}!"

        async with browser:
            ext_id = browser.extension_ids[0]
            print("loaded extension:", ext_id)
            await browser.navigate(f"chrome-extension://{ext_id}/hello.html")
            for _ in range(25):  # wait for the page script to call greet and render
                msg = await browser.evaluate("document.querySelector('#msg')?.textContent")
                if msg and msg != "...":
                    break
                await asyncio.sleep(0.2)
            print("[page]   shows:", msg)


if __name__ == "__main__":
    asyncio.run(main())

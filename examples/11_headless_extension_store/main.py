"""Pull a real extension from the Chrome Web Store, add to it, and drive it.

ExtensionSpec.from_store(id) downloads the CRX by id (cached in
<profile>.extensions/<id>.src). A downloaded extension's own filenames aren't
known up front, so we add_file our own page + script, inject config into it,
and let it prove it ran by calling the Python `greet` command, the same
build+load path as the local example, on a real store extension.

Needs network (reaches the Chrome Web Store). Extension: JSON Formatter (a
small, plain hello-world-sized MV3 extension). Swap EXTENSION_ID for any id.

    uv run examples/11_headless_extension_store/main.py
"""

import asyncio
import tempfile
from pathlib import Path

from chauffeur import Browser, ExtensionSpec, LaunchSpec

EXTENSION_ID = "bcjindcccaagfpapjjmafapmmgkkhgoa"  # JSON Formatter (small, MV3)

HELLO_HTML = '<!doctype html><meta charset="utf-8"><title>hello</title><h1 id="msg">...</h1><script src="chauffeur_hello.js"></script>'

HELLO_JS = """const name = globalThis.__chauffeur_config?.name ?? "stranger";
(async () => {
  const reply = await py_chauffeur.call("greet", { name });
  document.querySelector("#msg").textContent = reply;
})();
"""


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ext = (
            ExtensionSpec.from_store(EXTENSION_ID)
            .add_file("chauffeur_hello.html", HELLO_HTML)
            .add_file("chauffeur_hello.js", HELLO_JS)
            .inject_config("chauffeur_hello.js", {"name": "chauffeur"})
        )
        spec = LaunchSpec(profile=Path(tmp) / "profile", headless=True, extensions=(ext,))
        browser = Browser(spec)

        @browser.command()
        def greet(params: dict) -> str:
            print("[python] added page called greet with:", params)
            return f"Hello from Python, {params['name']}!"

        async with browser:
            ext_id = browser.extension_ids[0]
            print("pulled + built:", browser.handle.extensions[0].name, "-> id", ext_id)
            await browser.navigate(f"chrome-extension://{ext_id}/chauffeur_hello.html")
            for _ in range(25):  # wait for the added page to call greet and render
                msg = await browser.evaluate("document.querySelector('#msg')?.textContent")
                if msg and msg != "...":
                    break
                await asyncio.sleep(0.2)
            print("[page]   shows:", msg)


if __name__ == "__main__":
    asyncio.run(main())

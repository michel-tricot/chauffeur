"""Talk to an extension's service worker over py_chauffeur, no page involved.

When chauffeur loads an extension it auto-attaches the extension's service
worker and installs py_chauffeur there before the worker's own code runs. So
the worker can call Python commands (worker -> Python), and Python can drive
handlers the worker registered via browser.extension(id) (Python -> worker).
caller() tells a command which extension invoked it. This is the channel a
daemon would otherwise hand-roll with a WebSocket server.

Set ExtensionSpec(src, worker_channel=False) to load one without a channel.

    uv run examples/12_headless_extension_worker/main.py
"""

import asyncio
import json
import tempfile
from pathlib import Path

from chauffeur import Browser, ExtensionSpec, LaunchSpec, caller

MANIFEST = {
    "manifest_version": 3,
    "name": "worker channel demo",
    "version": "1.0.0",
    "background": {"service_worker": "sw.js"},
}

# The worker's own top-level code uses py_chauffeur, which proves it is present
# before the worker runs. No page, no content script, no WebSocket.
SW = """
py_chauffeur.on("add", async ({ a, b }) => a + b);              // Python -> worker
py_chauffeur.call("worker_ready", { where: "service_worker" });  // worker -> Python
"""


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "ext"
        src.mkdir()
        (src / "manifest.json").write_text(json.dumps(MANIFEST))
        (src / "sw.js").write_text(SW)

        browser = Browser(LaunchSpec(profile=Path(tmp) / "profile", headless=True, extensions=(ExtensionSpec(src),)))
        ready = asyncio.Event()

        @browser.command()
        def worker_ready(params: dict) -> str:
            print("worker -> Python  worker_ready:", params, "from extension", caller().extension_id)
            ready.set()
            return "ack"

        async with browser:
            ext_id = browser.extension_ids[0]
            print("loaded extension:", ext_id)
            await asyncio.wait_for(ready.wait(), 10)  # inbound worked
            result = await browser.extension(ext_id).call("add", {"a": 2, "b": 40})
            print("Python -> worker  add(2, 40) =", result)


if __name__ == "__main__":
    asyncio.run(main())

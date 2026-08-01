"""Pull an extension from the Chrome Web Store, patch it, and load it.

ExtensionSpec.from_store(id) downloads the CRX by id (cached in
<profile>.extensions/<id>.src), and the same patch pipeline applies: here we
add a marker file, since a downloaded extension's own filenames aren't known
up front. chauffeur builds it beside the profile and loads it over CDP.

Needs network (reaches the Chrome Web Store). Extension used: uBlock Origin
Lite. Swap EXTENSION_ID for any other Web Store id.

    uv run examples/10_headless_extension_store/main.py
"""

import asyncio
import json
import tempfile
from pathlib import Path

from chauffeur import Browser, ExtensionSpec, LaunchSpec

EXTENSION_ID = "ddkjiahejlhfcafbddmgiahcphecmpfh"  # uBlock Origin Lite


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        ext = ExtensionSpec.from_store(EXTENSION_ID).add_file(
            "chauffeur_marker.js", "console.log('added by chauffeur');"
        )
        spec = LaunchSpec(profile=Path(tmp) / "profile", headless=True, extensions=(ext,))
        async with Browser(spec) as browser:
            built = browser.handle.extensions[0]
            manifest = json.loads((built / "manifest.json").read_text())
            print("pulled:", manifest.get("name"), manifest.get("version"))
            print("built at:", built)
            print("marker added:", (built / "chauffeur_marker.js").is_file())
            print("loaded id:", browser.extension_ids[0])


if __name__ == "__main__":
    asyncio.run(main())

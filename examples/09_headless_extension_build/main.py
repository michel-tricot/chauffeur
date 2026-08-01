"""Patch an extension and let the launch pipeline build and load it.

Creates a throwaway MV3 extension so the example is self-contained, then
hands the ExtensionBuild to LaunchSpec.extensions: chauffeur builds it into
<profile>.extensions/<name> on every launch (so a bumped installed version
is always picked up) and loads it over CDP with Extensions.loadUnpacked —
branded Chrome 137+ ignores --load-extension, so CDP is the reliable path.
To patch a real installed extension instead, replace the generated source
with find_installed_extension("<extension id>").

    uv run examples/09_headless_extension_build/main.py
"""

import asyncio
import json
import tempfile
from pathlib import Path

from chauffeur import Browser, ExtensionBuild, LaunchSpec

MANIFEST = {
    "manifest_version": 3,
    "name": "chauffeur demo",
    "version": "1.0.0",
    "background": {"service_worker": "background.js"},
}


def make_source(root: Path) -> Path:
    src = root / "ext-src"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps(MANIFEST, indent=2))
    (src / "background.js").write_text('console.log("demo extension: config is", globalThis.__chauffeur_config);\n')
    return src


async def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ext = (
            ExtensionBuild(make_source(root))  # no workdir: built beside the profile
            .inject_config("background.js", {"endpoint": "http://127.0.0.1:8765", "token": "demo"})
            .append("background.js", 'console.log("bridge appended by chauffeur");')
            .patch_manifest(lambda m: {**m, "name": m["name"] + " (patched)"})
        )
        spec = LaunchSpec(profile=root / "profile", headless=True, extensions=(ext,))
        async with Browser(spec) as browser:
            built = browser.handle.extensions[0]
            print("built at:", built)
            print("--- patched background.js ---")
            print((built / "background.js").read_text())
            print("loaded, id:", browser.extension_ids[0])
            for _ in range(20):  # the service worker can take a beat to spin up
                ours = [t for t in await browser.cdp.targets() if t["url"].endswith("/background.js")]
                if ours:
                    break
                await asyncio.sleep(0.3)
            for target in ours:
                print("running:", target["type"], target["url"])


if __name__ == "__main__":
    asyncio.run(main())

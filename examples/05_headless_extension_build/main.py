"""Patch an extension with ExtensionBuild and load it at launch.

Creates a throwaway MV3 extension so the example is self-contained, then runs
the real pipeline: copy to a workdir, inject config, append bridge code,
rewrite the manifest, and load the build into a headless browser. To patch a
real installed extension instead, replace the generated source with
find_installed_extension("<extension id>").

    uv run examples/05_headless_extension_build/main.py
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
        built = (
            ExtensionBuild(make_source(root), workdir=root / "ext-build")
            .inject_config("background.js", {"endpoint": "http://127.0.0.1:8765", "token": "demo"})
            .append("background.js", 'console.log("bridge appended by chauffeur");')
            .patch_manifest(lambda m: {**m, "name": m["name"] + " (patched)"})
            .build()
        )
        print("--- patched background.js ---")
        print((built / "background.js").read_text())
        print("--- patched name:", json.loads((built / "manifest.json").read_text())["name"])

        # Branded Chrome (137+) ignores --load-extension, so load over CDP;
        # extension_debugging=True adds the flag Extensions.loadUnpacked needs.
        # With Chromium/dev builds, load_extensions=(built,) also works.
        spec = LaunchSpec(profile=root / "profile", headless=True, extension_debugging=True)
        async with Browser(spec) as browser:
            loaded = await browser.cdp.send("Extensions.loadUnpacked", {"path": str(built)})
            print("loaded, id:", loaded["id"])
            for _ in range(20):  # the service worker can take a beat to spin up
                ours = [t for t in await browser.cdp.targets() if t["url"].endswith("/background.js")]
                if ours:
                    break
                await asyncio.sleep(0.3)
            for target in ours:
                print("running:", target["type"], target["url"])


if __name__ == "__main__":
    asyncio.run(main())

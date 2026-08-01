"""Discover, copy, and patch Chromium extensions before loading them.

Mirrors the proven flow: find an installed extension by id, copy it to a
working dir, patch files (append bridge code, inject config, rewrite the
manifest), then hand the built path to launch (--load-extension) or to
Extensions.loadUnpacked over CDP.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from chauffeur.browsers import catalog


class ExtensionNotFoundError(RuntimeError):
    """No installed extension matches the id."""


def _version_key(name: str) -> tuple[int, ...]:
    parts = []
    for chunk in name.split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def find_installed_extension(extension_id: str, *, must_contain: str = "manifest.json") -> Path:
    """Highest-version copy of an extension across all installed browser profiles."""
    best: tuple[tuple[int, ...], Path] | None = None
    for browser in catalog():
        if not browser.data_dir or not browser.data_dir.exists():
            continue
        for ext_dir in browser.data_dir.glob(f"*/Extensions/{extension_id}/*"):
            if not (ext_dir / must_contain).exists():
                continue
            key = _version_key(ext_dir.name)
            if best is None or key > best[0]:
                best = (key, ext_dir)
    if best is None:
        raise ExtensionNotFoundError(f"extension {extension_id} not found in any installed browser")
    return best[1]


class ExtensionBuild:
    """A working copy of an extension that can be patched, then built.

    Rebuild is idempotent: build() re-copies from source and re-applies the
    recorded patches, so a bumped installed version is picked up automatically.
    """

    def __init__(self, source: Path, workdir: Path) -> None:
        self.source = source
        self.workdir = workdir
        self._patches: list[Callable[[Path], None]] = []

    def append(self, relative: str, text: str) -> ExtensionBuild:
        def patch(root: Path) -> None:
            target = root / relative
            target.write_text(target.read_text() + "\n" + text)

        self._patches.append(patch)
        return self

    def inject_config(self, relative: str, config: dict) -> ExtensionBuild:
        """Prepend `globalThis.__chauffeur_config = {...}` so appended code can read it."""
        payload = "globalThis.__chauffeur_config = " + json.dumps(config) + ";\n"

        def patch(root: Path) -> None:
            target = root / relative
            target.write_text(payload + target.read_text())

        self._patches.append(patch)
        return self

    def patch(self, relative: str, transform: Callable[[str], str]) -> ExtensionBuild:
        def apply(root: Path) -> None:
            target = root / relative
            target.write_text(transform(target.read_text()))

        self._patches.append(apply)
        return self

    def patch_manifest(self, transform: Callable[[dict], dict]) -> ExtensionBuild:
        def apply(root: Path) -> None:
            path = root / "manifest.json"
            manifest = json.loads(path.read_text())
            path.write_text(json.dumps(transform(manifest), indent=2))

        self._patches.append(apply)
        return self

    def build(self) -> Path:
        source = self.source.expanduser().resolve()
        workdir = self.workdir.expanduser().resolve()
        if workdir == source or source in workdir.parents or workdir in source.parents:
            raise ValueError(f"workdir {workdir} overlaps extension source {source}")
        if workdir.exists():
            # Only delete what looks like a previous build; a mistyped workdir
            # (profile dir, home dir, ...) must not be wiped.
            if not (workdir / "manifest.json").exists():
                raise ValueError(f"refusing to delete {workdir}: not a previous build (no manifest.json)")
            shutil.rmtree(workdir)
        shutil.copytree(source, workdir)
        for patch in self._patches:
            patch(workdir)
        return workdir

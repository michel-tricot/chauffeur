"""Discover, copy, and patch Chromium extensions before loading them.

Mirrors the proven flow: find an installed extension by id, copy it to a
working dir, patch files (append bridge code, inject config, rewrite the
manifest), then hand the built path to launch (--load-extension) or to
Extensions.loadUnpacked over CDP.
"""

from __future__ import annotations

import json
import re
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


def extensions_dir(profile: Path) -> Path:
    """Where derived extension builds live: ``<profile>.extensions`` beside it.

    Same family as the ``<profile>.ua`` sidecar — one profile path anchors
    all of chauffeur's per-app state.
    """
    profile = profile.expanduser()
    return profile.parent / f"{profile.name}.extensions"


class ExtensionBuild:
    """A working copy of an extension that can be patched, then built.

    Rebuild is idempotent: build() re-copies from source and re-applies the
    recorded patches, so a bumped installed version is picked up automatically.
    workdir is optional — hand the build to ``LaunchSpec.extensions`` and it is
    built beside the profile on every launch, keyed by :attr:`key`.
    """

    def __init__(self, source: Path, workdir: Path | None = None) -> None:
        self.source = source
        self.workdir = workdir
        self._patches: list[Callable[[Path], None]] = []

    @property
    def key(self) -> str:
        """Directory slug for derived builds, from the source manifest name."""
        try:
            name = json.loads((self.source / "manifest.json").read_text()).get("name", "")
        except (OSError, ValueError):
            name = ""
        slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
        return slug or "extension"

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

    def build(self, workdir: Path | None = None) -> Path:
        dest = workdir or self.workdir
        if dest is None:
            raise ValueError("no workdir: pass one here or at construction, or launch via LaunchSpec.extensions")
        source = self.source.expanduser().resolve()
        workdir = dest.expanduser().resolve()
        if workdir.is_relative_to(source) or source.is_relative_to(workdir):
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

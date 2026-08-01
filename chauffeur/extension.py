"""Get, patch, and build Chromium extensions before loading them.

An ExtensionSpec describes a source — a local unpacked directory or an id
pulled from the Chrome Web Store (downloaded as a CRX and unzipped) — plus
patches (inject config, append or rewrite existing files, add new files, edit
the manifest). build_extension() materializes it: copy to a working dir,
apply patches, hand the path to Extensions.loadUnpacked over CDP (usually via
LaunchSpec.extensions, which builds each spec beside the profile at launch).
"""

from __future__ import annotations

import io
import json
import re
import shutil
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from chauffeur.browsers import catalog

# Chrome's CRX download endpoint. prodversion just has to look plausible; the
# store does not gate downloads on an exact browser build.
_CRX_ENDPOINT = "https://clients2.google.com/service/update2/crx"
# The store serves an extension only when prodversion >= its
# minimum_chrome_version, and returns an empty 204 otherwise. A deliberately
# high version clears any extension's minimum; override for a specific build.
_STORE_PRODVERSION = "9999.0.0.0"
_CRX2, _CRX3 = 2, 3  # CRX header format versions


class ExtensionNotFoundError(RuntimeError):
    """No extension matches the id (not installed, or not on the store)."""


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "extension"


def _manifest_name(source: Path) -> str:
    try:
        return str(json.loads((source / "manifest.json").read_text()).get("name", ""))
    except (OSError, ValueError):
        return ""


def _crx_to_zip(data: bytes) -> bytes:
    """Strip the CRX2/CRX3 header, leaving the embedded ZIP payload."""
    if data[:2] == b"PK":  # already a bare zip
        return data
    if data[:4] != b"Cr24":
        raise ValueError("not a CRX file (bad magic)")
    version = int.from_bytes(data[4:8], "little")
    if version == _CRX2:
        pubkey_len = int.from_bytes(data[8:12], "little")
        sig_len = int.from_bytes(data[12:16], "little")
        offset = 16 + pubkey_len + sig_len
    elif version == _CRX3:
        header_len = int.from_bytes(data[8:12], "little")
        offset = 12 + header_len
    else:
        raise ValueError(f"unsupported CRX version {version}")
    return data[offset:]


def download_extension(
    extension_id: str, dest: Path, *, prodversion: str = _STORE_PRODVERSION, timeout: float = 30.0
) -> Path:
    """Download an extension from the Chrome Web Store by id and unpack it.

    Fetches the CRX, strips its header, and unzips into ``dest`` (replacing
    any prior contents). Returns ``dest``.
    """
    query = urllib.parse.urlencode(
        {
            "response": "redirect",
            "prodversion": prodversion,
            "acceptformat": "crx2,crx3",
            "x": f"id={extension_id}&installsource=ondemand&uc",
        }
    )
    request = urllib.request.Request(f"{_CRX_ENDPOINT}?{query}", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            crx = resp.read()
    except OSError as exc:
        raise ExtensionNotFoundError(f"could not download extension {extension_id}: {exc}") from exc
    if not crx:  # empty 204: usually prodversion below the extension's minimum
        raise ExtensionNotFoundError(f"store returned no data for {extension_id} (try a higher prodversion)")
    dest = dest.expanduser()
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(_crx_to_zip(crx))) as archive:
        archive.extractall(dest)
    if not (dest / "manifest.json").exists():
        raise ExtensionNotFoundError(f"downloaded extension {extension_id} has no manifest.json")
    return dest


class ExtensionSource:
    """Somewhere an unpacked extension can be obtained from."""

    def key(self) -> str:
        """Stable directory slug for builds derived from this source."""
        raise NotImplementedError

    def resolve(self, cache_dir: Path) -> Path:
        """Return a local directory holding the unpacked extension."""
        raise NotImplementedError


@dataclass(frozen=True)
class LocalExtension(ExtensionSource):
    """An unpacked extension already on disk (e.g. find_installed_extension)."""

    path: Path

    def key(self) -> str:
        return _slug(_manifest_name(self.path.expanduser()))

    def resolve(self, cache_dir: Path) -> Path:  # noqa: ARG002 — local sources ignore the cache
        path = self.path.expanduser().resolve()
        if not (path / "manifest.json").exists():
            raise ExtensionNotFoundError(f"no manifest.json under {path}")
        return path


@dataclass(frozen=True)
class StoreExtension(ExtensionSource):
    """An extension pulled from the Chrome Web Store by id, cached once."""

    extension_id: str
    prodversion: str = _STORE_PRODVERSION

    def key(self) -> str:
        return self.extension_id

    def resolve(self, cache_dir: Path) -> Path:
        cached = cache_dir.expanduser() / f"{self.extension_id}.src"
        if not (cached / "manifest.json").exists():  # download once, then reuse
            download_extension(self.extension_id, cached, prodversion=self.prodversion)
        return cached


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


class ExtensionSpec:
    """A description of an extension to load: a source plus recorded patches.

    The source is a local unpacked directory (pass a Path) or an id pulled
    from the Chrome Web Store (:meth:`from_store`). The chained methods only
    record patches; nothing touches disk until :func:`build_extension` runs —
    usually for you, when the spec is handed to ``LaunchSpec.extensions`` and
    built beside the profile on every launch, keyed by :attr:`key`.

    (It carries closures, so it describes rather than serializes — "spec" here
    means declare-vs-execute, not JSON-able config.)
    """

    def __init__(self, source: Path | str | ExtensionSource) -> None:
        self.source: ExtensionSource = source if isinstance(source, ExtensionSource) else LocalExtension(Path(source))
        self.patches: list[Callable[[Path], None]] = []

    @classmethod
    def from_store(cls, extension_id: str, *, prodversion: str = _STORE_PRODVERSION) -> ExtensionSpec:
        """Describe an extension pulled off the Chrome Web Store by id."""
        return cls(StoreExtension(extension_id, prodversion))

    @property
    def key(self) -> str:
        """Directory slug for derived builds (manifest name, or the store id)."""
        return self.source.key()

    def add_file(self, relative: str, content: str | bytes, *, overwrite: bool = False) -> ExtensionSpec:
        """Add a file to the extension (parents created automatically).

        Refuses to clobber an existing file unless overwrite=True; to append
        to or transform an existing file use append/patch/inject_config.
        """

        def patch(root: Path) -> None:
            target = root / relative
            if target.exists() and not overwrite:
                raise ValueError(f"{relative} already exists; pass overwrite=True or use append()/patch()")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content) if isinstance(content, bytes) else target.write_text(content)

        self.patches.append(patch)
        return self

    def append(self, relative: str, text: str) -> ExtensionSpec:
        def patch(root: Path) -> None:
            target = root / relative
            target.write_text(target.read_text() + "\n" + text)

        self.patches.append(patch)
        return self

    def inject_config(self, relative: str, config: dict) -> ExtensionSpec:
        """Prepend `globalThis.__chauffeur_config = {...}` so appended code can read it."""
        payload = "globalThis.__chauffeur_config = " + json.dumps(config) + ";\n"

        def patch(root: Path) -> None:
            target = root / relative
            target.write_text(payload + target.read_text())

        self.patches.append(patch)
        return self

    def patch(self, relative: str, transform: Callable[[str], str]) -> ExtensionSpec:
        def apply(root: Path) -> None:
            target = root / relative
            target.write_text(transform(target.read_text()))

        self.patches.append(apply)
        return self

    def patch_manifest(self, transform: Callable[[dict], dict]) -> ExtensionSpec:
        def apply(root: Path) -> None:
            path = root / "manifest.json"
            manifest = json.loads(path.read_text())
            path.write_text(json.dumps(transform(manifest), indent=2))

        self.patches.append(apply)
        return self


def build_extension(spec: ExtensionSpec, workdir: Path, *, cache_dir: Path | None = None) -> Path:
    """Materialize ``spec`` into ``workdir`` and return it.

    Copies the (possibly downloaded) source into workdir, then applies the
    recorded patches. Idempotent: re-run to pick up a bumped local source (a
    store download is cached in ``cache_dir``, defaulting beside workdir).
    """
    workdir = workdir.expanduser().resolve()
    cache = Path(cache_dir).expanduser() if cache_dir else workdir.parent
    source = spec.source.resolve(cache).resolve()
    if workdir.is_relative_to(source) or source.is_relative_to(workdir):
        raise ValueError(f"workdir {workdir} overlaps extension source {source}")
    if workdir.exists():
        # Only delete what looks like a previous build; a mistyped workdir
        # (profile dir, home dir, ...) must not be wiped.
        if not (workdir / "manifest.json").exists():
            raise ValueError(f"refusing to delete {workdir}: not a previous build (no manifest.json)")
        shutil.rmtree(workdir)
    shutil.copytree(source, workdir)
    for patch in spec.patches:
        patch(workdir)
    return workdir

"""Declarative description of how a browser should be spun up."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

from chauffeur.extension import ExtensionSpec
from chauffeur.ua import resolve_user_agent

# Trims the process footprint and keeps background pages/service workers
# responsive when headless.
MINIMAL_FOOTPRINT_FLAGS = (
    "--disable-gpu",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-features=Translate",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
)


# Named window positions: each maps to the fraction of the free vertical space
# (screen_height - window_height) left above the window; all are centered
# horizontally. "top" pins it to the top of the screen, "center" leaves equal
# margins, "dialog" sits above center (roughly where the OS places system dialogs).
_NAMED_POSITIONS = {"top": 0.0, "dialog": 1 / 3, "center": 0.5}


@dataclass(frozen=True)
class Window:
    size: tuple[int, int] | None = None
    """Window size in pixels; `None` leaves the browser default."""
    position: tuple[int, int] | Literal["top", "center", "dialog"] | None = None
    """`"top"` pins to the top of the main display, `"center"` centers, `"dialog"`
    sits above center; all center horizontally. Explicit `(x, y)` coordinates
    are used verbatim."""

    def __post_init__(self) -> None:
        # Catch a bad named position at construction rather than as a KeyError
        # deep in launch (the Literal type is not enforced at runtime).
        if isinstance(self.position, str) and self.position not in _NAMED_POSITIONS:
            raise ValueError(f"unknown window position {self.position!r}; use {sorted(_NAMED_POSITIONS)} or (x, y)")


@dataclass
class LaunchSpec:
    profile: Path
    """Profile directory, required by design: with no default, a launch can
    never silently land on a real browser's profile. Targeting one is allowed
    but must be spelled out; `launch()` logs a warning when it is."""
    browser: str | Path = "auto"
    """`"auto"` (first installed browser), a browser id/name (`"chrome"`,
    `"chromium"`, `"brave"`, `"edge"`), or an explicit binary `Path`."""
    headless: bool = True
    """Run without a visible window (`--headless=new`)."""
    devtools_port: int = 0
    """`0` picks a free port at launch."""
    url: str | Path | Traversable | None = None
    """Where to point the browser. A `str` is any URL used verbatim (`file://`,
    `http(s)://`, `chrome://`, `data:`, ...); a `Path` or `importlib.resources`
    traversable is a local page resolved to `file://` (packaged/zipped resources
    are extracted with their sibling css/js for the browser's lifetime). With
    `Browser`, navigation happens after the `py_chauffeur` channel is installed, so
    the page's scripts can use `py_chauffeur.*` from their first line."""
    app: bool = True
    """Open the destination as a chromeless app window (the default); set
    `False` for a normal browser tab. No effect when `url` is `None`."""
    window: Window | None = None
    extensions: tuple[ExtensionSpec | Path, ...] = ()
    """Extensions to load over CDP (`Extensions.loadUnpacked`); branded Chrome
    137+ ignores `--load-extension`, so CDP is the only reliable path and
    loading requires `Browser` (`launch()` alone has no CDP connection).
    An `ExtensionSpec` is built on every launch into `<profile>.extensions/<key>`,
    so a bumped source version is picked up automatically; a plain `Path` loads
    a pre-built directory as-is."""
    minimal_footprint: bool = True
    """Trim the process footprint (no GPU, background networking, sync, ...)
    and keep background pages/service workers responsive when headless."""
    show_browser_ui: bool = False
    """Headed windows start clean by default (no bookmarks bar or startup
    clutter), so a window can be presented as an app or dialog rather than a
    browser; set `True` to show Chrome's normal browsing UI. Ignored when
    headless. For a fully chromeless window, use `app=True`."""
    user_agent: str | Literal["auto"] | None = None
    """UA to present. An explicit string is used verbatim (headed or headless).
    `"auto"` replays the captured UA on headless runs only (headed browsers send
    their real UA); `None` leaves the browser default untouched."""
    extra_flags: tuple[str, ...] = ()
    """Additional command-line flags, appended verbatim."""


def build_args(binary: Path, spec: LaunchSpec, port: int, *, screen: tuple[int, int] | None = None) -> list[str]:
    assert spec.url is None or isinstance(spec.url, str), "resolve a Path/traversable url via launch() first"
    args = [
        str(binary),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={spec.profile.expanduser()}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if spec.headless:
        args.append("--headless=new")
    user_agent = _resolve_ua(binary, spec)
    if user_agent:
        args.append(f"--user-agent={user_agent}")
    if spec.extensions:
        args.append("--enable-unsafe-extension-debugging")
    if spec.minimal_footprint:
        args.extend(MINIMAL_FOOTPRINT_FLAGS)
    if spec.window:
        args.extend(_window_flags(spec.window, screen))
    args.extend(spec.extra_flags)
    if spec.url:
        # --app is a flag; a tab URL must be the trailing positional arg.
        args.append(f"--app={spec.url}" if spec.app else spec.url)
    elif not spec.headless and not spec.show_browser_ui:
        # A bare headed launch would open the New Tab Page, which forces the
        # bookmarks bar (and other clutter) on; start clean instead.
        args.append("about:blank")
    return args


def _resolve_ua(binary: Path, spec: LaunchSpec) -> str | None:
    if spec.user_agent is None:
        return None
    if spec.user_agent == "auto":
        # Headed sessions send their real UA; only override for headless replay.
        return resolve_user_agent(binary, spec.profile) if spec.headless else None
    return spec.user_agent


def _window_flags(window: Window, screen: tuple[int, int] | None) -> list[str]:
    flags = []
    size = window.size or (800, 600)
    if window.size:
        flags.append(f"--window-size={size[0]},{size[1]}")
    position = window.position
    if isinstance(position, str):  # a named position resolves against the screen
        if screen is None:
            position = None
        else:
            frac = _NAMED_POSITIONS[position]
            x = max((screen[0] - size[0]) // 2, 0)
            y = max(int((screen[1] - size[1]) * frac), 0)
            position = (x, y)
    if isinstance(position, tuple):
        flags.append(f"--window-position={position[0]},{position[1]}")
    return flags

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


@dataclass(frozen=True)
class Window:
    size: tuple[int, int] | None = None
    # "center" centers on the main display; "dialog" centers horizontally but sits
    # a third of the way down, where the OS places system dialogs.
    position: tuple[int, int] | Literal["center", "dialog"] | None = None


@dataclass
class LaunchSpec:
    # Profile directory, required by design: with no default, a launch can
    # never silently land on a real browser's profile. Targeting one is
    # allowed but must be spelled out, launch() logs a warning when it is.
    profile: Path
    browser: str | Path = "auto"
    headless: bool = True
    devtools_port: int = 0  # 0 = pick a free port at launch
    url: str | None = None
    app_url: str | None = None  # --app chromeless window; wins over url
    # Local page to show without a server: an HTML file whose relative
    # css/js/image siblings load alongside it over file://. A filesystem Path
    # is used in place; an importlib.resources traversable (data packaged in
    # a wheel/zip) is extracted, siblings included, for the browser's
    # lifetime. With Browser, navigation happens after the py_chauffeur channel is
    # installed, so the page's scripts can use py_chauffeur.* immediately.
    page: Path | Traversable | None = None  # opens as a tab; conflicts with url
    app_page: Path | Traversable | None = None  # chromeless --app window; wins over page
    window: Window | None = None
    # Extensions to load over CDP (Extensions.loadUnpacked), branded Chrome
    # 137+ ignores --load-extension, so CDP is the only reliable path and
    # loading requires Browser (launch() alone has no CDP connection).
    # An ExtensionSpec is built on every launch into <profile>.extensions/<key>,
    # so a bumped installed version is picked up automatically; a plain Path
    # loads a pre-built directory as-is.
    extensions: tuple[ExtensionSpec | Path, ...] = ()
    # Enables Extensions.loadUnpacked; implied by extensions.
    extension_debugging: bool = False
    minimal_footprint: bool = True
    # Headed windows start clean by default (no bookmarks bar or startup
    # clutter), so a window can be presented as an app or dialog rather than a
    # browser; set True to show Chrome's normal browsing UI. Ignored when
    # headless. For a fully chromeless window, use app_url/app_page.
    show_browser_ui: bool = False
    # UA to present. An explicit string is used verbatim (headed or headless).
    # "auto" replays the captured UA on headless runs only (headed browsers
    # send their real UA); None leaves the browser default untouched.
    user_agent: str | Literal["auto"] | None = None
    extra_flags: tuple[str, ...] = ()


def build_args(binary: Path, spec: LaunchSpec, port: int, *, screen: tuple[int, int] | None = None) -> list[str]:
    assert spec.page is None and spec.app_page is None, "resolve page/app_page via launch() first"
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
    if spec.extension_debugging or spec.extensions:
        args.append("--enable-unsafe-extension-debugging")
    if spec.minimal_footprint:
        args.extend(MINIMAL_FOOTPRINT_FLAGS)
    if spec.window:
        args.extend(_window_flags(spec.window, screen))
    if spec.app_url:
        args.append(f"--app={spec.app_url}")
    args.extend(spec.extra_flags)
    if spec.url and not spec.app_url:
        args.append(spec.url)
    elif not spec.app_url and not spec.headless and not spec.show_browser_ui:
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
    if position in ("center", "dialog"):
        if screen is None:
            position = None
        else:
            y_share = 2 if position == "center" else 3  # dialogs sit above center
            position = (max((screen[0] - size[0]) // 2, 0), max((screen[1] - size[1]) // y_share, 0))
    if isinstance(position, tuple):
        flags.append(f"--window-position={position[0]},{position[1]}")
    return flags

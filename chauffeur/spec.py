"""Declarative description of how a browser should be spun up."""

from __future__ import annotations

from dataclasses import dataclass
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

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
    position: tuple[int, int] | Literal["center"] | None = None


@dataclass
class LaunchSpec:
    # Dedicated profile owned by the consumer. Chromium refuses
    # --remote-debugging-port on the default profile, so this is required.
    profile: Path
    browser: str | Path = "auto"
    headless: bool = True
    devtools_port: int = 0  # 0 = pick a free port at launch
    url: str | None = None
    app_url: str | None = None  # --app chromeless window; wins over url
    # Local page to show without a server: an HTML file whose relative
    # css/js/image siblings load alongside it over file://. A filesystem Path
    # is used in place; an importlib.resources traversable (data packaged in
    # a wheel/zip) is extracted — siblings included — for the browser's
    # lifetime. With Browser, navigation happens after the py channel is
    # installed, so the page's scripts can use py.* immediately.
    page: Path | Traversable | None = None  # opens as a tab; conflicts with url
    app_page: Path | Traversable | None = None  # chromeless --app window; wins over page
    window: Window | None = None
    load_extensions: tuple[Path, ...] = ()
    # Needed for Extensions.loadUnpacked over CDP; implied by load_extensions.
    extension_debugging: bool = False
    minimal_footprint: bool = True
    # Headed windows start clean: bookmarks bar hidden and about:blank instead
    # of the New Tab Page. True restores Chrome's regular UI. (Tabbed windows
    # always keep the toolbar — use app_url/app_page for a toolbar-less window.)
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
    if spec.extension_debugging or spec.load_extensions:
        args.append("--enable-unsafe-extension-debugging")
    if spec.load_extensions:
        args.append("--load-extension=" + ",".join(str(p) for p in spec.load_extensions))
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
    if position == "center":
        position = None if screen is None else ((screen[0] - size[0]) // 2, (screen[1] - size[1]) // 2)
    if isinstance(position, tuple):
        flags.append(f"--window-position={position[0]},{position[1]}")
    return flags

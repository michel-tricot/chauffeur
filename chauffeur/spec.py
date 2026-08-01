"""Declarative description of how a browser should be spun up."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
    window: Window | None = None
    load_extensions: tuple[Path, ...] = ()
    # Needed for Extensions.loadUnpacked over CDP; implied by load_extensions.
    extension_debugging: bool = False
    minimal_footprint: bool = True
    extra_flags: tuple[str, ...] = ()


def build_args(binary: Path, spec: LaunchSpec, port: int, *, screen: tuple[int, int] | None = None) -> list[str]:
    args = [
        str(binary),
        f"--remote-debugging-port={port}",
        f"--user-data-dir={spec.profile.expanduser()}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if spec.headless:
        args.append("--headless=new")
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
    return args


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

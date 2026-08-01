"""Catalog of Chromium-family browsers: binaries and default data directories."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


class BrowserNotFound(RuntimeError):
    """No browser matching the selector is installed."""


@dataclass(frozen=True)
class BrowserInfo:
    id: str
    name: str
    binary: Path
    # Default user-data dir of the *installed* browser, used to discover
    # already-installed extensions. None for custom binaries.
    data_dir: Path | None


def _macos_catalog() -> tuple[BrowserInfo, ...]:
    home = Path.home()
    app_support = home / "Library/Application Support"
    return (
        BrowserInfo(
            "chrome",
            "Google Chrome",
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            app_support / "Google/Chrome",
        ),
        BrowserInfo(
            "chromium",
            "Chromium",
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            app_support / "Chromium",
        ),
        BrowserInfo(
            "brave",
            "Brave",
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            app_support / "BraveSoftware/Brave-Browser",
        ),
        BrowserInfo(
            "edge",
            "Microsoft Edge",
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            app_support / "Microsoft Edge",
        ),
    )


def _linux_catalog() -> tuple[BrowserInfo, ...]:
    home = Path.home()
    specs = [
        ("chrome", "Google Chrome", ["google-chrome", "google-chrome-stable"], home / ".config/google-chrome"),
        ("chromium", "Chromium", ["chromium", "chromium-browser"], home / ".config/chromium"),
        ("brave", "Brave", ["brave-browser"], home / ".config/BraveSoftware/Brave-Browser"),
        ("edge", "Microsoft Edge", ["microsoft-edge"], home / ".config/microsoft-edge"),
    ]
    found = []
    for browser_id, name, binaries, data_dir in specs:
        for candidate in binaries:
            binary = shutil.which(candidate)
            if binary:
                found.append(BrowserInfo(browser_id, name, Path(binary), data_dir))
                break
    return tuple(found)


def catalog() -> tuple[BrowserInfo, ...]:
    if sys.platform == "darwin":
        return _macos_catalog()
    return _linux_catalog()


def installed_browsers() -> list[BrowserInfo]:
    return [b for b in catalog() if b.binary.exists()]


def resolve_browser(selector: str | Path = "auto") -> BrowserInfo:
    """Resolve "auto", a browser id/name, or an explicit binary path."""
    if isinstance(selector, Path):
        if not selector.exists():
            raise BrowserNotFound(f"browser binary not found: {selector}")
        return BrowserInfo("custom", selector.name, selector, None)
    available = installed_browsers()
    if selector == "auto":
        if not available:
            raise BrowserNotFound("no supported browser installed")
        return available[0]
    for browser in available:
        if selector in (browser.id, browser.name):
            return browser
    raise BrowserNotFound(f"browser not installed: {selector!r}")

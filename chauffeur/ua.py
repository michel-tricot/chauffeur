"""User-Agent capture and replay.

Headless Chromium reports a ``HeadlessChrome/x.y`` User-Agent. Some origins
(notably anything behind Cloudflare) reject it, and a session cookie such as
``cf_clearance`` earned in a headed login is bound to the *exact* UA that
headed session sent. So the pattern is: capture the real UA during a headed
login, cache it next to the profile, and replay it, with the Headless marker
stripped, on later headless runs.

Best-effort throughout: if nothing is cached, replay falls back to a
per-platform reconstruction, so a missing capture never breaks a launch.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def ua_cache_path(profile: Path) -> Path:
    """Where a profile's captured UA lives: ``<profile>.ua`` beside the dir."""
    profile = profile.expanduser()
    return profile.parent / f"{profile.name}.ua"


def save_user_agent(profile: Path, user_agent: str) -> None:
    cache = ua_cache_path(profile)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(user_agent.strip(), encoding="utf-8")


def _fallback_platform_token() -> str:
    if sys.platform == "darwin":
        return "Macintosh; Intel Mac OS X 10_15_7"
    if sys.platform.startswith("linux"):
        return "X11; Linux x86_64"
    return "Windows NT 10.0; Win64; x64"


def resolve_user_agent(binary: Path, profile: Path) -> str:
    """The UA a headless run should present.

    Prefers the UA captured at login (Headless marker stripped); otherwise
    reconstructs a plausible one from the browser's ``--version``.
    """
    cache = ua_cache_path(profile)
    if cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        if cached:
            return cached.replace("HeadlessChrome/", "Chrome/")
    major = "140"
    try:
        out = subprocess.check_output([str(binary), "--version"], text=True)
        match = re.search(r"(\d+)\.", out)
        if match:
            major = match.group(1)
    except (OSError, subprocess.SubprocessError):
        pass
    return (
        f"Mozilla/5.0 ({_fallback_platform_token()}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
    )

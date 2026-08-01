"""Profile lifecycle: remove everything chauffeur keeps for a profile.

chauffeur anchors all of an app's browser state to one path: the profile
directory itself, the captured user agent beside it (``<profile>.ua``), and
built extensions (``<profile>.extensions``). wipe_profile removes all of it,
so consumers never have to track the sidecar layout themselves.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import socket
import time
from pathlib import Path

from chauffeur.cdp import CDPClient
from chauffeur.extension import extensions_dir
from chauffeur.ua import ua_cache_path


def running_devtools_port(profile: Path) -> int | None:
    """The DevTools port of a browser currently running on this profile, or None.

    Chrome records its port in ``<profile>/DevToolsActivePort``; the file can
    outlive the process, so the port is probed before being reported.
    """
    try:
        port = int((profile.expanduser() / "DevToolsActivePort").read_text().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return port
    except OSError:
        return None


async def _browser_close(port: int) -> None:
    client = await CDPClient.connect(port, timeout=2)
    try:
        await client.send("Browser.close", timeout=5)
    finally:
        await client.close()


def close_running_browser(profile: Path, timeout: float = 5.0) -> bool:
    """Ask a browser still running on this profile to exit; `True` if one was.

    Orderly `Browser.close`, so profile state is flushed on the way out.
    Synchronous — do not call from inside a running event loop.
    """
    port = running_devtools_port(profile)
    if port is None:
        return False
    with contextlib.suppress(Exception):
        asyncio.run(_browser_close(port))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:  # wait for it to release the profile
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                pass
        except OSError:
            break
        time.sleep(0.1)
    return True


def wipe_profile(profile: Path) -> bool:
    """Remove the profile directory and every sidecar chauffeur keeps for it.

    A browser still running on the profile (e.g. leaked by a killed consumer)
    is asked to exit first, so it cannot rewrite state on its way out. Returns
    `True` if anything existed. Raises `OSError` when the profile directory cannot
    be fully removed.
    """
    profile = profile.expanduser()
    ua = ua_cache_path(profile)
    extensions = extensions_dir(profile)
    existed = profile.exists() or ua.exists() or extensions.exists()
    if profile.exists():
        close_running_browser(profile)
    ua.unlink(missing_ok=True)
    shutil.rmtree(extensions, ignore_errors=True)
    if profile.exists():
        shutil.rmtree(profile)
    return existed

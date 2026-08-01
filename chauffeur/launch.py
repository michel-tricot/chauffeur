"""Spawn a browser process from a LaunchSpec and hand back a plain handle.

No daemon, no lifecycle magic: the consumer owns the handle and decides when
it dies.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from chauffeur.browsers import resolve_browser
from chauffeur.spec import LaunchSpec, build_args


class LaunchError(RuntimeError):
    """The browser failed to start or its DevTools endpoint never came up."""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def screen_size() -> tuple[int, int] | None:
    """Main display size. CoreGraphics via ctypes: no TCC prompt, unlike osascript."""
    if sys.platform != "darwin":
        return None
    try:
        import ctypes

        class _CGRect(ctypes.Structure):
            _fields_ = [(f, ctypes.c_double) for f in ("x", "y", "w", "h")]

        cg = ctypes.CDLL("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
        cg.CGMainDisplayID.restype = ctypes.c_uint32
        cg.CGDisplayBounds.restype = _CGRect
        cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
        bounds = cg.CGDisplayBounds(cg.CGMainDisplayID())
        return int(bounds.w), int(bounds.h)
    except Exception:
        return None


@dataclass
class BrowserHandle:
    proc: subprocess.Popen
    port: int
    binary: Path

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def terminate(self, timeout: float = 5.0) -> None:
        if not self.running:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)


def launch(spec: LaunchSpec, *, ready_timeout: float = 15.0) -> BrowserHandle:
    info = resolve_browser(spec.browser)
    port = spec.devtools_port or free_port()
    spec.profile.expanduser().mkdir(parents=True, exist_ok=True)
    screen = screen_size() if spec.window and spec.window.position == "center" else None
    args = build_args(info.binary, spec, port, screen=screen)
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handle = BrowserHandle(proc, port, info.binary)
    deadline = time.monotonic() + ready_timeout
    while True:
        if proc.poll() is not None:
            raise LaunchError(f"{info.binary.name} exited with code {proc.returncode} before DevTools came up")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                json.loads(resp.read())
            return handle
        except OSError:
            if time.monotonic() > deadline:
                handle.terminate()
                raise LaunchError(f"DevTools port {port} not ready after {ready_timeout}s") from None
            time.sleep(0.2)

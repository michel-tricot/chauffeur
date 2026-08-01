"""Spawn a browser process from a LaunchSpec and hand back a plain handle.

No daemon, no lifecycle magic: the consumer owns the handle and decides when
it dies.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import logging
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from importlib.resources import as_file
from importlib.resources.abc import Traversable
from pathlib import Path

from chauffeur.browsers import catalog, resolve_browser
from chauffeur.extension import build_extension, extensions_dir
from chauffeur.spec import LaunchSpec, build_args

log = logging.getLogger(__name__)


class LaunchError(RuntimeError):
    """The browser failed to start or its DevTools endpoint never came up.

    ``returncode`` is the browser's exit code when it died before the endpoint
    came up (its most common cause: another browser already holds the profile,
    so Chrome's process singleton makes the new one exit immediately); None
    when the process kept running but the endpoint never became ready.
    """

    def __init__(self, message: str, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


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


def _scratch_dir(stack: contextlib.ExitStack) -> Path:
    """A temp dir that lives until the stack (i.e. the browser) is done."""
    return Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="chauffeur-page-")))


def _page_to_uri(page: Path | Traversable, stack: contextlib.ExitStack) -> str:
    """file:// URI for a local page; packaged resources are extracted first.

    A filesystem Path is used in place. Any other traversable (e.g. package
    data inside a zip) is materialized with as_file, via its parent when it
    exposes one, so sibling css/js come along, until the stack closes.
    """
    if isinstance(page, Path):
        page = page.expanduser()
        if not page.is_file():
            raise LaunchError(f"page not found: {page}")
        return page.resolve().as_uri()
    parent = getattr(page, "parent", None)  # zipfile.Path has it; bare Traversables may not
    if parent is not None and parent.is_dir():
        root = stack.enter_context(as_file(parent))
        return (root / page.name).as_uri()
    return stack.enter_context(as_file(page)).as_uri()


def _blank_page_uri(stack: contextlib.ExitStack) -> str:
    """A real blank file to launch on when navigation is deferred.

    Chrome silently ignores --app=about:blank (it opens a tabbed window
    instead of an app window), so deferral needs an actual file URL.
    """
    blank = _scratch_dir(stack) / "blank.html"
    blank.write_text("<!doctype html><title></title>")
    return blank.as_uri()


def _prepare_pages(
    spec: LaunchSpec, stack: contextlib.ExitStack, defer_page: bool
) -> tuple[LaunchSpec, str | None, str | None]:
    """Resolve spec.url to a plain URI string on a copy of the spec.

    A str is used verbatim; a Path/traversable becomes a file:// URI (packaged
    resources are extracted for the browser's lifetime). With defer_page and a
    destination set, the browser launches on a unique blank page instead and the
    resolved destination is returned, so the caller can navigate once its channel
    is wired. Launching straight at the destination would leave the primary tab
    ambiguous — session restore can add tabs — so the unique blank page doubles
    as the launch tab's identity (returned third, kept on the handle).
    """
    destination = None
    if spec.url is not None:
        destination = spec.url if isinstance(spec.url, str) else _page_to_uri(spec.url, stack)
    if destination is None or not defer_page:
        return dataclasses.replace(spec, url=destination), None, None
    blank = _blank_page_uri(stack)
    return dataclasses.replace(spec, url=blank), destination, blank


def _materialize_extensions(spec: LaunchSpec) -> tuple[Path, ...]:
    """Build spec.extensions into <profile>.extensions/<key>, ready to load.

    The build dir is derived from the profile so one path anchors all of the
    app's browser state, no second data-path to misconfigure. Rebuilding on
    every launch picks up bumped installed versions automatically.
    """
    built: list[Path] = []
    used: set[str] = set()
    for ext in spec.extensions:
        if isinstance(ext, Path):
            built.append(ext.expanduser().resolve())
            continue
        key, n = ext.key, 1
        while key in used:
            n += 1
            key = f"{ext.key}-{n}"
        used.add(key)
        built.append(build_extension(ext, extensions_dir(spec.profile) / key))
    return tuple(built)


def _warn_if_real_profile(profile: Path) -> None:
    """Point out a launch that targets a real browser's user data dir.

    profile is a required field precisely so nothing ever *defaults* to a
    real browser profile. Targeting one deliberately is allowed, but
    chauffeur opens a debugging port on it and rewrites its Preferences, so
    it deserves a loud note.
    """
    resolved = profile.expanduser().resolve()
    for browser in catalog():
        if browser.data_dir is None:
            continue
        if resolved.is_relative_to(browser.data_dir.expanduser().resolve()):
            log.warning(
                "profile %s is inside %s's real user data dir, chauffeur will write to it",
                profile,
                browser.name,
            )
            return


def _apply_ui_prefs(spec: LaunchSpec) -> None:
    """Persist headed-UI preferences (bookmarks bar) into the profile.

    Chrome reads them at startup, so this runs before the process spawns.
    Headless has no UI; the profile is left untouched.
    """
    if spec.headless:
        return
    prefs_path = spec.profile.expanduser() / "Default" / "Preferences"
    prefs: dict = {}
    if prefs_path.exists():
        with contextlib.suppress(OSError, ValueError):
            prefs = json.loads(prefs_path.read_text())
    bar = prefs.get("bookmark_bar")
    if not isinstance(bar, dict):
        bar = prefs["bookmark_bar"] = {}
    if bar.get("show_on_all_tabs") == spec.show_browser_ui:
        return  # already right, don't churn a file Chrome also owns
    bar["show_on_all_tabs"] = spec.show_browser_ui
    prefs_path.parent.mkdir(parents=True, exist_ok=True)
    prefs_path.write_text(json.dumps(prefs))


@dataclass
class BrowserHandle:
    proc: subprocess.Popen
    port: int
    binary: Path
    # Resources that must outlive the process (extracted page dirs); closed by
    # terminate().
    cleanup: contextlib.ExitStack | None = None
    # Set when launch(defer_page=True) held back spec.url so the consumer can
    # navigate to it after wiring its channel.
    deferred_url: str | None = None
    # The unique blank URI the primary tab launched on when deferral is active;
    # identifies that tab among session-restored ones.
    primary_url: str | None = None
    # Built extension dirs, ready for Extensions.loadUnpacked over CDP.
    extensions: tuple[Path, ...] = ()

    @property
    def running(self) -> bool:
        return self.proc.poll() is None

    def terminate(self, timeout: float = 5.0) -> None:
        try:
            if self.running:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait(5)
        finally:
            if self.cleanup is not None:
                self.cleanup.close()


def launch(spec: LaunchSpec, *, ready_timeout: float = 15.0, defer_page: bool = False) -> BrowserHandle:
    info = resolve_browser(spec.browser)
    port = spec.devtools_port or free_port()
    stack = contextlib.ExitStack()
    try:
        _warn_if_real_profile(spec.profile)
        extensions = _materialize_extensions(spec)
        spec, deferred_url, primary_url = _prepare_pages(spec, stack, defer_page)
        spec.profile.expanduser().mkdir(parents=True, exist_ok=True)
        _apply_ui_prefs(spec)
        # A named (string) position needs the screen size to resolve; explicit
        # coordinates and None do not.
        screen = screen_size() if spec.window and isinstance(spec.window.position, str) else None
        args = build_args(info.binary, spec, port, screen=screen)
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except BaseException:
        stack.close()
        raise
    handle = BrowserHandle(
        proc,
        port,
        info.binary,
        cleanup=stack,
        deferred_url=deferred_url,
        primary_url=primary_url,
        extensions=extensions,
    )
    deadline = time.monotonic() + ready_timeout
    while True:
        if proc.poll() is not None:
            handle.terminate()  # process is already dead; releases extracted pages
            raise LaunchError(
                f"{info.binary.name} exited with code {proc.returncode} before DevTools came up",
                returncode=proc.returncode,
            )
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as resp:
                json.loads(resp.read())
            return handle
        except OSError:
            if time.monotonic() > deadline:
                handle.terminate()
                raise LaunchError(f"DevTools port {port} not ready after {ready_timeout}s") from None
            time.sleep(0.2)

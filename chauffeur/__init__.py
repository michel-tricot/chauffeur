"""chauffeur: control a local Chromium-family browser.

Launch it your way, patch and load extensions, and talk to it in both
directions with a decorator-based command API.
"""

# Public API. Internal plumbing (CommandRegistry), the concrete extension
# source classes (use ExtensionSpec / ExtensionSpec.from_store), and the
# lower-level UA helpers (use Browser.capture_user_agent / user_agent="auto")
# stay reachable via their submodules but are intentionally not re-exported.
from chauffeur.browser import Browser, JSError, ServeReason
from chauffeur.browsers import BrowserInfo, BrowserNotFoundError, installed_browsers, resolve_browser
from chauffeur.cdp import CDPClient, CDPError
from chauffeur.extension import (
    ExtensionNotFoundError,
    ExtensionSpec,
    build_extension,
    download_extension,
    extensions_dir,
    find_installed_extension,
)
from chauffeur.launch import BrowserHandle, LaunchError, launch
from chauffeur.profiles import wipe_profile
from chauffeur.serde import SchemaError, SerdeError
from chauffeur.spec import LaunchSpec, Window
from chauffeur.sync import SyncBrowser
from chauffeur.ua import ua_cache_path

__all__ = [
    "Browser",
    "BrowserHandle",
    "BrowserInfo",
    "BrowserNotFoundError",
    "CDPClient",
    "CDPError",
    "ExtensionNotFoundError",
    "ExtensionSpec",
    "JSError",
    "LaunchError",
    "LaunchSpec",
    "SchemaError",
    "SerdeError",
    "ServeReason",
    "SyncBrowser",
    "Window",
    "build_extension",
    "download_extension",
    "extensions_dir",
    "find_installed_extension",
    "installed_browsers",
    "launch",
    "resolve_browser",
    "ua_cache_path",
    "wipe_profile",
]

"""chauffeur: control a local Chromium-family browser.

Launch it your way, patch and load extensions, and talk to it in both
directions with a decorator-based command API.
"""

from chauffeur.browser import Browser
from chauffeur.browsers import BrowserInfo, installed_browsers, resolve_browser
from chauffeur.cdp import CDPClient, CDPError
from chauffeur.dispatch import CommandRegistry
from chauffeur.extension import (
    ExtensionBuild,
    LocalExtension,
    StoreExtension,
    download_extension,
    extensions_dir,
    find_installed_extension,
)
from chauffeur.launch import BrowserHandle, LaunchError, launch
from chauffeur.serde import SchemaError, SerdeError
from chauffeur.spec import LaunchSpec, Window
from chauffeur.ua import resolve_user_agent, save_user_agent, ua_cache_path

__all__ = [
    "Browser",
    "BrowserHandle",
    "BrowserInfo",
    "CDPClient",
    "CDPError",
    "CommandRegistry",
    "ExtensionBuild",
    "LaunchError",
    "LaunchSpec",
    "LocalExtension",
    "SchemaError",
    "SerdeError",
    "StoreExtension",
    "Window",
    "download_extension",
    "extensions_dir",
    "find_installed_extension",
    "installed_browsers",
    "launch",
    "resolve_browser",
    "resolve_user_agent",
    "save_user_agent",
    "ua_cache_path",
]

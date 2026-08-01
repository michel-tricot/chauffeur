"""chauffeur: control a local Chromium-family browser.

Launch it your way, patch and load extensions, and talk to it in both
directions with a decorator-based command API.
"""

from chauffeur.browser import Browser
from chauffeur.browsers import BrowserInfo, installed_browsers, resolve_browser
from chauffeur.cdp import CDPClient, CDPError
from chauffeur.dispatch import CommandRegistry
from chauffeur.extension import ExtensionBuild, find_installed_extension
from chauffeur.launch import BrowserHandle, LaunchError, launch
from chauffeur.serde import SchemaError, SerdeError
from chauffeur.spec import LaunchSpec, Window

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
    "SchemaError",
    "SerdeError",
    "Window",
    "find_installed_extension",
    "installed_browsers",
    "launch",
    "resolve_browser",
]

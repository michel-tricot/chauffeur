import json
import logging
import sys

from chauffeur.browsers import BrowserInfo
from chauffeur.launch import _apply_ui_prefs, _warn_if_real_profile
from chauffeur.spec import LaunchSpec

# The package re-exports the launch *function*, which shadows the
# chauffeur.launch module attribute — go through sys.modules for the module.
launch_module = sys.modules["chauffeur.launch"]


def _prefs(profile):
    return json.loads((profile / "Default" / "Preferences").read_text())


def test_real_browser_data_dir_warns(tmp_path, monkeypatch, caplog):
    real = tmp_path / "Library/Google/Chrome"
    fake_catalog = (BrowserInfo("chrome", "Google Chrome", tmp_path / "bin", real),)
    monkeypatch.setattr(launch_module, "catalog", lambda: fake_catalog)

    with caplog.at_level(logging.WARNING, logger="chauffeur.launch"):
        _warn_if_real_profile(real / "Profile 1")
    assert "real user data dir" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="chauffeur.launch"):
        _warn_if_real_profile(tmp_path / "myapp-profile")  # dedicated dir: silent
    assert not caplog.text


def test_headed_hides_bookmarks_bar(tmp_path):
    profile = tmp_path / "prof"
    _apply_ui_prefs(LaunchSpec(profile=profile, headless=False))
    assert _prefs(profile)["bookmark_bar"]["show_on_all_tabs"] is False


def test_show_browser_ui_shows_bookmarks_bar(tmp_path):
    profile = tmp_path / "prof"
    _apply_ui_prefs(LaunchSpec(profile=profile, headless=False, show_browser_ui=True))
    assert _prefs(profile)["bookmark_bar"]["show_on_all_tabs"] is True


def test_existing_prefs_are_preserved(tmp_path):
    profile = tmp_path / "prof"
    default = profile / "Default"
    default.mkdir(parents=True)
    (default / "Preferences").write_text(json.dumps({"other": 1, "bookmark_bar": {"custom": 2}}))
    _apply_ui_prefs(LaunchSpec(profile=profile, headless=False))
    prefs = _prefs(profile)
    assert prefs["other"] == 1
    assert prefs["bookmark_bar"] == {"custom": 2, "show_on_all_tabs": False}


def test_unchanged_prefs_are_not_rewritten(tmp_path):
    profile = tmp_path / "prof"
    default = profile / "Default"
    default.mkdir(parents=True)
    text = '{ "bookmark_bar": { "show_on_all_tabs": false } }'  # distinctive formatting
    (default / "Preferences").write_text(text)
    _apply_ui_prefs(LaunchSpec(profile=profile, headless=False))
    assert (default / "Preferences").read_text() == text


def test_headless_leaves_profile_untouched(tmp_path):
    profile = tmp_path / "prof"
    _apply_ui_prefs(LaunchSpec(profile=profile, headless=True))
    assert not (profile / "Default").exists()

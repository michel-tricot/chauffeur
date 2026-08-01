import json

from chauffeur.launch import _apply_ui_prefs
from chauffeur.spec import LaunchSpec


def _prefs(profile):
    return json.loads((profile / "Default" / "Preferences").read_text())


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


def test_headless_leaves_profile_untouched(tmp_path):
    profile = tmp_path / "prof"
    _apply_ui_prefs(LaunchSpec(profile=profile, headless=True))
    assert not (profile / "Default").exists()

from pathlib import Path

from chauffeur import ua
from chauffeur.spec import LaunchSpec, build_args


def test_cache_path_is_beside_profile(tmp_path):
    profile = tmp_path / "prof"
    assert ua.ua_cache_path(profile) == tmp_path / "prof.ua"


def test_save_and_resolve_roundtrip_strips_headless(tmp_path):
    profile = tmp_path / "prof"
    ua.save_user_agent(profile, "Mozilla/5.0 HeadlessChrome/140.0.0.0 Safari/537.36")
    resolved = ua.resolve_user_agent(Path("/bin/does-not-matter"), profile)
    assert "HeadlessChrome" not in resolved
    assert "Chrome/140.0.0.0" in resolved


def test_resolve_falls_back_without_cache(tmp_path):
    # Non-existent binary => --version fails => default major, still a valid UA.
    resolved = ua.resolve_user_agent(tmp_path / "nope", tmp_path / "prof")
    assert resolved.startswith("Mozilla/5.0")
    assert "Chrome/" in resolved


def test_explicit_ua_applied_headed_and_headless(tmp_path):
    for headless in (True, False):
        spec = LaunchSpec(profile=tmp_path / "p", headless=headless, user_agent="Custom/1.0")
        args = build_args(Path("/bin/chrome"), spec, 9222)
        assert "--user-agent=Custom/1.0" in args


def test_auto_ua_only_headless(tmp_path):
    profile = tmp_path / "p"
    ua.save_user_agent(profile, "Real/9.0")

    headless = build_args(Path("/bin/chrome"), LaunchSpec(profile=profile, headless=True, user_agent="auto"), 9222)
    assert "--user-agent=Real/9.0" in headless

    headed = build_args(Path("/bin/chrome"), LaunchSpec(profile=profile, headless=False, user_agent="auto"), 9222)
    assert not any(a.startswith("--user-agent=") for a in headed)


def test_no_ua_by_default(tmp_path):
    args = build_args(Path("/bin/chrome"), LaunchSpec(profile=tmp_path / "p"), 9222)
    assert not any(a.startswith("--user-agent=") for a in args)

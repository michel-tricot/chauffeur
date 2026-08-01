from chauffeur.extension import extensions_dir
from chauffeur.profiles import running_devtools_port, wipe_profile
from chauffeur.ua import ua_cache_path


def _populated_profile(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "Cookies").write_text("data")
    ua_cache_path(profile).write_text("Mozilla/5.0")
    (extensions_dir(profile) / "ext").mkdir(parents=True)
    return profile


def test_wipe_profile_removes_dir_and_all_sidecars(tmp_path):
    profile = _populated_profile(tmp_path)
    assert wipe_profile(profile) is True
    assert not profile.exists()
    assert not ua_cache_path(profile).exists()
    assert not extensions_dir(profile).exists()


def test_wipe_profile_handles_sidecars_without_dir(tmp_path):
    profile = tmp_path / "profile"  # directory never created
    ua_cache_path(profile).write_text("Mozilla/5.0")
    assert wipe_profile(profile) is True
    assert not ua_cache_path(profile).exists()


def test_wipe_profile_with_nothing_returns_false(tmp_path):
    assert wipe_profile(tmp_path / "profile") is False


def test_running_devtools_port_ignores_missing_and_stale_files(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    assert running_devtools_port(profile) is None  # no file
    (profile / "DevToolsActivePort").write_text("not-a-port\n/devtools/browser/x")
    assert running_devtools_port(profile) is None  # garbage
    (profile / "DevToolsActivePort").write_text("1\n/devtools/browser/x")
    assert running_devtools_port(profile) is None  # nothing listening on port 1


def test_wipe_profile_survives_stale_devtools_file(tmp_path):
    profile = _populated_profile(tmp_path)
    (profile / "DevToolsActivePort").write_text("1\n/devtools/browser/x")
    assert wipe_profile(profile) is True
    assert not profile.exists()

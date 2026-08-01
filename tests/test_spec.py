from pathlib import Path

from chauffeur.spec import LaunchSpec, Window, build_args


def _args(**kw):
    spec = LaunchSpec(profile=Path("/tmp/prof"), **kw)
    return build_args(Path("/bin/chrome"), spec, port=9222)


def test_core_flags():
    args = _args()
    assert args[0] == "/bin/chrome"
    assert "--remote-debugging-port=9222" in args
    assert "--user-data-dir=/tmp/prof" in args
    assert "--headless=new" in args


def test_headed_omits_headless():
    assert "--headless=new" not in _args(headless=False)


def test_extension_flags_imply_debugging():
    args = _args(load_extensions=(Path("/tmp/ext"),))
    assert "--enable-unsafe-extension-debugging" in args
    assert "--load-extension=/tmp/ext" in args


def test_app_url_wins_over_url():
    args = _args(url="https://a", app_url="https://b")
    assert "--app=https://b" in args
    assert "https://a" not in args


def test_url_appended_last():
    args = _args(url="https://a")
    assert args[-1] == "https://a"


def test_window_centering_with_screen():
    from chauffeur.spec import build_args as ba

    spec = LaunchSpec(profile=Path("/tmp/p"), window=Window(size=(400, 300), position="center"))
    args = ba(Path("/bin/chrome"), spec, 9222, screen=(2000, 1000))
    assert "--window-size=400,300" in args
    assert "--window-position=800,350" in args


def test_bare_headed_launch_starts_blank_not_ntp():
    assert _args(headless=False)[-1] == "about:blank"


def test_show_browser_ui_keeps_ntp():
    assert "about:blank" not in _args(headless=False, show_browser_ui=True)


def test_bare_headless_launch_gets_no_url():
    assert "about:blank" not in _args()


def test_blank_does_not_override_url_or_app():
    assert _args(headless=False, url="https://a")[-1] == "https://a"
    assert "about:blank" not in _args(headless=False, app_url="https://a")


def test_minimal_footprint_toggle():
    assert "--disable-gpu" in _args()
    assert "--disable-gpu" not in _args(minimal_footprint=False)

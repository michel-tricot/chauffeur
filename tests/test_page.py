import contextlib
import zipfile
from pathlib import Path

import pytest

from chauffeur.launch import LaunchError, _page_to_uri, _prepare_pages
from chauffeur.spec import LaunchSpec, build_args


def _page(tmp_path, name="app.html"):
    page = tmp_path / name
    page.write_text("<!doctype html>")
    return page


def test_path_page_resolves_in_place(tmp_path):
    page = _page(tmp_path)
    with contextlib.ExitStack() as stack:
        assert _page_to_uri(page, stack) == page.resolve().as_uri()


def test_missing_path_page_raises(tmp_path):
    with contextlib.ExitStack() as stack, pytest.raises(LaunchError, match="page not found"):
        _page_to_uri(tmp_path / "nope.html", stack)


def test_zip_page_extracted_with_siblings(tmp_path):
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("ui/app.html", '<link rel="stylesheet" href="style.css">')
        zf.writestr("ui/style.css", "body {}")
        zf.writestr("ui/nested/x.js", "1;")

    stack = contextlib.ExitStack()
    uri = _page_to_uri(zipfile.Path(archive, "ui/app.html"), stack)
    extracted = Path(uri.removeprefix("file://"))
    assert extracted.name == "app.html"
    assert extracted.is_file()
    assert (extracted.parent / "style.css").is_file()
    assert (extracted.parent / "nested/x.js").is_file()

    stack.close()
    assert not extracted.exists()  # extraction lives only as long as the stack


def test_app_requires_url():
    with pytest.raises(ValueError, match="app=True needs a url"):
        LaunchSpec(profile=Path("/tmp/p"), app=True)


def test_string_url_is_verbatim_trailing_arg(tmp_path):
    spec = LaunchSpec(profile=tmp_path / "p", url="https://x")
    with contextlib.ExitStack() as stack:
        resolved, deferred, primary = _prepare_pages(spec, stack, defer_page=False)
        assert (deferred, primary) == (None, None)
        assert build_args(Path("/bin/chrome"), resolved, 9222)[-1] == "https://x"


def test_path_url_becomes_trailing_file_uri(tmp_path):
    page = _page(tmp_path)
    spec = LaunchSpec(profile=tmp_path / "p", url=page)
    with contextlib.ExitStack() as stack:
        resolved, _, _ = _prepare_pages(spec, stack, defer_page=False)
        assert build_args(Path("/bin/chrome"), resolved, 9222)[-1] == page.resolve().as_uri()


def test_app_makes_app_flag(tmp_path):
    page = _page(tmp_path)
    spec = LaunchSpec(profile=tmp_path / "p", url=page, app=True)
    with contextlib.ExitStack() as stack:
        resolved, _, _ = _prepare_pages(spec, stack, defer_page=False)
        args = build_args(Path("/bin/chrome"), resolved, 9222)
        assert f"--app={page.resolve().as_uri()}" in args
        assert args[-1] != page.resolve().as_uri()  # a flag, not the trailing tab arg


def test_deferred_destination_starts_on_blank(tmp_path):
    # An app page: the destination is held back and the window launches on a
    # unique blank file (Chrome ignores --app=about:blank), staying an app window.
    page = _page(tmp_path)
    spec = LaunchSpec(profile=tmp_path / "p", url=page, app=True)
    with contextlib.ExitStack() as stack:
        resolved, deferred, primary = _prepare_pages(spec, stack, defer_page=True)
        assert deferred == page.resolve().as_uri()
        assert resolved.url == primary
        assert primary.startswith("file://") and primary.endswith("blank.html")
        assert Path(primary.removeprefix("file://")).is_file()
        assert resolved.app is True  # still launches as an app window
        assert f"--app={primary}" in build_args(Path("/bin/chrome"), resolved, 9222)

    # A remote URL defers the same way, so the launch tab is identifiable.
    spec = LaunchSpec(profile=tmp_path / "p", url="https://x/login")
    with contextlib.ExitStack() as stack:
        resolved, deferred, primary = _prepare_pages(spec, stack, defer_page=True)
        assert deferred == "https://x/login"
        assert resolved.url == primary and primary.endswith("blank.html")


def test_spec_without_destination_passes_through(tmp_path):
    spec = LaunchSpec(profile=tmp_path / "p")
    with contextlib.ExitStack() as stack:
        resolved, deferred, primary = _prepare_pages(spec, stack, defer_page=True)
        assert (resolved.url, deferred, primary) == (None, None, None)

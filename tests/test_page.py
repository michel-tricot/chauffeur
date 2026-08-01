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


def test_page_conflicts_with_url(tmp_path):
    spec = LaunchSpec(profile=tmp_path / "p", page=_page(tmp_path), url="https://x")
    with contextlib.ExitStack() as stack, pytest.raises(ValueError, match="not both"):
        _prepare_pages(spec, stack, defer_page=False)


def test_app_page_conflicts_with_app_url(tmp_path):
    spec = LaunchSpec(profile=tmp_path / "p", app_page=_page(tmp_path), app_url="https://x")
    with contextlib.ExitStack() as stack, pytest.raises(ValueError, match="not both"):
        _prepare_pages(spec, stack, defer_page=False)


def test_page_becomes_trailing_url(tmp_path):
    page = _page(tmp_path)
    spec = LaunchSpec(profile=tmp_path / "p", page=page)
    with contextlib.ExitStack() as stack:
        resolved, deferred = _prepare_pages(spec, stack, defer_page=False)
        assert deferred is None
        args = build_args(Path("/bin/chrome"), resolved, 9222)
        assert args[-1] == page.resolve().as_uri()


def test_app_page_becomes_app_flag(tmp_path):
    page = _page(tmp_path)
    spec = LaunchSpec(profile=tmp_path / "p", app_page=page)
    with contextlib.ExitStack() as stack:
        resolved, _ = _prepare_pages(spec, stack, defer_page=False)
        args = build_args(Path("/bin/chrome"), resolved, 9222)
        assert f"--app={page.resolve().as_uri()}" in args


def test_deferred_page_starts_blank(tmp_path):
    page = _page(tmp_path)
    spec = LaunchSpec(profile=tmp_path / "p", app_page=page)
    with contextlib.ExitStack() as stack:
        resolved, deferred = _prepare_pages(spec, stack, defer_page=True)
        assert deferred == page.resolve().as_uri()
        # A real file, not about:blank, Chrome ignores --app=about:blank and
        # would open a tabbed window instead of an app window.
        assert resolved.app_url.startswith("file://")
        assert resolved.app_url.endswith("blank.html")
        assert Path(resolved.app_url.removeprefix("file://")).is_file()

    spec = LaunchSpec(profile=tmp_path / "p", page=page)
    with contextlib.ExitStack() as stack:
        resolved, deferred = _prepare_pages(spec, stack, defer_page=True)
        assert deferred == page.resolve().as_uri()
        assert resolved.url is None


def test_spec_without_pages_passes_through(tmp_path):
    spec = LaunchSpec(profile=tmp_path / "p", url="https://x")
    with contextlib.ExitStack() as stack:
        resolved, deferred = _prepare_pages(spec, stack, defer_page=True)
        assert resolved is spec
        assert deferred is None

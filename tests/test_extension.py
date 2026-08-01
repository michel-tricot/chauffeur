import json

import pytest

from chauffeur.extension import ExtensionBuild


def _make_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps({"name": "ext", "version": "1.0"}))
    (src / "background.js").write_text("init();")
    return src


def test_build_copies_and_patches(tmp_path):
    src = _make_source(tmp_path)
    work = tmp_path / "work"
    built = (
        ExtensionBuild(src, work)
        .inject_config("background.js", {"port": 1})
        .append("background.js", "bridge();")
        .patch_manifest(lambda m: {**m, "name": m["name"] + "!"})
        .build()
    )
    assert built == work.resolve()
    text = (built / "background.js").read_text()
    assert text.startswith("globalThis.__chauffeur_config")
    assert text.endswith("bridge();")
    assert json.loads((built / "manifest.json").read_text())["name"] == "ext!"


def test_rebuild_replaces_previous_build(tmp_path):
    src = _make_source(tmp_path)
    work = tmp_path / "work"
    build = ExtensionBuild(src, work)
    build.build()
    (work / "stale.js").write_text("old")
    build.build()
    assert not (work / "stale.js").exists()


def test_build_refuses_workdir_equal_to_source(tmp_path):
    src = _make_source(tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        ExtensionBuild(src, src).build()
    assert (src / "background.js").exists()


def test_build_refuses_workdir_inside_source(tmp_path):
    src = _make_source(tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        ExtensionBuild(src, src / "nested").build()


def test_build_refuses_source_inside_workdir(tmp_path):
    src = _make_source(tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        ExtensionBuild(src, tmp_path).build()


def test_build_refuses_foreign_directory(tmp_path):
    src = _make_source(tmp_path)
    foreign = tmp_path / "precious"
    foreign.mkdir()
    (foreign / "data.txt").write_text("keep me")
    with pytest.raises(ValueError, match="not a previous build"):
        ExtensionBuild(src, foreign).build()
    assert (foreign / "data.txt").read_text() == "keep me"

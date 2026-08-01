import io
import json
import zipfile

import pytest

import chauffeur.extension as ext_module
from chauffeur import ExtensionNotFoundError  # via the package root: locks in the public export
from chauffeur.extension import (
    ExtensionSpec,
    StoreExtension,
    _crx_to_zip,
    build_extension,
    download_extension,
    extensions_dir,
)
from chauffeur.launch import _materialize_extensions
from chauffeur.spec import LaunchSpec


def _make_source(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps({"name": "ext", "version": "1.0"}))
    (src / "background.js").write_text("init();")
    return src


def _zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


def _crx3(zip_bytes, header=b""):
    return b"Cr24" + (3).to_bytes(4, "little") + len(header).to_bytes(4, "little") + header + zip_bytes


def _crx2(zip_bytes, pubkey=b"", sig=b""):
    return (
        b"Cr24"
        + (2).to_bytes(4, "little")
        + len(pubkey).to_bytes(4, "little")
        + len(sig).to_bytes(4, "little")
        + pubkey
        + sig
        + zip_bytes
    )


def _fake_download(monkeypatch, crx_bytes, counter=None):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            if counter is not None:
                counter.append(1)
            return crx_bytes

    monkeypatch.setattr(ext_module.urllib.request, "urlopen", lambda *_a, **_kw: _Resp())


def test_build_copies_and_patches(tmp_path):
    src = _make_source(tmp_path)
    work = tmp_path / "work"
    spec = (
        ExtensionSpec(src)
        .inject_config("background.js", {"port": 1})
        .append("background.js", "bridge();")
        .patch_manifest(lambda m: {**m, "name": m["name"] + "!"})
    )
    built = build_extension(spec, work)
    assert built == work.resolve()
    text = (built / "background.js").read_text()
    assert text.startswith("globalThis.__chauffeur_config")
    assert text.endswith("bridge();")
    assert json.loads((built / "manifest.json").read_text())["name"] == "ext!"


def test_rebuild_replaces_previous_build(tmp_path):
    src = _make_source(tmp_path)
    work = tmp_path / "work"
    spec = ExtensionSpec(src)
    build_extension(spec, work)
    (work / "stale.js").write_text("old")
    build_extension(spec, work)
    assert not (work / "stale.js").exists()


def test_build_refuses_workdir_equal_to_source(tmp_path):
    src = _make_source(tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        build_extension(ExtensionSpec(src), src)
    assert (src / "background.js").exists()


def test_build_refuses_workdir_inside_source(tmp_path):
    src = _make_source(tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        build_extension(ExtensionSpec(src), src / "nested")


def test_build_refuses_source_inside_workdir(tmp_path):
    src = _make_source(tmp_path)
    with pytest.raises(ValueError, match="overlaps"):
        build_extension(ExtensionSpec(src), tmp_path)


def test_add_file_creates_and_refuses_overwrite(tmp_path):
    src = _make_source(tmp_path)
    spec = (
        ExtensionSpec(src)
        .add_file("content/inject.js", "console.log('hi');")
        .add_file("data.bin", b"\x00\x01\x02")
    )
    built = build_extension(spec, tmp_path / "work")
    assert (built / "content/inject.js").read_text() == "console.log('hi');"
    assert (built / "data.bin").read_bytes() == b"\x00\x01\x02"

    with pytest.raises(ValueError, match="already exists"):
        build_extension(ExtensionSpec(src).add_file("background.js", "x"), tmp_path / "work2")

    over = build_extension(
        ExtensionSpec(src).add_file("background.js", "replaced();", overwrite=True), tmp_path / "work3"
    )
    assert (over / "background.js").read_text() == "replaced();"


def test_crx3_to_zip():
    z = _zip_bytes({"manifest.json": "{}"})
    assert _crx_to_zip(_crx3(z, header=b"proto-header")) == z


def test_crx2_to_zip():
    z = _zip_bytes({"manifest.json": "{}"})
    assert _crx_to_zip(_crx2(z, pubkey=b"key", sig=b"sig")) == z


def test_bare_zip_passthrough_and_bad_magic():
    z = _zip_bytes({"manifest.json": "{}"})
    assert _crx_to_zip(z) == z
    with pytest.raises(ValueError, match="bad magic"):
        _crx_to_zip(b"NOPE" + z)


def test_download_extension_unpacks(tmp_path, monkeypatch):
    crx = _crx3(_zip_bytes({"manifest.json": '{"name": "Pulled"}', "bg.js": "1;"}))
    _fake_download(monkeypatch, crx)
    dest = download_extension("abcdefghijklmnopabcdefghijklmnop", tmp_path / "dl")
    assert json.loads((dest / "manifest.json").read_text())["name"] == "Pulled"
    assert (dest / "bg.js").is_file()


def test_download_strips_metadata(tmp_path, monkeypatch):
    # Store CRXs ship _metadata, and Chrome refuses to load an unpacked copy with it.
    crx = _crx3(_zip_bytes({"manifest.json": "{}", "_metadata/verified_contents.json": "{}"}))
    _fake_download(monkeypatch, crx)
    dest = download_extension("abcdefghijklmnopabcdefghijklmnop", tmp_path / "dl")
    assert not (dest / "_metadata").exists()


def test_bad_download_keeps_existing_copy(tmp_path, monkeypatch):
    _fake_download(monkeypatch, _crx3(_zip_bytes({"manifest.json": '{"name": "kept"}'})))
    dest = download_extension("abcdefghijklmnopabcdefghijklmnop", tmp_path / "dl")

    _fake_download(monkeypatch, b"Cr24 not a real crx payload")
    with pytest.raises(ExtensionNotFoundError, match="not a valid CRX"):
        download_extension("abcdefghijklmnopabcdefghijklmnop", tmp_path / "dl")
    assert json.loads((dest / "manifest.json").read_text())["name"] == "kept"


def test_manifestless_download_keeps_existing_copy(tmp_path, monkeypatch):
    _fake_download(monkeypatch, _crx3(_zip_bytes({"manifest.json": '{"name": "kept"}'})))
    dest = download_extension("abcdefghijklmnopabcdefghijklmnop", tmp_path / "dl")

    _fake_download(monkeypatch, _crx3(_zip_bytes({"bg.js": "1;"})))
    with pytest.raises(ExtensionNotFoundError, match="no manifest"):
        download_extension("abcdefghijklmnopabcdefghijklmnop", tmp_path / "dl")
    assert json.loads((dest / "manifest.json").read_text())["name"] == "kept"


def test_store_source_downloads_once(tmp_path, monkeypatch):
    calls = []
    _fake_download(monkeypatch, _crx3(_zip_bytes({"manifest.json": "{}"})), counter=calls)
    source = StoreExtension("abcdefghijklmnopabcdefghijklmnop")
    first = source.resolve(tmp_path)
    second = source.resolve(tmp_path)  # cached; no second download
    assert first == second
    assert len(calls) == 1


def test_store_source_refresh_redownloads_each_resolve(tmp_path, monkeypatch):
    calls = []
    _fake_download(monkeypatch, _crx3(_zip_bytes({"manifest.json": "{}"})), counter=calls)
    source = StoreExtension("abcdefghijklmnopabcdefghijklmnop", refresh=True)
    assert source.resolve(tmp_path) == source.resolve(tmp_path)
    assert len(calls) == 2


def test_store_source_refresh_survives_store_outage(tmp_path, monkeypatch):
    _fake_download(monkeypatch, _crx3(_zip_bytes({"manifest.json": '{"name": "kept"}'})))
    source = StoreExtension("abcdefghijklmnopabcdefghijklmnop", refresh=True)
    cached = source.resolve(tmp_path)

    _fake_download(monkeypatch, b"")  # empty 204: the store is not cooperating
    assert source.resolve(tmp_path) == cached  # must not raise; the cache keeps working
    assert json.loads((cached / "manifest.json").read_text())["name"] == "kept"


def test_store_source_refresh_raises_without_cache(tmp_path, monkeypatch):
    _fake_download(monkeypatch, b"")
    with pytest.raises(ExtensionNotFoundError):
        StoreExtension("abcdefghijklmnopabcdefghijklmnop", refresh=True).resolve(tmp_path)


def test_from_store_builds_with_patches(tmp_path, monkeypatch):
    crx = _crx3(_zip_bytes({"manifest.json": '{"name": "Store Ext"}', "background.js": "boot();"}))
    _fake_download(monkeypatch, crx)
    spec = ExtensionSpec.from_store("abcdefghijklmnopabcdefghijklmnop")
    assert spec.key == "abcdefghijklmnopabcdefghijklmnop"
    built = build_extension(spec.append("background.js", "bridge();").add_file("extra.js", "x"), tmp_path / "build")
    assert (built / "background.js").read_text().endswith("bridge();")
    assert (built / "extra.js").is_file()


def test_key_slugs_manifest_name(tmp_path):
    src = _make_source(tmp_path)
    assert ExtensionSpec(src).key == "ext"


def test_materialize_builds_beside_profile(tmp_path):
    src = _make_source(tmp_path)
    profile = tmp_path / "profile"
    spec = LaunchSpec(profile=profile, extensions=(ExtensionSpec(src), ExtensionSpec(src)))
    built = _materialize_extensions(spec)
    assert built[0] == (extensions_dir(profile) / "ext").resolve()
    assert built[1].name == "ext-2"  # same manifest name: second build gets a suffix
    assert (built[0] / "manifest.json").is_file()


def test_materialize_passes_prebuilt_paths_through(tmp_path):
    prebuilt = tmp_path / "prebuilt"
    spec = LaunchSpec(profile=tmp_path / "profile", extensions=(prebuilt,))
    assert _materialize_extensions(spec) == (prebuilt.resolve(),)


def test_build_refuses_foreign_directory(tmp_path):
    src = _make_source(tmp_path)
    foreign = tmp_path / "precious"
    foreign.mkdir()
    (foreign / "data.txt").write_text("keep me")
    with pytest.raises(ValueError, match="not a previous build"):
        build_extension(ExtensionSpec(src), foreign)
    assert (foreign / "data.txt").read_text() == "keep me"

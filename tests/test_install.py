import os
import shutil
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from nokap._errors import NokapError
from nokap._install import (
    _resolve,
    cache_dir,
    chrome_platform,
    install_chrome,
    installed_headless_shell,
)

PLAT = chrome_platform()
EXE = (
    "chrome-headless-shell.exe" if sys.platform == "win32" else "chrome-headless-shell"
)


def _downloads(version, plats):
    base = "https://storage.googleapis.com/chrome-for-testing-public"
    return {
        "chrome-headless-shell": [
            {
                "platform": p,
                "url": f"{base}/{version}/{p}/chrome-headless-shell-{p}.zip",
            }
            for p in plats
        ]
    }


def _entry(version, plats=(PLAT,)):
    return {
        "version": version,
        "revision": "1",
        "downloads": _downloads(version, plats),
    }


FAKE_JSON = {
    "last-known-good-versions-with-downloads.json": {
        "channels": {
            "Stable": {"channel": "Stable", **_entry("156.0.8078.80")},
            "Beta": {"channel": "Beta", **_entry("157.0.8100.10")},
        }
    },
    "latest-versions-per-milestone-with-downloads.json": {
        "milestones": {"155": {"milestone": "155", **_entry("155.0.7999.5")}}
    },
    "known-good-versions-with-downloads.json": {
        "versions": [
            # Old versions have no headless-shell downloads
            {"version": "113.0.5672.0", "revision": "1", "downloads": {}},
            _entry("156.0.8078.80"),
        ]
    },
}


@pytest.fixture()
def fake_cft():
    with patch("nokap._install._fetch_json", side_effect=FAKE_JSON.__getitem__) as m:
        yield m


@pytest.fixture()
def cache(tmp_path):
    path = tmp_path / "cache"
    with patch.dict(os.environ, {"NOKAP_CACHE_DIR": str(path)}):
        yield path


def _make_zip(path, members):
    """`members` maps archive names to (content, unix mode)."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, (content, mode) in members.items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (0o100000 | mode) << 16
            zf.writestr(info, content)
    return path


def _shell_zip(path):
    root = f"chrome-headless-shell-{PLAT}"
    return _make_zip(
        path,
        {
            f"{root}/{EXE}": (b"#!/bin/sh\n", 0o755),
            f"{root}/resources.pak": (b"data", 0o644),
        },
    )


def _serve(archive):
    """A stand-in for _download that copies a local zip."""
    return patch(
        "nokap._install._download",
        side_effect=lambda url, dest: shutil.copy(archive, dest),
    )


# ---------------------------------------------------------------------------
# Platform and cache location
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plat, machine, expected",
    [
        ("macos", "arm64", "mac-arm64"),
        ("macos", "x86_64", "mac-x64"),
        ("linux", "x86_64", "linux64"),
        ("linux", "aarch64", "linux-arm64"),
        ("windows", "AMD64", "win64"),
        ("windows", "ARM64", "win64"),
        ("windows", "x86", "win32"),
    ],
)
def test_chrome_platform(plat, machine, expected):
    with (
        patch("nokap._install.current_platform", return_value=plat),
        patch("nokap._install.platform.machine", return_value=machine),
    ):
        assert chrome_platform() == expected


def test_cache_dir_env_var(tmp_path):
    with patch.dict(os.environ, {"NOKAP_CACHE_DIR": str(tmp_path)}):
        assert cache_dir() == tmp_path


def test_cache_dir_linux_xdg(tmp_path):
    with (
        patch.dict(os.environ, {"XDG_CACHE_HOME": str(tmp_path)}),
        patch("nokap._install.current_platform", return_value="linux"),
    ):
        os.environ.pop("NOKAP_CACHE_DIR", None)
        assert cache_dir() == tmp_path / "nokap"


def test_cache_dir_macos():
    with (
        patch("nokap._install.current_platform", return_value="macos"),
        patch.dict(os.environ),
    ):
        os.environ.pop("NOKAP_CACHE_DIR", None)
        assert cache_dir() == Path.home() / "Library" / "Caches" / "nokap"


# ---------------------------------------------------------------------------
# Version resolution
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spec, version",
    [
        ("stable", "156.0.8078.80"),
        ("Beta", "157.0.8100.10"),
        ("155", "155.0.7999.5"),
        ("156.0.8078.80", "156.0.8078.80"),
    ],
)
def test_resolve(fake_cft, spec, version):
    resolved, url = _resolve(spec, PLAT)
    assert resolved == version
    assert url.endswith(f"/{version}/{PLAT}/chrome-headless-shell-{PLAT}.zip")


@pytest.mark.parametrize(
    "spec, message",
    [
        ("latest", "Invalid version"),
        ("1.2", "Invalid version"),
        ("12", "no release for milestone"),
        ("1.2.3.4", "no build for version"),
        ("113.0.5672.0", "no chrome-headless-shell build"),
    ],
)
def test_resolve_errors(fake_cft, spec, message):
    with pytest.raises(NokapError, match=message):
        _resolve(spec, PLAT)


def test_resolve_missing_platform(fake_cft):
    with pytest.raises(NokapError, match="for not-a-platform"):
        _resolve("stable", "not-a-platform")


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------


def test_install_chrome(fake_cft, cache, tmp_path):
    archive = _shell_zip(tmp_path / "shell.zip")
    with _serve(archive):
        path = install_chrome()

    expected = (
        cache
        / "chrome-headless-shell"
        / "156.0.8078.80"
        / f"chrome-headless-shell-{PLAT}"
    )
    assert path == str(expected / EXE)
    assert (expected / "resources.pak").read_bytes() == b"data"
    if sys.platform != "win32":
        assert os.access(path, os.X_OK)
        assert not os.access(expected / "resources.pak", os.X_OK)
    assert installed_headless_shell() == path
    # Only the version dir is left behind; staging is cleaned up
    assert os.listdir(cache / "chrome-headless-shell") == ["156.0.8078.80"]


def test_install_chrome_is_idempotent(fake_cft, cache, tmp_path):
    archive = _shell_zip(tmp_path / "shell.zip")
    with _serve(archive) as download:
        first = install_chrome("stable")
        second = install_chrome("156.0.8078.80")
        assert first == second
        assert download.call_count == 1

        install_chrome("stable", force=True)
        assert download.call_count == 2


def test_install_chrome_rejects_zip_slip(fake_cft, cache, tmp_path):
    archive = _make_zip(tmp_path / "evil.zip", {"../../evil": (b"x", 0o644)})
    with _serve(archive), pytest.raises(NokapError, match="Refusing to extract"):
        install_chrome()
    assert not (cache / "evil").exists()
    assert not (cache.parent / "evil").exists()
    assert installed_headless_shell() is None


def test_install_chrome_archive_without_executable(fake_cft, cache, tmp_path):
    archive = _make_zip(tmp_path / "empty.zip", {"README": (b"x", 0o644)})
    with _serve(archive), pytest.raises(NokapError, match="does not contain"):
        install_chrome()
    assert os.listdir(cache / "chrome-headless-shell") == []


def test_install_chrome_network_error(cache):
    with (
        patch("nokap._install._fetch_json", side_effect=OSError("offline")),
        pytest.raises(NokapError, match="Could not reach Chrome for Testing"),
    ):
        install_chrome()


def test_install_chrome_download_error(fake_cft, cache):
    with (
        patch("nokap._install._download", side_effect=OSError("reset")),
        pytest.raises(NokapError, match="Downloading .* failed"),
    ):
        install_chrome()
    assert os.listdir(cache / "chrome-headless-shell") == []

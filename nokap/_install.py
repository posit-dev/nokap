from __future__ import annotations

import json
import os
import platform
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from ._errors import NokapError
from ._utils import current_platform

__all__ = ["install_chrome"]

_CFT_BASE = "https://googlechromelabs.github.io/chrome-for-testing"
_CHANNELS = ("stable", "beta", "dev", "canary")
_HEADLESS_SHELL = "chrome-headless-shell"


def cache_dir() -> Path:
    """
    Directory where nokap keeps browsers it installs.

    Uses the `NOKAP_CACHE_DIR` environment variable when set; otherwise the platform's
    user cache directory (`~/Library/Caches/nokap` on macOS, `$XDG_CACHE_HOME/nokap` or
    `~/.cache/nokap` on Linux, `%LOCALAPPDATA%\\nokap\\Cache` on Windows).
    """
    env = os.environ.get("NOKAP_CACHE_DIR")
    if env:
        return Path(env).expanduser()

    plat = current_platform()
    if plat == "macos":
        return Path.home() / "Library" / "Caches" / "nokap"
    if plat == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "nokap" / "Cache"
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "nokap"


def chrome_platform() -> str:
    """The Chrome for Testing platform key for this machine (e.g., `mac-arm64`)."""
    plat = current_platform()
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")

    if plat == "macos":
        return "mac-arm64" if arm else "mac-x64"
    if plat == "linux":
        return "linux-arm64" if arm else "linux64"
    # Windows on ARM runs the x64 build under emulation
    return "win64" if machine in ("amd64", "x86_64", "arm64", "aarch64") else "win32"


def _executable_name() -> str:
    windows = current_platform() == "windows"
    return f"{_HEADLESS_SHELL}.exe" if windows else _HEADLESS_SHELL


def _executable_path(version_dir: Path, plat: str) -> Path:
    return version_dir / f"{_HEADLESS_SHELL}-{plat}" / _executable_name()


def _version_key(name: str) -> tuple[int, ...]:
    """Sort key for version dir names; empty for anything that isn't a version."""
    if not re.fullmatch(r"\d+(\.\d+)*", name):
        return ()
    return tuple(int(p) for p in name.split("."))


def installed_headless_shell() -> str | None:
    """
    Path to the newest chrome-headless-shell installed by `install_chrome()`, or None.
    """
    root = cache_dir() / _HEADLESS_SHELL
    if not root.is_dir():
        return None

    plat = chrome_platform()
    versions = sorted(
        (d for d in root.iterdir() if d.is_dir() and _version_key(d.name)),
        key=lambda d: _version_key(d.name),
        reverse=True,
    )
    for version_dir in versions:
        exe = _executable_path(version_dir, plat)
        if exe.is_file():
            return str(exe)
    return None


def _fetch_json(name: str) -> Any:
    with urllib.request.urlopen(f"{_CFT_BASE}/{name}", timeout=30) as resp:
        return json.load(resp)


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def _resolve(version: str, plat: str) -> tuple[str, str]:
    """Resolve a channel, milestone, or exact version to (version, download URL)."""
    spec = version.strip().lower()

    if spec in _CHANNELS:
        data = _fetch_json("last-known-good-versions-with-downloads.json")
        entry = data["channels"][spec.capitalize()]
    elif re.fullmatch(r"\d+", spec):
        data = _fetch_json("latest-versions-per-milestone-with-downloads.json")
        entry = data["milestones"].get(spec)
        if entry is None:
            raise NokapError(
                f"Chrome for Testing has no release for milestone {version!r}."
            )
    elif re.fullmatch(r"\d+(\.\d+){3}", spec):
        data = _fetch_json("known-good-versions-with-downloads.json")
        entry = next((v for v in data["versions"] if v["version"] == spec), None)
        if entry is None:
            raise NokapError(
                f"Chrome for Testing has no build for version {version!r}."
            )
    else:
        raise NokapError(
            f"Invalid version {version!r}. Use a channel ({', '.join(_CHANNELS)}), "
            "a milestone (e.g., '156'), or an exact version (e.g., '156.0.8078.80')."
        )

    for download in entry.get("downloads", {}).get(_HEADLESS_SHELL, []):
        if download["platform"] == plat:
            return entry["version"], download["url"]
    raise NokapError(
        "Chrome for Testing has no chrome-headless-shell build of "
        f"{entry['version']} for {plat}."
    )


def _extract(archive: Path, dest: Path) -> None:
    """Extract a zip, keeping file modes (zipfile drops the executable bit)."""
    dest_resolved = dest.resolve()
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            target = (dest / info.filename).resolve()
            if not target.is_relative_to(dest_resolved):
                raise NokapError(
                    f"Refusing to extract {info.filename!r} outside {dest}."
                )
            zf.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                os.chmod(target, mode)


def install_chrome(version: str = "stable", *, force: bool = False) -> str:
    """
    Download `chrome-headless-shell` from Chrome for Testing into nokap's cache.

    `chrome-headless-shell` is Chrome's standalone headless build. It starts in
    environments where full Chrome can't, such as the macOS sandboxes used by coding
    agents, and it starts faster. Once installed, `find_chrome()` prefers it over a
    system Chrome (`CHROME_PATH` still takes precedence). Nothing is downloaded unless
    you call this function (or run `nokap install-chrome`).

    Parameters
    ----------
    version
        A release channel (`"stable"`, `"beta"`, `"dev"`, `"canary"`), a milestone such
        as `"156"`, or an exact version such as `"156.0.8078.80"`.
    force
        Reinstall even if this version is already present.

    Returns
    -------
    str
        Path to the `chrome-headless-shell` executable.

    Raises
    ------
    NokapError
        If the version can't be resolved, no build exists for this platform, or the
        download fails.

    Examples
    --------
    ```python
    import nokap

    path = nokap.install_chrome()
    nokap.find_chrome() == path  # True unless CHROME_PATH is set
    ```
    """
    plat = chrome_platform()
    try:
        resolved, url = _resolve(version, plat)
    except OSError as e:
        raise NokapError(f"Could not reach Chrome for Testing: {e}") from e

    root = cache_dir() / _HEADLESS_SHELL
    final = root / resolved
    exe = _executable_path(final, plat)
    if exe.is_file() and not force:
        return str(exe)

    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{resolved}-", dir=root))
    try:
        archive = staging / "download.zip"
        try:
            _download(url, archive)
        except OSError as e:
            raise NokapError(f"Downloading {url} failed: {e}") from e
        unpacked = staging / "unpacked"
        _extract(archive, unpacked)
        if not _executable_path(unpacked, plat).is_file():
            raise NokapError(
                f"The archive at {url} does not contain {_executable_name()}."
            )
        if final.exists():
            shutil.rmtree(final)
        os.replace(unpacked, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return str(exe)

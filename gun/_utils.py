from __future__ import annotations

import platform
import socket
import sys
from pathlib import Path
from urllib.parse import quote


def file_url(path: str | Path) -> str:
    """Convert a local file path to a file:/// URL."""
    p = Path(path).resolve()
    # On Windows, paths need forward slashes and a leading /
    if sys.platform == "win32":
        return "file:///" + quote(str(p).replace("\\", "/"), safe=":/")
    return "file://" + quote(str(p), safe="/:")


def find_open_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def is_url(s: str) -> bool:
    """Check if a string looks like a URL (http/https/file)."""
    return s.startswith(("http://", "https://", "file://"))


def current_platform() -> str:
    """Return normalized platform name: 'macos', 'linux', or 'windows'."""
    system = platform.system().lower()
    if system == "darwin":
        return "macos"
    if system == "windows":
        return "windows"
    return "linux"

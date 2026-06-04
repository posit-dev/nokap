from __future__ import annotations

import atexit
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from ._utils import current_platform, find_open_port


def find_chrome() -> str:
    """
    Locate the Chrome or Chromium binary on the system.

    Search order:
    1. CHROME_PATH environment variable
    2. Platform-specific known locations

    Returns the path to the Chrome executable.

    Raises
    ------
    RuntimeError
        If Chrome cannot be found.
    """
    # Check environment variable first
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    plat = current_platform()

    if plat == "macos":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

    elif plat == "linux":
        names = [
            "google-chrome",
            "google-chrome-stable",
            "chromium-browser",
            "chromium",
            "microsoft-edge",
        ]
        for name in names:
            path = shutil.which(name)
            if path:
                return path

    elif plat == "windows":
        # Common Windows install paths
        program_files = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        rel_paths = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"Chromium\Application\chrome.exe",
        ]
        for base in program_files:
            if not base:
                continue
            for rel in rel_paths:
                full = os.path.join(base, rel)
                if os.path.isfile(full):
                    return full

    raise RuntimeError(
        "Chrome/Chromium not found. Install Chrome or set the CHROME_PATH "
        "environment variable to the Chrome executable path."
    )


def _default_chrome_args(port: int, headless: bool = True) -> list[str]:
    """Build the default Chrome launch arguments."""
    args = [
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-client-side-phishing-detection",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-hang-monitor",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-sync",
        "--disable-translate",
        "--metrics-recording-only",
        "--safebrowsing-disable-auto-update",
        "--password-store=basic",
        "--use-mock-keychain",
    ]
    if headless:
        args.append("--headless")
        args.append("--disable-gpu")
    return args


class Chrome:
    """
    Manages a headless Chrome browser process.

    Launches Chrome with remote debugging enabled and provides the WebSocket
    URL for CDP communication.

    Parameters
    ----------
    path
        Path to Chrome executable. If None, auto-detected via `find_chrome()`.
    headless
        Whether to run in headless mode.
    extra_args
        Additional command-line arguments to pass to Chrome.
    timeout
        Maximum seconds to wait for Chrome to start and report its WS URL.
    """

    def __init__(
        self,
        path: str | None = None,
        headless: bool = True,
        extra_args: list[str] | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._path = path or find_chrome()
        self._port = find_open_port()
        self._headless = headless
        self._process: subprocess.Popen[bytes] | None = None
        self._ws_url: str | None = None

        args = [self._path] + _default_chrome_args(self._port, headless)
        if extra_args:
            args.extend(extra_args)
        args.append("about:blank")

        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for Chrome to report the DevTools WebSocket URL on stderr
        self._ws_url = self._wait_for_ws_url(timeout)

        # Register cleanup
        atexit.register(self.close)

    def _wait_for_ws_url(self, timeout: float) -> str:
        """Poll stderr for the DevTools listening message."""
        assert self._process is not None
        assert self._process.stderr is not None

        deadline = time.monotonic() + timeout
        pattern = re.compile(r"DevTools listening on (ws://\S+)")
        accumulated = b""

        while time.monotonic() < deadline:
            # Read in small chunks with a short timeout
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break

            chunk = b""
            try:
                # Non-blocking read approach: read one byte at a time until newline
                # This works because Chrome writes line-buffered to stderr
                while True:
                    byte = self._process.stderr.read(1)
                    if not byte:
                        break
                    chunk += byte
                    if byte == b"\n":
                        break
            except OSError:
                break

            if chunk:
                accumulated += chunk
                text = accumulated.decode("utf-8", errors="replace")
                match = pattern.search(text)
                if match:
                    return match.group(1)

            # Check if process has died
            if self._process.poll() is not None:
                stderr_text = accumulated.decode("utf-8", errors="replace")
                raise RuntimeError(
                    f"Chrome process exited unexpectedly (code {self._process.returncode}).\n"
                    f"stderr: {stderr_text[:500]}"
                )

            time.sleep(0.05)

        raise RuntimeError(
            f"Timed out after {timeout}s waiting for Chrome DevTools WebSocket URL. "
            "Ensure Chrome is installed and working."
        )

    @property
    def ws_url(self) -> str:
        """The WebSocket URL for CDP communication."""
        if self._ws_url is None:
            raise RuntimeError("Chrome is not running.")
        return self._ws_url

    @property
    def port(self) -> int:
        """The remote debugging port."""
        return self._port

    @property
    def pid(self) -> int | None:
        """The Chrome process ID, or None if not running."""
        return self._process.pid if self._process else None

    def is_alive(self) -> bool:
        """Check if the Chrome process is still running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    def close(self) -> None:
        """Terminate the Chrome process."""
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._process = None
        self._ws_url = None

        # Unregister atexit handler (ignore if already unregistered)
        try:
            atexit.unregister(self.close)
        except Exception:
            pass

    def __enter__(self) -> Chrome:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()

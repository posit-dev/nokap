from __future__ import annotations

import atexit
import os
import re
import shlex
import shutil
import subprocess
import time

from ._errors import ChromeNotFoundError, ChromeStartError
from ._install import installed_headless_shell
from ._utils import current_platform, find_open_port

# Seatbelt denies `mach-register`, which multi-process Chrome needs to hand ports to its
# child processes; `--single-process` avoids the rendezvous server entirely
_MACH_DENIED = re.compile(r"bootstrap_check_in .*Permission denied")


def find_chrome() -> str:
    """
    Locate the Chrome or Chromium binary on the system.

    Search order:
    1. CHROME_PATH environment variable
    2. chrome-headless-shell installed by `nokap install-chrome`
    3. chrome-headless-shell on PATH
    4. Platform-specific known locations

    Returns the path to the Chrome executable.

    Raises
    ------
    ChromeNotFoundError
        If Chrome cannot be found.
    """
    # Check environment variable first
    env_path = os.environ.get("CHROME_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    # chrome-headless-shell starts faster and works in sandboxes where full Chrome can't
    shell = installed_headless_shell() or shutil.which("chrome-headless-shell")
    if shell:
        return shell

    plat = current_platform()

    if plat == "macos":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/"
            "Google Chrome Canary",
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

    raise ChromeNotFoundError()


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


def _env_chrome_args() -> list[str]:
    """Extra Chrome arguments from the NOKAP_CHROME_ARGS environment variable."""
    value = os.environ.get("NOKAP_CHROME_ARGS", "").strip()
    return shlex.split(value, posix=os.name != "nt") if value else []


def is_headless_shell(path: str) -> bool:
    """Whether `path` points to a chrome-headless-shell binary."""
    return os.path.basename(path).lower().startswith("chrome-headless-shell")


def _sandbox_hint(path: str, returncode: int, stderr: str) -> str | None:
    """Explain launch failures that come from running inside a macOS sandbox."""
    if _MACH_DENIED.search(stderr):
        return (
            "Chrome was denied mach-register, which happens inside a macOS sandbox; "
            "it must run there with --single-process."
        )
    if (
        current_platform() == "macos"
        and returncode == -6
        and not stderr.strip()
        and not is_headless_shell(path)
    ):
        return (
            "Full Chrome aborts like this inside a macOS sandbox, where it can't "
            "register with LaunchServices. Run `nokap install-chrome` to use "
            "chrome-headless-shell, which works there."
        )
    return None


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
        Additional command-line arguments to pass to Chrome. These come after any
        arguments in the NOKAP_CHROME_ARGS environment variable.
    timeout
        Maximum seconds to wait for Chrome to start and report its WS URL.

    Notes
    -----
    If Chrome fails because a macOS sandbox denies it mach-register (as Seatbelt-based
    agent sandboxes do), nokap retries once with `--single-process`.
    """

    def __init__(
        self,
        path: str | None = None,
        headless: bool = True,
        extra_args: list[str] | None = None,
        timeout: float = 20.0,
    ) -> None:
        # Set first so close() and __del__ work if anything below raises
        self._process: subprocess.Popen[bytes] | None = None
        self._ws_url: str | None = None
        self._port = 0

        self._path = path or find_chrome()
        self._headless = headless

        args = _env_chrome_args() + list(extra_args or [])
        try:
            self._launch(args, timeout)
        except ChromeStartError as e:
            if "--single-process" in args or not _MACH_DENIED.search(e.stderr):
                raise
            self._launch([*args, "--single-process"], timeout)

        # Register cleanup
        atexit.register(self.close)

    def _launch(self, args: list[str], timeout: float) -> None:
        """Start Chrome and wait for its DevTools URL, cleaning up on failure."""
        try:
            self._port = find_open_port()
        except OSError as e:
            raise ChromeStartError(
                f"Could not bind a local port for Chrome's DevTools endpoint ({e}). "
                "If nokap runs inside a sandbox, allow binding to localhost (for "
                "mcp-console, set sandbox.network.allow_local_binding: true)."
            ) from e

        cmd = [
            self._path,
            *_default_chrome_args(self._port, self._headless),
            *args,
            "about:blank",
        ]
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Wait for Chrome to report the DevTools WebSocket URL on stderr
        try:
            self._ws_url = self._wait_for_ws_url(timeout)
        except BaseException:
            self.close()
            raise

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
                returncode = self._process.returncode
                msg = f"Chrome process exited unexpectedly (code {returncode})"
                hint = _sandbox_hint(self._path, returncode, stderr_text)
                if hint:
                    msg += f". {hint}"
                raise ChromeStartError(msg, stderr=stderr_text)

            time.sleep(0.05)

        raise ChromeStartError(
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
        if getattr(self, "_process", None) is not None:
            self.close()

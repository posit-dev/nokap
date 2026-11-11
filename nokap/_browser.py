from __future__ import annotations

import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import ExitStack
from typing import BinaryIO, cast

from ._errors import ChromeNotFoundError, ChromeStartError, ConnectionError_
from ._pipe import SyncPipeCDP
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


def _default_chrome_args(port: int | None, headless: bool = True) -> list[str]:
    """Build the default Chrome launch arguments."""
    args = [
        "--remote-debugging-pipe"
        if port is None
        else f"--remote-debugging-port={port}",
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

    Launches Chrome with remote debugging enabled over WebSocket or pipes.

    Parameters
    ----------
    path
        Path to Chrome executable. If None, auto-detected via `find_chrome()`.
    headless
        Whether to run in headless mode.
    extra_args
        Additional command-line arguments to pass to Chrome. When None, reads
        NOKAP_CHROME_ARGS, a JSON array of strings.
    timeout
        Maximum seconds to wait for Chrome's DevTools endpoint to become ready.
    transport
        "websocket" or "pipe". Defaults to NOKAP_TRANSPORT, or "websocket"
        when unset. Pipe transport requires POSIX.
    """

    def __init__(
        self,
        path: str | None = None,
        headless: bool = True,
        extra_args: list[str] | None = None,
        timeout: float = 20.0,
        transport: str | None = None,
    ) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._resources = ExitStack()
        self._pipe_read: int | None = None
        self._pipe_write: int | None = None
        self._stderr_file: BinaryIO | None = None
        self._ws_url: str | None = None
        self._transport = transport or os.environ.get("NOKAP_TRANSPORT", "websocket")
        if self._transport not in ("websocket", "pipe"):
            raise ValueError("NOKAP_TRANSPORT must be 'websocket' or 'pipe'")
        if self._transport == "pipe" and os.name != "posix":
            raise NotImplementedError("Pipe transport currently requires POSIX")
        if extra_args is None:
            environment_args = json.loads(os.environ.get("NOKAP_CHROME_ARGS", "[]"))
            if not isinstance(environment_args, list) or not all(
                isinstance(argument, str)
                for argument in cast(list[object], environment_args)
            ):
                raise ValueError("NOKAP_CHROME_ARGS must be a JSON array of strings")
            extra_args = cast(list[str], environment_args)
        self._path = path or find_chrome()
        self._port = find_open_port() if self._transport == "websocket" else None
        self._headless = headless

        args = [self._path] + _default_chrome_args(self._port, headless)
        if self._transport == "pipe" and not any(
            argument.partition("=")[0] == "--user-data-dir"
            for argument in extra_args or []
        ):
            profile = self._resources.enter_context(
                tempfile.TemporaryDirectory(prefix="nokap-chrome-")
            )
            args.append(f"--user-data-dir={profile}")
        if extra_args:
            args.extend(extra_args)
        args.append("about:blank")

        try:
            if self._transport == "pipe":
                self._start_pipe(args)
                self._wait_for_pipe(timeout)
            else:
                self._process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                self._ws_url = self._wait_for_ws_url(timeout)
        except Exception:
            self.close()
            raise

        # Register cleanup
        atexit.register(self.close)

    def _start_pipe(self, args: list[str]) -> None:
        chrome_read, self._pipe_write = os.pipe()
        self._resources.callback(os.close, self._pipe_write)
        self._pipe_read, chrome_write = os.pipe()
        self._resources.callback(os.close, self._pipe_read)
        self._stderr_file = self._resources.enter_context(
            tempfile.TemporaryFile()  # noqa: SIM115 - ExitStack owns the file.
        )
        # Map descriptors in a fresh interpreter, not a preexec_fn in the
        # caller's potentially multithreaded process. exec preserves Chrome's PID.
        bootstrap = """
import os, sys
source_read, source_write = int(sys.argv[1]), int(sys.argv[2])
read_fd, write_fd = os.dup(source_read), os.dup(source_write)
os.dup2(read_fd, 3)
os.dup2(write_fd, 4)
# dup2(fd, fd) preserves its close-on-exec flag.
os.set_inheritable(3, True)
os.set_inheritable(4, True)
for fd in {source_read, source_write, read_fd, write_fd} - {3, 4}:
    os.close(fd)
os.execv(sys.argv[3], sys.argv[3:])
"""
        try:
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    bootstrap,
                    str(chrome_read),
                    str(chrome_write),
                    *args,
                ],
                pass_fds=(chrome_read, chrome_write),
                stdout=subprocess.DEVNULL,
                stderr=self._stderr_file,
            )
        finally:
            os.close(chrome_read)
            os.close(chrome_write)

    def _wait_for_pipe(self, timeout: float) -> None:
        connection = SyncPipeCDP(*self.pipes, timeout=timeout)
        try:
            connection.connect()
        except FutureTimeoutError as error:
            raise ChromeStartError(
                f"Timed out after {timeout}s waiting for Chrome DevTools pipe",
                stderr=self.stderr,
            ) from error
        except (ConnectionError_, OSError) as error:
            raise ChromeStartError(
                "Chrome DevTools pipe failed to start", stderr=self.stderr
            ) from error
        finally:
            connection.close()

    @property
    def transport(self) -> str:
        """The selected DevTools transport."""
        return self._transport

    @property
    def pipes(self) -> tuple[int, int]:
        """The read and write descriptors for pipe-mode DevTools communication."""
        if self._pipe_read is None or self._pipe_write is None:
            raise RuntimeError("Chrome is not running with pipe transport")
        return self._pipe_read, self._pipe_write

    @property
    def stderr(self) -> str:
        """Chrome's startup diagnostics when using pipe transport."""
        if self._stderr_file is None:
            return ""
        self._stderr_file.seek(0)
        return self._stderr_file.read().decode("utf-8", errors="replace")

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
                msg = (
                    "Chrome process exited unexpectedly"
                    f" (code {self._process.returncode})"
                )
                raise ChromeStartError(msg, stderr=stderr_text)

            time.sleep(0.05)

        raise ChromeStartError(
            f"Timed out after {timeout}s waiting for Chrome DevTools WebSocket URL. "
            "Ensure Chrome is installed and working."
        )

    @property
    def ws_url(self) -> str:
        """The WebSocket URL for CDP communication."""
        if self._transport == "pipe":
            raise RuntimeError("Pipe transport has no WebSocket URL")
        if self._ws_url is None:
            raise RuntimeError("Chrome is not running.")
        return self._ws_url

    @property
    def port(self) -> int:
        """The remote debugging port."""
        if self._port is None:
            raise RuntimeError("Pipe transport has no debugging port")
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
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._process = None
        self._ws_url = None
        self._resources.close()
        self._pipe_read = self._pipe_write = None
        self._stderr_file = None

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

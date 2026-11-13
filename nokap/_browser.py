from __future__ import annotations

import atexit
import errno
import json
import os
import re
import selectors
import shlex
import shutil
import subprocess
import tempfile
import time
from contextlib import ExitStack, suppress
from typing import BinaryIO

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from ._errors import ChromeNotFoundError, ChromeStartError, ConnectionError_
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


def _split_args(value: str, windows: bool = False) -> list[str]:
    """
    Split a command-line string with shell-style quoting.

    On Windows, backslashes are kept literally so paths like `C:\\dir` survive.
    """
    lexer = shlex.shlex(value, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    if windows:
        lexer.escape = ""
    return list(lexer)


def _env_chrome_args() -> list[str]:
    """Extra Chrome arguments from the NOKAP_CHROME_ARGS environment variable."""
    value = os.environ.get("NOKAP_CHROME_ARGS", "").strip()
    return _split_args(value, windows=os.name == "nt") if value else []


def is_headless_shell(path: str) -> bool:
    """Whether `path` points to a chrome-headless-shell binary."""
    return os.path.basename(path).lower().startswith("chrome-headless-shell")


def _select_transport(transport: str | None) -> str:
    """Resolve the DevTools transport from the argument, environment, or platform."""
    source = "transport" if transport else "NOKAP_TRANSPORT"
    value = transport or os.environ.get("NOKAP_TRANSPORT", "")
    # An empty variable counts as unset
    selected = value.strip().lower() or ("pipe" if os.name == "posix" else "websocket")
    if selected not in ("websocket", "pipe"):
        raise ValueError(f"{source} must be 'websocket' or 'pipe', not {value!r}")
    if selected == "pipe" and os.name != "posix":
        raise NotImplementedError("Pipe transport currently requires POSIX")
    return selected


def _macos_user_dirs_unavailable() -> bool:
    if current_platform() != "macos":
        return False
    try:
        # _CS_DARWIN_USER_DIR and _CS_DARWIN_USER_CACHE_DIR from macOS unistd.h;
        # Python accepts the values but does not expose their names. Chrome needs
        # these paths to initialize child sandboxes. In restricted environments,
        # confstr can fail with EIO before Chrome reports a Mach registration error.
        for name in (65536, 65538):
            os.confstr(name)
    except OSError as error:
        if error.errno != errno.EIO:
            raise
        return True
    return False


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

    Launches Chrome with remote debugging enabled over WebSocket or pipes.

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
        Maximum seconds to wait for Chrome's DevTools endpoint to become ready.
    transport
        "websocket" or "pipe". Defaults to NOKAP_TRANSPORT when set, otherwise
        "pipe" on macOS/Linux and "websocket" on Windows. Pipe transport
        requires POSIX. Select "websocket" to use ws_url or port.

    Notes
    -----
    On macOS, nokap selects `--single-process` when the user-directory queries
    needed for Chrome's child sandboxes fail with EIO. If Chrome instead reports
    a Mach registration denial, nokap retries once with `--single-process`.
    """

    def __init__(
        self,
        path: str | None = None,
        headless: bool = True,
        extra_args: list[str] | None = None,
        timeout: float = 20.0,
        transport: str | None = None,
    ) -> None:
        # Set first so close() and __del__ work if anything below raises
        self._process: subprocess.Popen[bytes] | None = None
        self._resources = ExitStack()
        self._pipe_read: int | None = None
        self._pipe_write: int | None = None
        self._stderr_file: BinaryIO | None = None
        self._ws_url: str | None = None
        self._ready = False
        self._transport = _select_transport(transport)
        self._port: int | None = None

        self._path = path or find_chrome()
        self._headless = headless

        args = _env_chrome_args() + list(extra_args or [])
        if (
            "--single-process" not in args
            and "--no-sandbox" not in args
            and _macos_user_dirs_unavailable()
        ):
            args.append("--single-process")
        try:
            self._launch(args, timeout)
        except ChromeStartError as e:
            if "--single-process" in args or not _MACH_DENIED.search(e.stderr):
                raise
            self._launch([*args, "--single-process"], timeout)

        # Register cleanup
        atexit.register(self.close)

    def _launch(self, args: list[str], timeout: float) -> None:
        """Start Chrome and wait for DevTools, cleaning up on failure."""
        if self._transport == "websocket":
            try:
                self._port = find_open_port()
            except OSError as e:
                raise ChromeStartError(
                    "Could not bind a local port for Chrome's DevTools endpoint "
                    f"({e}). "
                    "On POSIX, set NOKAP_TRANSPORT=pipe. Alternatively, allow binding "
                    "to localhost (for mcp-console, set "
                    "sandbox.network.allow_local_binding: true)."
                ) from e

        cmd = [
            self._path,
            *_default_chrome_args(self._port, self._headless),
        ]
        if not any(
            argument.partition("=")[0] == "--user-data-dir" for argument in args
        ):
            # Lingering Chrome helpers can hold or recreate profile files. A failed
            # removal must not mask a launch error or make close() raise.
            profile = self._resources.enter_context(
                tempfile.TemporaryDirectory(
                    prefix="nokap-chrome-", ignore_cleanup_errors=True
                )
            )
            cmd.append(f"--user-data-dir={profile}")
        cmd.extend([*args, "about:blank"])

        try:
            if self._transport == "pipe":
                self._start_pipe(cmd)
                self._wait_for_pipe(timeout)
            else:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                self._ws_url = self._wait_for_ws_url(timeout)
            self._ready = True
        except BaseException:
            self.close()
            raise

    def _start_pipe(self, args: list[str]) -> None:
        # Popen puts the pipes on stdin/stdout and /bin/sh moves them to fds 3 and 4
        # before exec, which preserves Chrome's PID. This avoids a preexec_fn in a
        # potentially multithreaded caller and does not rely on sys.executable,
        # which frozen or embedded Pythons may not provide. Redirections attached
        # to exec stay inheritable even in ksh, unlike a bare `exec 3<&0`.
        remap = 'exec "$0" "$@" 3<&0 4>&1 0</dev/null 1>/dev/null'
        with ExitStack() as child_resources:
            chrome_read, self._pipe_write = os.pipe()
            child_resources.callback(os.close, chrome_read)
            self._resources.callback(os.close, self._pipe_write)
            self._pipe_read, chrome_write = os.pipe()
            child_resources.callback(os.close, chrome_write)
            self._resources.callback(os.close, self._pipe_read)
            self._stderr_file = self._resources.enter_context(
                tempfile.TemporaryFile()  # noqa: SIM115 - ExitStack owns the file.
            )
            self._process = subprocess.Popen(
                ["/bin/sh", "-c", remap, *args],
                stdin=chrome_read,
                stdout=chrome_write,
                stderr=self._stderr_file,
            )

    def _wait_for_pipe(self, timeout: float) -> None:
        """Wait for Chrome to answer one command over the DevTools pipe."""
        assert self._process is not None
        read_fd, write_fd = self.pipes
        deadline = time.monotonic() + timeout
        received = bytearray()
        try:
            os.write(write_fd, b'{"id":1,"method":"Browser.getVersion"}\0')
            with selectors.DefaultSelector() as selector:
                selector.register(read_fd, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise ChromeStartError(
                            f"Timed out after {timeout}s waiting for Chrome "
                            "DevTools pipe",
                            stderr=self.stderr,
                        )
                    # Read single bytes so that no part of a later message is
                    # consumed here; the caller's connection reads everything after.
                    byte = os.read(read_fd, 1)
                    if not byte:
                        raise ConnectionError_("Chrome DevTools pipe closed")
                    if byte != b"\0":
                        received += byte
                    elif json.loads(received).get("id") == 1:
                        return
                    else:
                        received.clear()
        except (ConnectionError_, OSError, ValueError) as error:
            # The pipe can close before Chrome exits and finishes writing stderr
            with suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=1)
            stderr = self.stderr
            message = "Chrome DevTools pipe failed to start"
            hint = _sandbox_hint(self._path, self._process.returncode or 0, stderr)
            if hint:
                message += f". {hint}"
            raise ChromeStartError(message, stderr=stderr) from error

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
        """Shut down Chrome before removing its temporary profile."""
        if self._ready and self.is_alive():
            assert self._process is not None
            try:
                self._request_shutdown()
                # Chrome allows its network service 10s to flush profile data.
                self._process.wait(timeout=15)
            except (OSError, WebSocketException, subprocess.TimeoutExpired):
                pass
        # Failed startup and unresponsive browsers still need termination.
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
        self._process = None
        self._ws_url = None
        self._ready = False
        self._resources.close()
        self._pipe_read = self._pipe_write = None
        self._stderr_file = None

        # Unregister atexit handler (ignore if already unregistered)
        try:
            atexit.unregister(self.close)
        except Exception:
            pass

    def _request_shutdown(self) -> None:
        command = '{"id":0,"method":"Browser.close"}'
        if self._transport == "pipe":
            # Do not compete with the caller's CDP connection for pipe responses.
            os.write(self.pipes[1], command.encode() + b"\0")
        else:
            with connect(self.ws_url, open_timeout=5, close_timeout=1) as connection:
                connection.send(command)

    def __enter__(self) -> Chrome:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        if hasattr(self, "_resources"):
            self.close()

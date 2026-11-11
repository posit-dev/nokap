import gc
import os
import stat
import sys
from unittest.mock import patch

import pytest

from nokap._browser import (
    Chrome,
    _env_chrome_args,
    _sandbox_hint,
    _split_args,
    find_chrome,
    is_headless_shell,
)
from nokap._errors import ChromeNotFoundError, ChromeStartError
from nokap._install import chrome_platform

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="uses shell scripts")

MACH_DENIED = (
    "[0101/000000.000000:FATAL:mach_port_rendezvous_mac.cc(155)] Check failed: "
    "kr == KERN_SUCCESS. bootstrap_check_in "
    "org.chromium.Chromium.MachPortRendezvousServer.123: Permission denied (1100)"
)


def test_find_chrome_env_var(tmp_path):
    # Create a fake chrome binary
    fake_chrome = tmp_path / "chrome"
    fake_chrome.touch()

    with patch.dict(os.environ, {"CHROME_PATH": str(fake_chrome)}):
        result = find_chrome()
        assert result == str(fake_chrome)


def test_find_chrome_env_var_missing_file():
    with patch.dict(os.environ, {"CHROME_PATH": "/nonexistent/chrome"}):
        # Should fall through to platform search
        # May or may not find Chrome depending on system
        try:
            find_chrome()
        except RuntimeError as e:
            assert "Chrome/Chromium not found" in str(e)


def test_find_chrome_no_env_var():
    with patch.dict(os.environ, {}, clear=False):
        # Remove CHROME_PATH if set
        os.environ.pop("CHROME_PATH", None)
        # This may succeed or fail depending on whether Chrome is installed
        try:
            path = find_chrome()
            assert os.path.isfile(path)
        except RuntimeError:
            pass  # Chrome not installed, that's fine for CI


# ---------------------------------------------------------------------------
# chrome-headless-shell discovery
# ---------------------------------------------------------------------------


def _fake_install(cache, version):
    exe_name = (
        "chrome-headless-shell.exe"
        if sys.platform == "win32"
        else "chrome-headless-shell"
    )
    exe = (
        cache
        / "chrome-headless-shell"
        / version
        / f"chrome-headless-shell-{chrome_platform()}"
        / exe_name
    )
    exe.parent.mkdir(parents=True)
    exe.touch()
    return str(exe)


def test_find_chrome_prefers_installed_headless_shell(tmp_path):
    exe = _fake_install(tmp_path, "156.0.8078.80")
    with patch.dict(os.environ, {"NOKAP_CACHE_DIR": str(tmp_path)}):
        os.environ.pop("CHROME_PATH", None)
        assert find_chrome() == exe


def test_find_chrome_picks_newest_installed_version(tmp_path):
    _fake_install(tmp_path, "99.0.4844.51")
    newest = _fake_install(tmp_path, "156.0.8078.80")
    _fake_install(tmp_path, "120.0.6099.109")
    with patch.dict(os.environ, {"NOKAP_CACHE_DIR": str(tmp_path)}):
        os.environ.pop("CHROME_PATH", None)
        assert find_chrome() == newest


def test_find_chrome_env_var_beats_installed_headless_shell(tmp_path):
    _fake_install(tmp_path / "cache", "156.0.8078.80")
    fake_chrome = tmp_path / "chrome"
    fake_chrome.touch()
    env = {"NOKAP_CACHE_DIR": str(tmp_path / "cache"), "CHROME_PATH": str(fake_chrome)}
    with patch.dict(os.environ, env):
        assert find_chrome() == str(fake_chrome)


@posix_only
def test_find_chrome_headless_shell_on_path(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shell = bin_dir / "chrome-headless-shell"
    shell.touch()
    shell.chmod(0o755)
    env = {"NOKAP_CACHE_DIR": str(tmp_path / "empty"), "PATH": str(bin_dir)}
    with patch.dict(os.environ, env):
        os.environ.pop("CHROME_PATH", None)
        assert find_chrome() == str(shell)


def test_is_headless_shell():
    assert is_headless_shell("/x/chrome-headless-shell-mac-arm64/chrome-headless-shell")
    assert is_headless_shell("chrome-headless-shell.exe")
    assert not is_headless_shell(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )


# ---------------------------------------------------------------------------
# Launch arguments and failure handling
# ---------------------------------------------------------------------------


def test_env_chrome_args():
    with patch.dict(
        os.environ, {"NOKAP_CHROME_ARGS": ' --single-process --lang="en US" '}
    ):
        assert _env_chrome_args() == ["--single-process", "--lang=en US"]
    with patch.dict(os.environ, {"NOKAP_CHROME_ARGS": ""}):
        assert _env_chrome_args() == []
    with patch.dict(os.environ, {}):
        os.environ.pop("NOKAP_CHROME_ARGS", None)
        assert _env_chrome_args() == []


@pytest.mark.parametrize("windows", [False, True])
def test_split_args_quoting(windows):
    value = """--a --lang="en US" '--b=c d' --e#f"""
    assert _split_args(value, windows) == ["--a", "--lang=en US", "--b=c d", "--e#f"]


def test_split_args_backslashes():
    value = r'--user-data-dir=C:\tmp\nokap --x="C:\Program Files\y"'
    assert _split_args(value, windows=True) == [
        r"--user-data-dir=C:\tmp\nokap",
        r"--x=C:\Program Files\y",
    ]
    # POSIX shells treat backslash as an escape
    assert _split_args(r"--a=b\ c", windows=False) == ["--a=b c"]


def test_del_is_safe_on_uninitialized_instance():
    # __del__ runs even when __init__ never ran or raised early
    Chrome.__new__(Chrome).__del__()


def test_failed_init_leaves_usable_instance():
    with (
        patch("nokap._browser.find_chrome", side_effect=ChromeNotFoundError()),
        pytest.raises(ChromeNotFoundError),
    ):
        Chrome()
    gc.collect()


def test_port_bind_failure_explains_sandbox(tmp_path):
    with (
        patch(
            "nokap._browser.find_open_port", side_effect=PermissionError(1, "denied")
        ),
        pytest.raises(ChromeStartError, match="allow_local_binding"),
    ):
        Chrome(path=str(tmp_path / "chrome"))


def test_sandbox_hint_mach_denied():
    hint = _sandbox_hint("/x/chrome-headless-shell", -5, MACH_DENIED)
    assert hint is not None
    assert "--single-process" in hint


def test_sandbox_hint_full_chrome_sigabrt_on_macos():
    full = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    with patch("nokap._browser.current_platform", return_value="macos"):
        hint = _sandbox_hint(full, -6, "")
        assert hint is not None
        assert "nokap install-chrome" in hint
        # Not for headless-shell, other exit codes, or when Chrome said something
        assert _sandbox_hint("/x/chrome-headless-shell", -6, "") is None
        assert _sandbox_hint(full, 1, "") is None
        assert _sandbox_hint(full, -6, "some error") is None
    with patch("nokap._browser.current_platform", return_value="linux"):
        assert _sandbox_hint(full, -6, "") is None


def _write_script(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


def _launches(argv_file):
    """Each launch is recorded as one line of space-separated args."""
    return [line.split(" ") for line in argv_file.read_text().splitlines()]


# Records its args, then behaves like Chrome once DevTools is up
_OK_BODY = """\
echo "$*" >> "$NOKAP_TEST_ARGV"
echo "DevTools listening on ws://127.0.0.1:9/devtools/browser/fake" >&2
exec sleep 30
"""


@posix_only
def test_launch_arg_order(tmp_path):
    chrome = _write_script(tmp_path / "chrome", _OK_BODY)
    argv = tmp_path / "argv"
    env = {"NOKAP_TEST_ARGV": str(argv), "NOKAP_CHROME_ARGS": "--env-a --env-b"}
    with patch.dict(os.environ, env), Chrome(path=chrome, extra_args=["--extra"]) as c:
        assert c.ws_url == "ws://127.0.0.1:9/devtools/browser/fake"
        assert c.is_alive()
    (args,) = _launches(argv)
    assert args[0] == f"--remote-debugging-port={c.port}"
    assert args[-4:] == ["--env-a", "--env-b", "--extra", "about:blank"]
    assert not c.is_alive()


@posix_only
def test_mach_denial_retries_with_single_process(tmp_path):
    body = f"""\
echo "$*" >> "$NOKAP_TEST_ARGV"
for a in "$@"; do
  if [ "$a" = "--single-process" ]; then
    echo "DevTools listening on ws://127.0.0.1:9/devtools/browser/fake" >&2
    exec sleep 30
  fi
done
echo "{MACH_DENIED}" >&2
exit 133
"""
    chrome = _write_script(tmp_path / "chrome-headless-shell", body)
    argv = tmp_path / "argv"
    with patch.dict(os.environ, {"NOKAP_TEST_ARGV": str(argv)}):
        os.environ.pop("NOKAP_CHROME_ARGS", None)
        with Chrome(path=chrome) as c:
            assert c.is_alive()
    first, second = _launches(argv)
    assert "--single-process" not in first
    assert "--single-process" in second


@posix_only
def test_mach_denial_not_retried_with_single_process_already_set(tmp_path):
    body = f"""\
echo "$*" >> "$NOKAP_TEST_ARGV"
echo "{MACH_DENIED}" >&2
exit 133
"""
    chrome = _write_script(tmp_path / "chrome-headless-shell", body)
    argv = tmp_path / "argv"
    env = {"NOKAP_TEST_ARGV": str(argv), "NOKAP_CHROME_ARGS": "--single-process"}
    with patch.dict(os.environ, env), pytest.raises(ChromeStartError) as excinfo:
        Chrome(path=chrome)
    assert "mach-register" in str(excinfo.value)
    assert MACH_DENIED in excinfo.value.stderr
    assert len(_launches(argv)) == 1


@posix_only
def test_other_failures_are_not_retried(tmp_path):
    body = """\
echo "$*" >> "$NOKAP_TEST_ARGV"
echo "something else went wrong" >&2
exit 1
"""
    chrome = _write_script(tmp_path / "chrome", body)
    argv = tmp_path / "argv"
    with patch.dict(os.environ, {"NOKAP_TEST_ARGV": str(argv)}):
        os.environ.pop("NOKAP_CHROME_ARGS", None)
        with pytest.raises(ChromeStartError, match="code 1"):
            Chrome(path=chrome)
    assert len(_launches(argv)) == 1

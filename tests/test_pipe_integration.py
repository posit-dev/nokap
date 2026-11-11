import shlex
import socket
import struct
import sys

import pytest

import nokap

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipe transport"),
]


@pytest.fixture(autouse=True)
def pipe_transport(monkeypatch):
    monkeypatch.setenv("NOKAP_TRANSPORT", "pipe")

    def reject_tcp(self, address):
        raise AssertionError("Rendering must not bind or connect a TCP socket")

    monkeypatch.setattr(socket.socket, "bind", reject_tcp)
    monkeypatch.setattr(socket.socket, "connect", reject_tcp)
    yield
    nokap.close()


def test_html_image_without_tcp(tmp_path):
    output = tmp_path / "pipe.png"
    html = '<div id="target" style="width:320px;height:200px;background:red"></div>'
    assert nokap.from_html(html, output, selector="#target", delay=0) == output
    image = output.read_bytes()
    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", image[16:24]) == (320, 200)


def test_great_tables_image_and_pdf_without_tcp(tmp_path):
    pd = pytest.importorskip("pandas")
    GT = pytest.importorskip("great_tables").GT

    table = GT(pd.DataFrame({"Region": ["North", "South"], "Revenue": [1234.5, 9876]}))
    table = table.tab_header(title="Quarterly sales").fmt_currency(columns="Revenue")
    image = tmp_path / "table.png"
    document = tmp_path / "table.pdf"
    table.gtsave(image)
    table.gtsave(document)
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert document.read_bytes().startswith(b"%PDF-")


def test_large_image_without_tcp(tmp_path):
    from PIL import Image

    html = """
    <canvas id="target" width="512" height="512"></canvas>
    <script>
        const context = document.querySelector('canvas').getContext('2d');
        const image = context.createImageData(512, 512);
        let seed = 1;
        for (let i = 0; i < image.data.length; i += 4) {
            for (let channel = 0; channel < 3; channel++) {
                seed ^= seed << 13;
                seed ^= seed >>> 17;
                seed ^= seed << 5;
                image.data[i + channel] = seed & 255;
            }
            image.data[i + 3] = 255;
        }
        context.putImageData(image, 0, 0);
    </script>
    """
    output = tmp_path / "large.png"
    nokap.from_html(html, output, selector="#target", delay=0)
    assert output.stat().st_size > 500_000
    with Image.open(output) as image:
        image.load()
        assert image.size == (512, 512)


def test_capture_after_close_without_tcp(tmp_path):
    for name in ("first", "second"):
        output = tmp_path / f"{name}.png"
        nokap.from_html(f"<h1>{name}</h1>", output, delay=0)
        assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        nokap.close()


@pytest.mark.parametrize("explicit_args", ["none", "empty", "override"])
def test_chrome_arguments_from_environment(tmp_path, monkeypatch, explicit_args):
    environment_profile = tmp_path / "environment profile"
    explicit_profile = tmp_path / "explicit profile"
    monkeypatch.setenv(
        "NOKAP_CHROME_ARGS", shlex.quote(f"--user-data-dir={environment_profile}")
    )
    extra_args = {
        "none": None,
        "empty": [],
        "override": [f"--user-data-dir={explicit_profile}"],
    }[explicit_args]
    with nokap.Chrome(transport="pipe", extra_args=extra_args):
        assert environment_profile.exists() is (explicit_args != "override")
        assert explicit_profile.exists() is (explicit_args == "override")


def test_invalid_chrome_arguments_from_environment(monkeypatch):
    monkeypatch.setenv("NOKAP_CHROME_ARGS", '--lang="unterminated')
    with (
        pytest.raises(ValueError, match="No closing quotation"),
        nokap.Chrome(transport="pipe"),
    ):
        pass


def test_pipe_startup_failure_reports_chrome_stderr(tmp_path):
    executable = tmp_path / "chrome"
    executable.write_text(
        "#!/bin/sh\necho 'test chrome startup failure' >&2\nexit 17\n"
    )
    executable.chmod(0o755)

    with (
        pytest.raises(nokap.ChromeStartError, match="test chrome startup failure"),
        nokap.Chrome(path=str(executable), transport="pipe", timeout=1),
    ):
        pass


def test_pipe_startup_timeout(tmp_path):
    executable = tmp_path / "chrome"
    # Read requests without replying. The handshake must respect the timeout.
    executable.write_text("#!/bin/sh\nexec cat <&3 >/dev/null\n")
    executable.chmod(0o755)

    with (
        pytest.raises(nokap.ChromeStartError, match="Timed out.*0.1s"),
        nokap.Chrome(path=str(executable), transport="pipe", timeout=0.1),
    ):
        pass


def test_pipe_mach_denial_reports_hint_without_repeating_retry(tmp_path):
    arguments = tmp_path / "arguments"
    executable = tmp_path / "chrome-headless-shell"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(arguments))}\n"
        "echo 'bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.123: "
        "Permission denied (1100)' >&2\n"
        "exit 133\n"
    )
    executable.chmod(0o755)
    with pytest.raises(nokap.ChromeStartError, match="mach-register"):
        nokap.Chrome(
            path=str(executable), transport="pipe", extra_args=["--single-process"]
        )
    assert len(arguments.read_text().splitlines()) == 1


def test_capture_recovers_and_removes_dead_browser_profile(tmp_path, monkeypatch):
    import os
    import signal
    import tempfile

    chrome_path = nokap.find_chrome()
    pid_file = tmp_path / "chrome.pid"
    executable = tmp_path / "chrome"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf '%s' \"$$\" > {shlex.quote(str(pid_file))}\n"
        f'exec {shlex.quote(chrome_path)} "$@"\n'
    )
    executable.chmod(0o755)
    monkeypatch.setenv("CHROME_PATH", str(executable))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    nokap.from_html("<h1>First browser</h1>", tmp_path / "first.png", delay=0)
    first_profile = next(tmp_path.glob("nokap-chrome-*"))
    pid = int(pid_file.read_text())
    os.kill(pid, signal.SIGTERM)
    os.waitpid(pid, 0)

    output = tmp_path / "second.png"
    nokap.from_html("<h1>Replacement browser</h1>", output, delay=0)
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not first_profile.exists()
    nokap.close()
    assert not list(tmp_path.glob("nokap-chrome-*"))


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "Mach registration is macOS-only; do not force Linux Chrome "
        "through a simulated macOS recovery"
    ),
)
def test_mach_denial_retries_pipe_without_leaking_profiles(tmp_path, monkeypatch):
    import tempfile

    chrome_path = nokap.find_chrome()
    arguments = tmp_path / "arguments"
    executable = tmp_path / "chrome-headless-shell"
    executable.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {shlex.quote(str(arguments))}\n"
        'for argument in "$@"; do\n'
        '  if [ "$argument" = "--single-process" ]; then\n'
        f'    exec {shlex.quote(chrome_path)} "$@"\n'
        "  fi\n"
        "done\n"
        "echo 'bootstrap_check_in org.chromium.Chromium.MachPortRendezvousServer.123: "
        "Permission denied (1100)' >&2\n"
        "exit 133\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("CHROME_PATH", str(executable))
    monkeypatch.setenv("NOKAP_CHROME_ARGS", "--lang=en-US")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    output = tmp_path / "retry.png"
    nokap.from_html("<h1>Sandbox retry</h1>", output, delay=0)
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    first, second = arguments.read_text().splitlines()
    assert "--single-process" not in first
    assert "--single-process" in second
    assert "--lang=en-US" in first and "--lang=en-US" in second
    assert len(list(tmp_path.glob("nokap-chrome-*"))) == 1
    nokap.close()
    assert not list(tmp_path.glob("nokap-chrome-*"))

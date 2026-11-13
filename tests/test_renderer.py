import os
import shlex
import signal
import sys
from collections.abc import Iterator
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread

import pytest

import nokap

pytestmark = pytest.mark.integration

HTML = """
<div id="target" style="width:20px;height:12px"></div>
<script>
    const colors = {"nokap-red": "red", "nokap-blue": "blue"};
    document.getElementById("target").style.background =
        colors[navigator.userAgent] || "lime";
</script>
"""


@pytest.fixture(autouse=True)
def isolated_default(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    nokap.close()
    monkeypatch.delenv("NOKAP_TRANSPORT", raising=False)
    monkeypatch.delenv("NOKAP_CHROME_ARGS", raising=False)
    yield
    nokap.close()


@pytest.fixture
def chrome_path() -> str:
    try:
        return nokap.find_chrome()
    except nokap.ChromeNotFoundError:
        pytest.skip("Chrome not installed")


@pytest.fixture(
    params=[
        "websocket",
        pytest.param(
            "pipe",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipes"),
        ),
    ]
)
def transport(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def assert_color(path: Path, color: tuple[int, int, int]) -> None:
    from PIL import Image

    with Image.open(path) as image:
        assert image.format == "PNG"
        assert image.size == (20, 12)
        assert image.convert("RGB").getpixel((10, 6)) == color


def test_renderer_instances_own_reusable_browsers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chrome_path: str,
    transport: str,
) -> None:
    # Explicit arguments come after environment arguments for each instance.
    monkeypatch.setenv("NOKAP_CHROME_ARGS", "--user-agent=nokap-green")
    source = tmp_path / "table.html"
    source.write_text(HTML)
    with (
        nokap.Renderer(
            chrome_path, transport=transport, extra_args=["--user-agent=nokap-red"]
        ) as red,
        nokap.Renderer(
            chrome_path, transport=transport, extra_args=["--user-agent=nokap-blue"]
        ) as blue,
    ):
        red_browser, blue_browser = red.browser, blue.browser
        red_pid, blue_pid = red_browser.pid, blue_browser.pid
        assert red_pid is not None and blue_pid is not None and red_pid != blue_pid
        assert red_browser.transport == blue_browser.transport == transport
        with pytest.raises(AttributeError):
            red.browser = blue_browser

        red_html = tmp_path / "red-html.png"
        assert red.from_html(HTML, red_html, selector="#target", delay=0) == red_html
        assert_color(red_html, (255, 0, 0))
        blue_html = tmp_path / "blue-html.png"
        assert (
            nokap.from_html(HTML, blue_html, renderer=blue, selector="#target", delay=0)
            == blue_html
        )
        assert_color(blue_html, (0, 0, 255))

        red_url = tmp_path / "red-url.png"
        assert (
            nokap.webshot(source, red_url, renderer=red, selector="#target", delay=0)
            == red_url
        )
        assert_color(red_url, (255, 0, 0))
        blue_url = tmp_path / "blue-url.png"
        assert blue.webshot(source, blue_url, selector="#target", delay=0) == blue_url
        assert_color(blue_url, (0, 0, 255))
        assert red.browser is red_browser and red.browser.pid == red_pid
        assert blue.browser is blue_browser and blue.browser.pid == blue_pid

        default = tmp_path / "default.png"
        nokap.from_html(HTML, default, selector="#target", delay=0)
        assert_color(default, (0, 255, 0))
        nokap.close()
        assert red_browser.is_alive() and blue_browser.is_alive()

        red.close()
        red.close()
        assert not red_browser.is_alive()
        assert blue_browser.is_alive()
        surviving = tmp_path / "surviving.png"
        blue.from_html(HTML, surviving, selector="#target", delay=0)
        assert_color(surviving, (0, 0, 255))
        assert blue.browser.pid == blue_pid

    assert not red_browser.is_alive() and not blue_browser.is_alive()


def test_renderer_captures_environment_at_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chrome_path: str,
    transport: str,
) -> None:
    monkeypatch.setenv("NOKAP_TRANSPORT", transport)
    monkeypatch.setenv("NOKAP_CHROME_ARGS", "--user-agent=nokap-red")
    with nokap.Renderer(chrome_path) as renderer:
        browser = renderer.browser
        pid = browser.pid
        assert browser.is_alive() and pid is not None
        assert browser.transport == transport
        monkeypatch.setenv("NOKAP_TRANSPORT", "invalid")
        monkeypatch.setenv("NOKAP_CHROME_ARGS", "--user-agent=nokap-blue")
        output = tmp_path / "captured.png"
        renderer.from_html(HTML, output, selector="#target", delay=0)
        assert_color(output, (255, 0, 0))
        assert renderer.browser is browser and browser.pid == pid


def test_context_error_closes_renderer_permanently(
    tmp_path: Path, chrome_path: str, transport: str
) -> None:
    renderer = nokap.Renderer(chrome_path, transport=transport)
    browser = renderer.browser
    assert browser.is_alive()
    with pytest.raises(ValueError, match="caller failed"), renderer as active:
        assert active is renderer
        raise ValueError("caller failed")
    assert not browser.is_alive()
    renderer.close()
    source = tmp_path / "table.html"
    source.write_text(HTML)
    output = tmp_path / "closed.png"
    for render in (
        lambda: renderer.from_html(HTML, output),
        lambda: renderer.webshot(source, output),
        lambda: nokap.from_html(HTML, output, renderer=renderer),
        lambda: nokap.webshot(source, output, renderer=renderer),
    ):
        with pytest.raises(RuntimeError, match="closed"):
            render()
    assert not output.exists()
    assert renderer.browser is browser and not browser.is_alive()


def test_renderer_does_not_restart_closed_browser(
    tmp_path: Path, chrome_path: str, transport: str
) -> None:
    with nokap.Renderer(chrome_path, transport=transport) as renderer:
        browser = renderer.browser
        browser.close()
        with pytest.raises(nokap.NokapError, match="not running"):
            renderer.from_html(HTML, tmp_path / "unexpected.png")
        assert renderer.browser is browser and not browser.is_alive()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable fixture")
def test_connection_failure_closes_browser_and_profile(tmp_path: Path) -> None:
    from websockets.exceptions import InvalidStatus

    class RejectUpgrade(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self.send_response(503)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()

        def log_message(self, *_: object) -> None:
            pass

    recorded = tmp_path / "browser-arguments"
    executable = tmp_path / "chrome"
    # Announce readiness, then reject the WebSocket upgrade after Chrome starts.
    with HTTPServer(("127.0.0.1", 0), RejectUpgrade) as server:
        server.timeout = 5
        port = server.server_port
        executable.write_text(
            "#!/bin/sh\n"
            f'printf \'%s\\n\' "$$" "$@" > {shlex.quote(str(recorded))}\n'
            f"echo 'DevTools listening on ws://127.0.0.1:{port}/"
            "devtools/browser/test' >&2\n"
            "exec sleep 30\n"
        )
        executable.chmod(0o755)
        responder = Thread(target=server.handle_request)
        responder.start()
        try:
            with pytest.raises(InvalidStatus) as error:
                nokap.Renderer(str(executable), transport="websocket")
            assert error.value.response.status_code == 503
        finally:
            responder.join(timeout=10)
        assert not responder.is_alive()
    pid_text, *arguments = recorded.read_text().splitlines()
    pid = int(pid_text)
    try:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
        profile = next(
            arg.split("=", 1)[1]
            for arg in arguments
            if arg.startswith("--user-data-dir=")
        )
        assert not Path(profile).exists()
    finally:
        # Retire only the fixture-owned process if a cleanup regression fails.
        with suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)

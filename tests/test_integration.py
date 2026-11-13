import os
import shlex
import sys
from pathlib import Path

import pytest

import nokap

# Skip all tests if Chrome is not available
try:
    nokap.find_chrome()
    HAS_CHROME = True
except RuntimeError:
    HAS_CHROME = False

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed"),
]


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure browser is closed after each test."""
    yield
    nokap.close()


@pytest.mark.parametrize(
    ("environment", "explicit", "expected"),
    [
        (None, None, "websocket" if sys.platform == "win32" else "pipe"),
        ("websocket", None, "websocket"),
        ("pipe", "websocket", "websocket"),
        pytest.param(
            "pipe",
            None,
            "pipe",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipes"),
        ),
        pytest.param(
            "websocket",
            "pipe",
            "pipe",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipes"),
        ),
    ],
)
def test_chrome_transport(monkeypatch, environment, explicit, expected):
    if environment is None:
        monkeypatch.delenv("NOKAP_TRANSPORT", raising=False)
    else:
        monkeypatch.setenv("NOKAP_TRANSPORT", environment)
    with nokap.Chrome(transport=explicit) as chrome:
        assert chrome.transport == expected
        if expected == "websocket":
            assert chrome.ws_url.startswith(f"ws://127.0.0.1:{chrome.port}/")
        else:
            with pytest.raises(RuntimeError, match="no WebSocket URL"):
                _ = chrome.ws_url
            with pytest.raises(RuntimeError, match="no debugging port"):
                _ = chrome.port


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable fixture")
@pytest.mark.parametrize("transport", ["websocket", "pipe"])
def test_chrome_executable_name_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    browser_path = nokap.find_chrome()
    bin_dir = tmp_path / "browser bin"
    bin_dir.mkdir()
    executable = bin_dir / "browser-on-path"
    executable.write_text(f'#!/bin/sh\nexec {shlex.quote(browser_path)} "$@"\n')
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir), prepend=os.pathsep)

    with nokap.Chrome(path=executable.name, transport=transport) as browser:
        assert browser.is_alive()
        assert browser.transport == transport


class TestWebshot:
    def test_screenshot_url(self, tmp_path):
        out = tmp_path / "example.png"
        result = nokap.webshot("https://www.google.com", out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_screenshot_local_html(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body><h1>Hello</h1></body></html>")
        out = tmp_path / "test.png"
        result = nokap.webshot(html_file, out)
        assert result == out
        assert out.exists()

    def test_screenshot_with_selector(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><body><div id='target' style='width:100px;height:100px;"
            "background:red;'>Box</div></body></html>"
        )
        out = tmp_path / "test.png"
        result = nokap.webshot(html_file, out, selector="#target")
        assert result == out
        assert out.exists()

    def test_screenshot_jpeg(self, tmp_path):
        out = tmp_path / "example.jpg"
        result = nokap.webshot("https://www.google.com", out)
        assert result == out
        assert out.exists()

    def test_pdf(self, tmp_path):
        out = tmp_path / "example.pdf"
        result = nokap.webshot("https://www.google.com", out)
        assert result == out
        assert out.exists()
        # PDF files start with %PDF
        assert out.read_bytes()[:4] == b"%PDF"


class TestFromHtml:
    def test_basic_html(self, tmp_path):
        out = tmp_path / "test.png"
        result = nokap.from_html("<h1>Hello World</h1>", out)
        assert result == out
        assert out.exists()

    def test_html_with_selector(self, tmp_path):
        html = """
        <html><body>
            <div>Outside</div>
            <table><tr><td>Cell</td></tr></table>
        </body></html>
        """
        out = tmp_path / "table.png"
        result = nokap.from_html(html, out, selector="table")
        assert result == out
        assert out.exists()

    def test_html_with_zoom(self, tmp_path):
        out = tmp_path / "zoomed.png"
        result = nokap.from_html("<h1>Big</h1>", out, zoom=2)
        assert result == out
        assert out.exists()

    def test_html_to_pdf(self, tmp_path):
        out = tmp_path / "test.pdf"
        result = nokap.from_html("<h1>PDF Test</h1>", out)
        assert result == out
        assert out.read_bytes()[:4] == b"%PDF"

    def test_html_to_element_pdf(self, tmp_path):
        """Element-bounded PDF: sized to fit the selector element."""
        html = """
        <html><body>
            <div>Header content</div>
            <table id="target" style="border-collapse:collapse;">
                <tr><td style="border:1px solid #000;padding:8px;">Cell A</td>
                    <td style="border:1px solid #000;padding:8px;">Cell B</td></tr>
                <tr><td style="border:1px solid #000;padding:8px;">Cell C</td>
                    <td style="border:1px solid #000;padding:8px;">Cell D</td></tr>
            </table>
            <div>Footer content</div>
        </body></html>
        """
        out = tmp_path / "element.pdf"
        result = nokap.from_html(html, out, selector="#target", expand=10)
        assert result == out
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"
        # Element PDF should be smaller than a full-page PDF
        full_out = tmp_path / "full.pdf"
        nokap.from_html(html, full_out)
        assert out.stat().st_size < full_out.stat().st_size


class TestGreatTables:
    """Test integration with great_tables."""

    gt = pytest.importorskip("great_tables")

    def test_gt_table_snapshot(self, tmp_path):
        """Capture a GT table as a PNG, matching the nokap-test.qmd workflow."""
        pytest.importorskip("pandas")
        from great_tables import GT, exibble

        html = GT(exibble).as_raw_html(make_page=True, all_important=True)
        out = tmp_path / "gt_table.png"
        result = nokap.from_html(html, out, selector="table", zoom=2, expand=5)
        assert result == out
        assert out.exists()
        # A rendered GT table should produce a substantial image
        assert out.stat().st_size > 5000

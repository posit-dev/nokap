import pytest

import gun

# Skip all tests if Chrome is not available
try:
    gun.find_chrome()
    HAS_CHROME = True
except RuntimeError:
    HAS_CHROME = False

pytestmark = pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure browser is closed after each test."""
    yield
    gun.close()


class TestWebshot:
    def test_screenshot_url(self, tmp_path):
        out = tmp_path / "example.png"
        result = gun.webshot("https://example.com", out)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_screenshot_local_html(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body><h1>Hello</h1></body></html>")
        out = tmp_path / "test.png"
        result = gun.webshot(html_file, out)
        assert result == out
        assert out.exists()

    def test_screenshot_with_selector(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><body><div id='target' style='width:100px;height:100px;"
            "background:red;'>Box</div></body></html>"
        )
        out = tmp_path / "test.png"
        result = gun.webshot(html_file, out, selector="#target")
        assert result == out
        assert out.exists()

    def test_screenshot_jpeg(self, tmp_path):
        out = tmp_path / "example.jpg"
        result = gun.webshot("https://example.com", out)
        assert result == out
        assert out.exists()

    def test_pdf(self, tmp_path):
        out = tmp_path / "example.pdf"
        result = gun.webshot("https://example.com", out)
        assert result == out
        assert out.exists()
        # PDF files start with %PDF
        assert out.read_bytes()[:4] == b"%PDF"


class TestFromHtml:
    def test_basic_html(self, tmp_path):
        out = tmp_path / "test.png"
        result = gun.from_html("<h1>Hello World</h1>", out)
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
        result = gun.from_html(html, out, selector="table")
        assert result == out
        assert out.exists()

    def test_html_with_zoom(self, tmp_path):
        out = tmp_path / "zoomed.png"
        result = gun.from_html("<h1>Big</h1>", out, zoom=2)
        assert result == out
        assert out.exists()

    def test_html_to_pdf(self, tmp_path):
        out = tmp_path / "test.pdf"
        result = gun.from_html("<h1>PDF Test</h1>", out)
        assert result == out
        assert out.read_bytes()[:4] == b"%PDF"

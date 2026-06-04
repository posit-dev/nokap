import pytest

import gun
from gun._errors import (
    ChromeNotFoundError,
    GunError,
    NavigationError,
    SelectorError,
)

# Skip all tests if Chrome is not available
try:
    gun.find_chrome()
    HAS_CHROME = True
except (RuntimeError, ChromeNotFoundError):
    HAS_CHROME = False

pytestmark = pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure browser is closed after each test."""
    yield
    gun.close()


class TestSelectorErrors:
    def test_invalid_selector_raises(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body><p>Hello</p></body></html>")
        out = tmp_path / "test.png"
        with pytest.raises(SelectorError, match="No element matches selector"):
            gun.webshot(html_file, out, selector="#nonexistent")

    def test_selector_error_is_gun_error(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body><p>Hello</p></body></html>")
        out = tmp_path / "test.png"
        with pytest.raises(GunError):
            gun.webshot(html_file, out, selector=".does-not-exist")

    def test_empty_element_ignored_in_union(self, tmp_path):
        """Elements with zero width/height are skipped in union bounds."""
        html_file = tmp_path / "test.html"
        html_file.write_text(
            "<html><body>"
            "<div class='target' style='width:0;height:0;'></div>"
            "<div class='target' style='width:50px;height:50px;"
            "background:blue;'>Box</div>"
            "</body></html>"
        )
        out = tmp_path / "test.png"
        gun.webshot(html_file, out, selector=[".target"])
        assert out.exists()


class TestNavigationErrors:
    def test_navigation_nonexistent_file_raises(self, tmp_path):
        """Navigation to a nonexistent file raises NavigationError."""
        out = tmp_path / "test.png"
        with pytest.raises(NavigationError, match="ERR_FILE_NOT_FOUND"):
            gun.webshot("file:///nonexistent/path/to/file.html", out)


class TestParameterValidation:
    def test_selector_and_cliprect_mutually_exclusive(self, tmp_path):
        html_file = tmp_path / "test.html"
        html_file.write_text("<html><body><p>Hello</p></body></html>")
        out = tmp_path / "test.png"
        with pytest.raises(ValueError, match="Cannot specify both"):
            gun.webshot(html_file, out, selector="p", cliprect=(0, 0, 100, 100))


class TestEdgeCases:
    def test_webp_format(self, tmp_path):
        out = tmp_path / "test.webp"
        gun.from_html("<h1>WebP Test</h1>", out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_expand_single_int(self, tmp_path):
        html = (
            "<html><body>"
            "<div id='box' style='width:50px;height:50px;"
            "background:red;'>X</div></body></html>"
        )
        out = tmp_path / "test.png"
        gun.from_html(html, out, selector="#box", expand=10)
        assert out.exists()

    def test_expand_tuple(self, tmp_path):
        html = (
            "<html><body>"
            "<div id='box' style='width:50px;height:50px;"
            "background:red;'>X</div></body></html>"
        )
        out = tmp_path / "test.png"
        gun.from_html(html, out, selector="#box", expand=(5, 10, 15, 20))
        assert out.exists()

    def test_custom_viewport(self, tmp_path):
        out = tmp_path / "test.png"
        gun.from_html("<h1>Wide</h1>", out, vwidth=1920, vheight=1080)
        assert out.exists()

    def test_delay_zero(self, tmp_path):
        out = tmp_path / "test.png"
        gun.from_html("<h1>Fast</h1>", out, delay=0)
        assert out.exists()

    def test_output_directory_created(self, tmp_path):
        """Output parent directories are created if they don't exist."""
        out = tmp_path / "subdir" / "nested" / "test.png"
        gun.from_html("<h1>Nested</h1>", out)
        assert out.exists()

    def test_html_with_unicode(self, tmp_path):
        out = tmp_path / "test.png"
        gun.from_html("<h1>こんにちは 🌍</h1>", out)
        assert out.exists()

    def test_large_html_table(self, tmp_path):
        """Test with a larger HTML table to ensure no truncation issues."""
        rows = "".join(
            f"<tr><td>Row {i}</td><td>Data {i}</td></tr>" for i in range(100)
        )
        html = f"<html><body><table>{rows}</table></body></html>"
        out = tmp_path / "table.png"
        gun.from_html(html, out, selector="table")
        assert out.exists()
        assert out.stat().st_size > 1000  # Should be a substantial image


class TestPDFOptions:
    def test_pdf_landscape(self, tmp_path):
        out = tmp_path / "landscape.pdf"
        gun.from_html("<h1>Landscape</h1>", out, landscape=True)
        assert out.exists()
        assert out.read_bytes()[:4] == b"%PDF"

    def test_pdf_a4(self, tmp_path):
        out = tmp_path / "a4.pdf"
        gun.from_html("<h1>A4</h1>", out, page_size="a4")
        assert out.exists()

    def test_pdf_print_background(self, tmp_path):
        html = "<html><body style='background:lightblue;'><h1>BG</h1></body></html>"
        out = tmp_path / "bg.pdf"
        gun.from_html(html, out, print_background=True)
        assert out.exists()


class TestBrowserRecovery:
    def test_works_after_close(self, tmp_path):
        """Calling webshot after gun.close() should auto-restart Chrome."""
        out1 = tmp_path / "first.png"
        gun.from_html("<h1>First</h1>", out1)
        assert out1.exists()

        gun.close()

        out2 = tmp_path / "second.png"
        gun.from_html("<h1>Second</h1>", out2)
        assert out2.exists()

    def test_multiple_sequential_screenshots(self, tmp_path):
        """Multiple screenshots in sequence reuse the same browser."""
        for i in range(5):
            out = tmp_path / f"shot_{i}.png"
            gun.from_html(f"<h1>Shot {i}</h1>", out)
            assert out.exists()

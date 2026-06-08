from __future__ import annotations

import pytest
from click.testing import CliRunner

import nokap
from nokap._cli import cli
from nokap._errors import ChromeNotFoundError

# Skip all tests if Chrome is not available
try:
    nokap.find_chrome()
    HAS_CHROME = True
except (RuntimeError, ChromeNotFoundError):
    HAS_CHROME = False


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture(autouse=True)
def cleanup():
    """Ensure browser is closed after each test."""
    yield
    nokap.close()


# ---------------------------------------------------------------------------
# Top-level CLI group
# ---------------------------------------------------------------------------


class TestCLIGroup:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Screenshots and PDFs from web pages" in result.output
        assert "webshot" in result.output
        assert "from-html" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "nokap" in result.output
        assert "version" in result.output

    def test_no_command(self, runner):
        result = runner.invoke(cli, [])
        assert result.exit_code == 0
        # Shows help when no command given
        assert "Commands:" in result.output

    def test_invalid_command(self, runner):
        result = runner.invoke(cli, ["nonexistent"])
        assert result.exit_code != 0
        assert "No such command" in result.output


# ---------------------------------------------------------------------------
# webshot command - argument/option parsing
# ---------------------------------------------------------------------------


class TestWebshotHelp:
    def test_help(self, runner):
        result = runner.invoke(cli, ["webshot", "--help"])
        assert result.exit_code == 0
        assert "Take a screenshot or PDF" in result.output

    def test_shows_all_options(self, runner):
        result = runner.invoke(cli, ["webshot", "--help"])
        assert "--vwidth" in result.output
        assert "--vheight" in result.output
        assert "--selector" in result.output
        assert "--expand" in result.output
        assert "--delay" in result.output
        assert "--zoom" in result.output
        assert "--useragent" in result.output
        assert "--page-size" in result.output
        assert "--landscape" in result.output
        assert "--print-background" in result.output

    def test_short_options_shown(self, runner):
        result = runner.invoke(cli, ["webshot", "--help"])
        assert "-s" in result.output
        assert "-e" in result.output
        assert "-d" in result.output
        assert "-z" in result.output

    def test_missing_url_argument(self, runner):
        result = runner.invoke(cli, ["webshot"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output


# ---------------------------------------------------------------------------
# from-html command - argument/option parsing
# ---------------------------------------------------------------------------


class TestFromHtmlHelp:
    def test_help(self, runner):
        result = runner.invoke(cli, ["from-html", "--help"])
        assert result.exit_code == 0
        assert "Render an HTML file" in result.output

    def test_shows_all_options(self, runner):
        result = runner.invoke(cli, ["from-html", "--help"])
        assert "--selector" in result.output
        assert "--vwidth" in result.output
        assert "--vheight" in result.output
        assert "--expand" in result.output
        assert "--delay" in result.output
        assert "--zoom" in result.output

    def test_missing_html_file_argument(self, runner):
        result = runner.invoke(cli, ["from-html"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output

    def test_nonexistent_html_file(self, runner):
        result = runner.invoke(cli, ["from-html", "/nonexistent/file.html"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# webshot command - integration (requires Chrome)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")
class TestWebshotIntegration:
    def test_screenshot_url(self, runner, tmp_path):
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", "https://www.google.com", out])
        assert result.exit_code == 0
        assert out in result.output
        assert (tmp_path / "out.png").exists()
        assert (tmp_path / "out.png").stat().st_size > 0

    def test_screenshot_local_file(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><h1>Hello</h1></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_screenshot_jpeg(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>JPEG test</p></body></html>")
        out = str(tmp_path / "out.jpg")
        result = runner.invoke(cli, ["webshot", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.jpg").exists()
        assert (tmp_path / "out.jpg").stat().st_size > 0

    def test_screenshot_webp(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>WebP test</p></body></html>")
        out = str(tmp_path / "out.webp")
        result = runner.invoke(cli, ["webshot", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.webp").exists()

    def test_pdf_output(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>PDF test</p></body></html>")
        out = str(tmp_path / "out.pdf")
        result = runner.invoke(cli, ["webshot", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.pdf").exists()
        # Verify it's actually a PDF
        assert (tmp_path / "out.pdf").read_bytes()[:4] == b"%PDF"

    def test_selector_option(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text(
            "<html><body>"
            "<div id='target' style='width:100px;height:100px;background:red;'>"
            "Target</div></body></html>"
        )
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out, "-s", "#target"])
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_selector_short_option(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p class='x'>Hi</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out, "-s", ".x"])
        assert result.exit_code == 0

    def test_zoom_option(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Zoom</p></body></html>")
        out_1x = str(tmp_path / "out_1x.png")
        out_2x = str(tmp_path / "out_2x.png")
        runner.invoke(cli, ["webshot", str(html_file), out_1x, "-z", "1"])
        runner.invoke(cli, ["webshot", str(html_file), out_2x, "-z", "2"])
        # 2x zoom should produce a larger file
        size_1x = (tmp_path / "out_1x.png").stat().st_size
        size_2x = (tmp_path / "out_2x.png").stat().st_size
        assert size_2x > size_1x

    def test_expand_option(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text(
            "<html><body>"
            "<div id='box' style='width:50px;height:50px;background:blue;'>"
            "</div></body></html>"
        )
        out = str(tmp_path / "out.png")
        result = runner.invoke(
            cli, ["webshot", str(html_file), out, "-s", "#box", "-e", "10"]
        )
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_viewport_options(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Viewport</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(
            cli,
            ["webshot", str(html_file), out, "--vwidth", "1920", "--vheight", "1080"],
        )
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_delay_option(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Delay</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out, "-d", "0"])
        assert result.exit_code == 0

    def test_pdf_landscape(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Landscape</p></body></html>")
        out = str(tmp_path / "out.pdf")
        result = runner.invoke(cli, ["webshot", str(html_file), out, "--landscape"])
        assert result.exit_code == 0
        assert (tmp_path / "out.pdf").exists()

    def test_pdf_page_size(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>A4</p></body></html>")
        out = str(tmp_path / "out.pdf")
        result = runner.invoke(
            cli, ["webshot", str(html_file), out, "--page-size", "a4"]
        )
        assert result.exit_code == 0

    def test_pdf_print_background(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text(
            "<html><body style='background:yellow;'><p>BG</p></body></html>"
        )
        out = str(tmp_path / "out.pdf")
        result = runner.invoke(
            cli, ["webshot", str(html_file), out, "--print-background"]
        )
        assert result.exit_code == 0

    def test_default_output_filename(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Default</p></body></html>")
        # Without specifying output, it goes to "webshot.png" in cwd
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["webshot", str(html_file)])
            assert result.exit_code == 0
            assert "webshot.png" in result.output

    def test_invalid_selector_reports_error(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Hello</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out, "-s", "#nope"])
        assert result.exit_code == 1
        assert "Error:" in result.output


# ---------------------------------------------------------------------------
# from-html command - integration (requires Chrome)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")
class TestFromHtmlIntegration:
    def test_basic_html_file(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text("<html><body><h1>Hello CLI</h1></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["from-html", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()
        assert (tmp_path / "out.png").stat().st_size > 0

    def test_with_selector(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text(
            "<html><body>"
            "<div id='capture' style='width:200px;height:100px;background:green;'>"
            "Capture me</div>"
            "<p>Not this</p></body></html>"
        )
        out = str(tmp_path / "out.png")
        result = runner.invoke(
            cli, ["from-html", str(html_file), out, "-s", "#capture"]
        )
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_with_zoom(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text("<html><body><p>Zoom test</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["from-html", str(html_file), out, "-z", "2"])
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_to_pdf(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text("<html><body><p>PDF from HTML</p></body></html>")
        out = str(tmp_path / "out.pdf")
        result = runner.invoke(cli, ["from-html", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.pdf").read_bytes()[:4] == b"%PDF"

    def test_with_expand(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text(
            "<html><body>"
            "<span id='el' style='display:inline-block;width:80px;height:40px;"
            "background:orange;'>Box</span></body></html>"
        )
        out = str(tmp_path / "out.png")
        result = runner.invoke(
            cli, ["from-html", str(html_file), out, "-s", "#el", "-e", "20"]
        )
        assert result.exit_code == 0

    def test_viewport_options(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text("<html><body><p>Wide</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(
            cli,
            ["from-html", str(html_file), out, "--vwidth", "1440", "--vheight", "900"],
        )
        assert result.exit_code == 0

    def test_delay_option(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text("<html><body><p>Quick</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["from-html", str(html_file), out, "-d", "0"])
        assert result.exit_code == 0

    def test_default_output_filename(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text("<html><body><p>Default out</p></body></html>")
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["from-html", str(html_file)])
            assert result.exit_code == 0
            assert "webshot.png" in result.output

    def test_unicode_html(self, runner, tmp_path):
        html_file = tmp_path / "input.html"
        html_file.write_text(
            "<html><body><p>日本語テスト 🎉</p></body></html>", encoding="utf-8"
        )
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["from-html", str(html_file), out])
        assert result.exit_code == 0
        assert (tmp_path / "out.png").exists()

    def test_large_html_table(self, runner, tmp_path):
        rows = "".join(
            f"<tr><td>Row {i}</td><td>Data {i}</td></tr>" for i in range(100)
        )
        html_file = tmp_path / "input.html"
        html_file.write_text(f"<html><body><table>{rows}</table></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["from-html", str(html_file), out, "-s", "table"])
        assert result.exit_code == 0
        assert (tmp_path / "out.png").stat().st_size > 1000


# ---------------------------------------------------------------------------
# Error handling in CLI
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")
class TestCLIErrorHandling:
    def test_webshot_invalid_selector_exits_1(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Hello</p></body></html>")
        out = str(tmp_path / "out.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out, "-s", "#missing"])
        assert result.exit_code == 1
        assert "Error:" in result.output

    def test_from_html_nonexistent_file(self, runner):
        result = runner.invoke(cli, ["from-html", "/does/not/exist.html", "out.png"])
        assert result.exit_code != 0

    def test_webshot_outputs_path_on_success(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Path check</p></body></html>")
        out = str(tmp_path / "result.png")
        result = runner.invoke(cli, ["webshot", str(html_file), out])
        assert result.exit_code == 0
        # Output should contain the resolved path
        assert "result.png" in result.output


# ---------------------------------------------------------------------------
# Option validation / edge cases
# ---------------------------------------------------------------------------


class TestCLIOptionValidation:
    def test_webshot_invalid_vwidth_type(self, runner):
        result = runner.invoke(
            cli, ["webshot", "https://example.com", "o.png", "--vwidth", "abc"]
        )
        assert result.exit_code != 0

    def test_webshot_invalid_vheight_type(self, runner):
        result = runner.invoke(
            cli, ["webshot", "https://example.com", "o.png", "--vheight", "abc"]
        )
        assert result.exit_code != 0

    def test_webshot_invalid_expand_type(self, runner):
        result = runner.invoke(
            cli, ["webshot", "https://example.com", "o.png", "-e", "abc"]
        )
        assert result.exit_code != 0

    def test_webshot_invalid_delay_type(self, runner):
        result = runner.invoke(
            cli, ["webshot", "https://example.com", "o.png", "-d", "abc"]
        )
        assert result.exit_code != 0

    def test_webshot_invalid_zoom_type(self, runner):
        result = runner.invoke(
            cli, ["webshot", "https://example.com", "o.png", "-z", "abc"]
        )
        assert result.exit_code != 0

    def test_from_html_invalid_expand_type(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>x</p></body></html>")
        result = runner.invoke(cli, ["from-html", str(html_file), "o.png", "-e", "abc"])
        assert result.exit_code != 0

    def test_from_html_invalid_zoom_type(self, runner, tmp_path):
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>x</p></body></html>")
        result = runner.invoke(cli, ["from-html", str(html_file), "o.png", "-z", "abc"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# doctor command
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")
class TestDoctor:
    def test_doctor_passes(self, runner):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "All checks passed" in result.output

    def test_doctor_reports_chrome_path(self, runner):
        result = runner.invoke(cli, ["doctor"])
        assert "Path:" in result.output

    def test_doctor_reports_timing(self, runner):
        result = runner.invoke(cli, ["doctor"])
        assert "ms" in result.output


# ---------------------------------------------------------------------------
# batch command
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_CHROME, reason="Chrome not installed")
class TestBatch:
    def test_batch_html_jobs(self, runner, tmp_path):
        import json

        manifest = tmp_path / "jobs.json"
        manifest.write_text(
            json.dumps(
                [
                    {"html": "<h1>One</h1>", "file": "one.png"},
                    {"html": "<h1>Two</h1>", "file": "two.png", "zoom": 2},
                ]
            )
        )
        out_dir = tmp_path / "output"
        result = runner.invoke(cli, ["batch", str(manifest), "-o", str(out_dir)])
        assert result.exit_code == 0
        assert (out_dir / "one.png").exists()
        assert (out_dir / "two.png").exists()
        assert "2/2 succeeded" in result.output

    def test_batch_with_selector(self, runner, tmp_path):
        import json

        manifest = tmp_path / "jobs.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "html": "<div><table><tr><td>X</td></tr></table></div>",
                        "file": "table.pdf",
                        "selector": "table",
                        "expand": 5,
                    }
                ]
            )
        )
        out_dir = tmp_path / "output"
        result = runner.invoke(cli, ["batch", str(manifest), "-o", str(out_dir)])
        assert result.exit_code == 0
        pdf_file = out_dir / "table.pdf"
        assert pdf_file.exists()
        assert pdf_file.read_bytes()[:4] == b"%PDF"

    def test_batch_missing_file_key(self, runner, tmp_path):
        import json

        manifest = tmp_path / "jobs.json"
        manifest.write_text(json.dumps([{"html": "<h1>No file</h1>"}]))
        out_dir = tmp_path / "output"
        result = runner.invoke(cli, ["batch", str(manifest), "-o", str(out_dir)])
        assert result.exit_code == 1
        assert "0/1 succeeded" in result.output

    def test_batch_invalid_json(self, runner, tmp_path):
        manifest = tmp_path / "jobs.json"
        manifest.write_text("not json")
        result = runner.invoke(cli, ["batch", str(manifest)])
        assert result.exit_code == 1
        assert "Error reading manifest" in result.output

    def test_batch_not_array(self, runner, tmp_path):
        manifest = tmp_path / "jobs.json"
        manifest.write_text('{"not": "array"}')
        result = runner.invoke(cli, ["batch", str(manifest)])
        assert result.exit_code == 1
        assert "JSON array" in result.output

    def test_batch_default_selector(self, runner, tmp_path):
        """Command-line --selector applies to all jobs as default."""
        import json

        manifest = tmp_path / "jobs.json"
        manifest.write_text(
            json.dumps(
                [
                    {
                        "html": "<div><p id='x'>Hi</p></div>",
                        "file": "p.png",
                    }
                ]
            )
        )
        out_dir = tmp_path / "output"
        result = runner.invoke(
            cli, ["batch", str(manifest), "-o", str(out_dir), "-s", "p"]
        )
        assert result.exit_code == 0
        assert (out_dir / "p.png").exists()

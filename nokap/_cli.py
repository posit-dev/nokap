from __future__ import annotations

import sys
from pathlib import Path
from typing import cast

import click

import nokap
from nokap._browser import find_chrome
from nokap._errors import ChromeNotFoundError
from nokap._types import PaperSize
from nokap._utils import current_platform


@click.group(invoke_without_command=True)
@click.version_option(package_name="nokap", prog_name="nokap")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Screenshots and PDFs from web pages. Powered by headless Chrome."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.argument("url")
@click.argument("file", default="webshot.png")
@click.option("--vwidth", default=992, type=int, help="Viewport width in pixels.")
@click.option("--vheight", default=744, type=int, help="Viewport height in pixels.")
@click.option("--selector", "-s", default=None, help="CSS selector to capture.")
@click.option(
    "--expand", "-e", default=0, type=int, help="Pixels to expand around selector."
)
@click.option(
    "--delay", "-d", default=0.2, type=float, help="Seconds to wait after page load."
)
@click.option("--zoom", "-z", default=1.0, type=float, help="Zoom/scale factor.")
@click.option("--useragent", default=None, help="Custom User-Agent string.")
@click.option(
    "--page-size", default="letter", help="Paper size for PDF (e.g., letter, a4)."
)
@click.option("--landscape", is_flag=True, help="Use landscape orientation for PDF.")
@click.option("--print-background", is_flag=True, help="Print CSS backgrounds in PDF.")
def webshot(
    url: str,
    file: str,
    vwidth: int,
    vheight: int,
    selector: str | None,
    expand: int,
    delay: float,
    zoom: float,
    useragent: str | None,
    page_size: str,
    landscape: bool,
    print_background: bool,
) -> None:
    """Take a screenshot or PDF of a URL or local file.

    URL can be an http/https URL or a local file path.
    FILE is the output path (default: webshot.png). Format is determined by
    extension: .png, .jpg, .webp for images; .pdf for PDF.
    """
    try:
        result = nokap.webshot(
            url,
            file,
            vwidth=vwidth,
            vheight=vheight,
            selector=selector,
            expand=expand,
            delay=delay,
            zoom=zoom,
            useragent=useragent,
            page_size=cast(PaperSize, page_size),
            landscape=landscape,
            print_background=print_background,
        )
        click.echo(result)
    except nokap.NokapError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        nokap.close()


@cli.command("from-html")
@click.argument("html_file", type=click.Path(exists=True))
@click.argument("file", default="webshot.png")
@click.option("--selector", "-s", default="html", help="CSS selector to capture.")
@click.option("--vwidth", default=992, type=int, help="Viewport width in pixels.")
@click.option("--vheight", default=744, type=int, help="Viewport height in pixels.")
@click.option(
    "--expand", "-e", default=0, type=int, help="Pixels to expand around selector."
)
@click.option(
    "--delay", "-d", default=0.2, type=float, help="Seconds to wait after page load."
)
@click.option("--zoom", "-z", default=1.0, type=float, help="Zoom/scale factor.")
def from_html(
    html_file: str,
    file: str,
    selector: str,
    vwidth: int,
    vheight: int,
    expand: int,
    delay: float,
    zoom: float,
) -> None:
    """Render an HTML file to an image or PDF.

    HTML_FILE is a path to an HTML file to render.
    FILE is the output path (default: webshot.png).
    """
    html_content = Path(html_file).read_text(encoding="utf-8")
    try:
        result = nokap.from_html(
            html_content,
            file,
            selector=selector,
            vwidth=vwidth,
            vheight=vheight,
            expand=expand,
            delay=delay,
            zoom=zoom,
        )
        click.echo(result)
    except nokap.NokapError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        nokap.close()


@cli.command()
def info() -> None:
    """Display system info and whether a compatible browser is found."""
    import platform
    import subprocess
    from importlib.metadata import version

    click.echo(f"nokap version: {version('nokap')}")
    click.echo(f"Python: {sys.version.split()[0]}")
    click.echo(f"Platform: {current_platform()} ({platform.platform()})")
    click.echo("")

    try:
        chrome_path = find_chrome()
        click.echo(f"Browser found: {chrome_path}")

        # Try to get the version
        try:
            result = subprocess.run(
                [chrome_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip()
            if version:
                click.echo(f"Browser version: {version}")
        except (subprocess.TimeoutExpired, OSError):
            pass

    except ChromeNotFoundError:
        click.echo("Browser found: No")
        click.echo(
            "Install Chrome, Chromium, or set the CHROME_PATH environment variable."
        )
        sys.exit(1)

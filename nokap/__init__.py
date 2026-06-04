from __future__ import annotations

import atexit
import tempfile
import time
from pathlib import Path
from typing import Any

from ._browser import Chrome, find_chrome
from ._cdp import SyncCDP
from ._errors import (
    CDPError,
    ChromeNotFoundError,
    ChromeStartError,
    ConnectionError_,
    NavigationError,
    NokapError,
    PageLoadTimeout,
    SelectorError,
)
from ._pdf import capture_pdf
from ._screenshot import capture_screenshot
from ._session import Session
from ._types import PaperSize
from ._utils import file_url, is_url

__all__ = [
    "webshot",
    "from_html",
    "close",
    "find_chrome",
    "Chrome",
    "Session",
    "NokapError",
    "CDPError",
    "ChromeNotFoundError",
    "ChromeStartError",
    "NavigationError",
    "PageLoadTimeout",
    "SelectorError",
]

# ---------------------------------------------------------------------------
# Module-level browser singleton
# ---------------------------------------------------------------------------

_browser: Chrome | None = None
_cdp: SyncCDP | None = None

_MAX_RETRIES = 2


def _get_browser() -> Chrome:
    """Get or create the module-level Chrome browser instance."""
    global _browser
    if _browser is None or not _browser.is_alive():
        # If browser died, also reset the CDP connection
        global _cdp
        if _cdp is not None:
            try:
                _cdp.close()
            except Exception:
                pass
            _cdp = None
        _browser = Chrome()
    return _browser


def _get_cdp() -> SyncCDP:
    """Get or create the module-level CDP connection, with auto-recovery."""
    global _cdp, _browser
    browser = _get_browser()
    if _cdp is None:
        _cdp = SyncCDP(browser.ws_url)
        _cdp.connect()
    return _cdp


def close() -> None:
    """
    Explicitly close the module-level browser and CDP connection.

    Call this when you're done taking screenshots to clean up Chrome processes.
    If not called, cleanup happens automatically at interpreter exit.
    """
    global _browser, _cdp
    if _cdp is not None:
        try:
            _cdp.close()
        except Exception:
            pass
        _cdp = None
    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None


atexit.register(close)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def webshot(
    url: str | Path,
    file: str | Path = "webshot.png",
    *,
    vwidth: int = 992,
    vheight: int = 744,
    selector: str | list[str] | None = None,
    cliprect: tuple[float, float, float, float] | None = None,
    expand: int | tuple[int, int, int, int] = 0,
    delay: float = 0.2,
    zoom: float = 1,
    useragent: str | None = None,
    # PDF-specific options (only used when file ends with .pdf)
    page_size: PaperSize = "letter",
    margins: float | tuple[float, float, float, float] = 0.5,
    landscape: bool = False,
    print_background: bool = False,
) -> Path:
    """
    Take a screenshot or PDF of a web page.

    Parameters
    ----------
    url
        URL to capture. Can be an http/https URL, a file:// URL, or a local
        file path (automatically converted to a file URL).
    file
        Output file path. The format is determined by extension:
        .png, .jpg/.jpeg, .webp for images; .pdf for PDF.
    vwidth
        Viewport width in pixels.
    vheight
        Viewport height in pixels.
    selector
        CSS selector(s) to capture. The screenshot is cropped to the
        element's bounding box. Mutually exclusive with `cliprect`.
    cliprect
        Explicit clip rectangle as (x, y, width, height) in CSS pixels.
        Mutually exclusive with `selector`.
    expand
        Pixels to expand around the selector bounding box.
        Single int for all sides, or (top, right, bottom, left) tuple.
    delay
        Seconds to wait after page load before capturing.
    zoom
        Zoom/scale factor. Values > 1 produce higher resolution images.
    useragent
        Custom User-Agent string.
    page_size
        Paper size for PDF output (e.g., "letter", "a4").
    margins
        Margins in inches for PDF output. Single float or 4-tuple.
    landscape
        Whether to use landscape orientation for PDF output.
    print_background
        Whether to print CSS backgrounds in PDF output.

    Returns
    -------
    Path
        The absolute path to the output file.
    """
    # Resolve URL
    url_str: str
    if isinstance(url, Path) or not is_url(str(url)):
        url_str = file_url(url)
    else:
        url_str = str(url)

    # Resolve output file
    out_file = Path(file).resolve()
    is_pdf = out_file.suffix.lower() == ".pdf"

    # Get CDP connection and create a session (with retry on connection failure)
    for attempt in range(_MAX_RETRIES + 1):
        try:
            cdp = _get_cdp()
            session = Session(cdp, width=vwidth, height=vheight)
            break
        except (ConnectionError_, ChromeStartError, OSError):
            if attempt == _MAX_RETRIES:
                raise
            # Connection stale or Chrome slow to start — reset and retry
            close()
    else:
        cdp = _get_cdp()
        session = Session(cdp, width=vwidth, height=vheight)

    try:
        # Set user agent if provided
        if useragent:
            session.set_user_agent(useragent)

        # Navigate
        session.navigate(url_str)

        # Wait for delay
        if delay > 0:
            time.sleep(delay)

        # Capture
        if is_pdf:
            return capture_pdf(
                session,
                out_file,
                page_size=page_size,
                margins=margins,
                landscape=landscape,
                scale=zoom,
                print_background=print_background,
            )
        else:
            return capture_screenshot(
                session,
                out_file,
                selector=selector,
                cliprect=cliprect,
                expand=expand,
                zoom=zoom,
            )
    finally:
        session.close()


def from_html(
    html: str,
    file: str | Path = "webshot.png",
    *,
    selector: str = "html",
    encoding: str = "utf-8",
    **kwargs: Any,
) -> Path:
    """
    Take a screenshot or PDF from an HTML string.

    This is the primary integration point for packages like great-tables
    that generate HTML and need to convert it to an image.

    Parameters
    ----------
    html
        The HTML content to render.
    file
        Output file path. Format determined by extension.
    selector
        CSS selector to capture (default: "html" for full page).
    encoding
        Character encoding for the HTML file.
    **kwargs
        Additional arguments passed to `webshot()` (e.g., zoom, expand,
        delay, vwidth, vheight).

    Returns
    -------
    Path
        The absolute path to the output file.
    """
    # Write HTML to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".html",
        encoding=encoding,
        delete=False,
    ) as f:
        # Ensure charset meta tag is present for proper rendering
        if "<meta" not in html.lower() or "charset" not in html.lower():
            html = f'<meta charset="{encoding}">\n' + html
        f.write(html)
        tmp_path = Path(f.name)

    try:
        return webshot(tmp_path, file, selector=selector, **kwargs)
    finally:
        # Clean up temp file
        try:
            tmp_path.unlink()
        except OSError:
            pass

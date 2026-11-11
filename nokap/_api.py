from __future__ import annotations

import atexit
import tempfile
import time
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ._browser import Chrome
from ._cdp import SyncCDP
from ._errors import ChromeStartError, ConnectionError_
from ._pdf import capture_element_pdf, capture_pdf
from ._pipe import SyncPipeCDP
from ._screenshot import capture_screenshot
from ._session import Session
from ._types import PaperSize
from ._utils import file_url, is_url

__all__ = [
    "Renderer",
    "webshot",
    "from_html",
    "close",
]


class Renderer:
    """
    Own a configured Chrome browser and connection for repeated captures.

    Construction launches Chrome immediately. Options match `Chrome`: `path`
    selects the executable, `headless` controls headless mode, `extra_args` are
    appended after NOKAP_CHROME_ARGS, `timeout` bounds browser startup, and
    `transport` overrides NOKAP_TRANSPORT. Environment settings are read at
    construction. Pipes are the default on macOS/Linux; Windows uses WebSockets.

    Use as a context manager or call `close()` to release the connection, browser,
    and temporary profile. Closing is terminal. If the browser exits unexpectedly,
    create a new renderer. Use separate instances for independent tasks.

    Pass this object to `webshot()` or `from_html()` with `renderer=`, or call its
    methods. Captures borrow the renderer and close only their own browser tab.
    """

    def __init__(
        self,
        path: str | None = None,
        *,
        headless: bool = True,
        extra_args: list[str] | None = None,
        timeout: float = 20.0,
        transport: str | None = None,
    ) -> None:
        self._resources = ExitStack()
        self._closed = False
        try:
            self._browser = Chrome(
                path,
                headless=headless,
                extra_args=extra_args,
                timeout=timeout,
                transport=transport,
            )
            self._resources.callback(self._browser.close)
            self._cdp: SyncCDP | SyncPipeCDP
            if self._browser.transport == "pipe":
                self._cdp = SyncPipeCDP(*self._browser.pipes)
            else:
                self._cdp = SyncCDP(self._browser.ws_url)
            self._resources.callback(self._cdp.close)
            try:
                self._cdp.connect()
            except (ConnectionError_, FutureTimeoutError) as error:
                if self._browser.transport == "pipe":
                    raise ChromeStartError(
                        "Chrome DevTools pipe failed to start",
                        stderr=self._browser.stderr,
                    ) from error
                raise
        except BaseException:
            self.close()
            raise
        atexit.register(self.close)

    @property
    def browser(self) -> Chrome:
        """The owned Chrome process; its lifetime is managed by this renderer."""
        return self._browser

    def _get_cdp(self) -> SyncCDP | SyncPipeCDP:
        if self._closed:
            raise RuntimeError("Renderer is closed; create a new Renderer.")
        if not self._browser.is_alive():
            raise ConnectionError_(
                "Renderer browser is not running; create a new Renderer."
            )
        return self._cdp

    def webshot(
        self, url: str | Path, file: str | Path = "webshot.png", **kwargs: Any
    ) -> Path:
        """Capture a page with this renderer. Options match `nokap.webshot()`."""
        return webshot(url, file, renderer=self, **kwargs)

    def from_html(
        self, html: str, file: str | Path = "webshot.png", **kwargs: Any
    ) -> Path:
        """Capture HTML with this renderer. Options match `nokap.from_html()`."""
        return from_html(html, file, renderer=self, **kwargs)

    def close(self) -> None:
        """Close this renderer permanently. Other renderer instances are unaffected."""
        if self._closed:
            return
        self._closed = True
        atexit.unregister(self.close)
        self._resources.close()

    def __enter__(self) -> Renderer:
        self._get_cdp()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# The convenience functions share one renderer. Explicit instances own theirs.
_renderer: Renderer | None = None
_MAX_RETRIES = 2


def _get_renderer() -> Renderer:
    global _renderer
    if _renderer is not None and not _renderer.browser.is_alive():
        close()
    if _renderer is None:
        _renderer = Renderer()
    return _renderer


def close() -> None:
    """
    Close the shared default renderer. Explicit Renderer instances are unaffected.

    A later capture without `renderer=` creates a new default renderer. Cleanup
    also happens automatically at interpreter exit.
    """
    global _renderer
    renderer, _renderer = _renderer, None
    if renderer is not None:
        renderer.close()


atexit.register(close)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def webshot(
    url: str | Path,
    file: str | Path = "webshot.png",
    *,
    renderer: Renderer | None = None,
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
        URL to capture. Can be an http/https URL, a `file://` URL, or a local
        file path (automatically converted to a `file://` URL).
    file
        Output file path. The format is determined by extension:
        `.png`, `.jpg`/`.jpeg`, `.webp` for images; `.pdf` for PDF.
    renderer
        Renderer to borrow for this capture. If None, use the shared default.
        The caller owns an explicit renderer and is responsible for closing it.
    vwidth
        Viewport width in pixels.
    vheight
        Viewport height in pixels.
    selector
        CSS selector(s) to capture. For images, the screenshot is cropped to
        the element's bounding box. For PDFs, produces an element-bounded PDF
        sized to fit the element. Mutually exclusive with `cliprect=`.
    cliprect
        Explicit clip rectangle as (x, y, width, height) in CSS pixels.
        Mutually exclusive with `selector=`.
    expand
        Pixels to expand around the selector bounding box.
        Single int for all sides, or (top, right, bottom, left) tuple.
    delay
        Seconds to wait after page load before capturing.
    zoom
        Zoom/scale factor for raster images (PNG, JPEG, WebP). Values > 1
        produce higher resolution images. Ignored for PDF output since PDFs
        are vector format and always render at full resolution.
    useragent
        Custom User-Agent string.
    page_size
        Paper size for PDF output (e.g., `"letter"`, `"a4"`).
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

    # Retry only the shared default; an explicit renderer owns one browser lifetime.
    attempt = 0
    while True:
        try:
            owner = renderer if renderer is not None else _get_renderer()
            cdp = owner._get_cdp()
            session = Session(cdp, width=vwidth, height=vheight)
            break
        except (ConnectionError_, ChromeStartError, OSError):
            if renderer is not None or attempt == _MAX_RETRIES:
                raise
            # Connection stale or Chrome slow to start (reset and retry)
            close()
            attempt += 1

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
            # Use element-bounded PDF when a specific selector (not just "html")
            # or cliprect targets a sub-region of the page
            use_element_pdf = cliprect is not None or (
                selector is not None and selector != "html"
            )
            if use_element_pdf:
                # Element-bounded PDF: tight fit around selector/cliprect
                # Note: zoom/scale is ignored for PDF and vector output is
                # resolution-independent and always sharp.
                return capture_element_pdf(
                    session,
                    out_file,
                    selector=selector,
                    cliprect=cliprect,
                    expand=expand,
                    print_background=print_background,
                )
            else:
                # Full-page PDF with standard paper dimensions
                return capture_pdf(
                    session,
                    out_file,
                    page_size=page_size,
                    margins=margins,
                    landscape=landscape,
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
    renderer: Renderer | None = None,
    **kwargs: Any,
) -> Path:
    """
    Take a screenshot or PDF from an HTML string.

    This is the primary integration point for packages like `great-tables`
    that generate HTML and need to convert it to an image or PDF.

    For PDF output with a selector (other than `"html"`), produces an
    element-bounded PDF sized to fit the selected element with selectable
    text preserved, and this is useful for embedding tables in presentations.

    Parameters
    ----------
    html
        The HTML content to render.
    file
        Output file path. Format determined by extension (`.png`, `.jpg`, `.webp`
        for images; `.pdf` for PDF).
    selector
        CSS selector to capture (default: `"html"` for full page). When a
        specific selector is used with PDF output, produces a tightly-bounded
        PDF. Wide elements (e.g., tables) are automatically detected and
        rendered at their natural width.
    encoding
        Character encoding for the HTML file.
    renderer
        Renderer to borrow for this capture. If None, use the shared default.
        This function does not close an explicit renderer.
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
        return webshot(tmp_path, file, selector=selector, renderer=renderer, **kwargs)
    finally:
        # Clean up temp file
        try:
            tmp_path.unlink()
        except OSError:
            pass

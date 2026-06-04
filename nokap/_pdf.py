from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ._session import Session
from ._types import PaperSize, PDFOptions


def capture_pdf(
    session: Session,
    file: Path,
    page_size: PaperSize = "letter",
    margins: float | tuple[float, float, float, float] = 0.5,
    landscape: bool = False,
    scale: float = 1.0,
    print_background: bool = False,
    display_header_footer: bool = False,
    header_template: str = "",
    footer_template: str = "",
) -> Path:
    """
    Generate a PDF from the current page.

    Parameters
    ----------
    session
        The active CDP session to print from.
    file
        Output PDF file path.
    page_size
        Named paper size (e.g., "letter", "a4").
    margins
        Margins in inches. Single float for all sides, or
        (top, right, bottom, left) tuple.
    landscape
        Whether to use landscape orientation.
    scale
        Scale of the page rendering (0.1 to 2.0).
    print_background
        Whether to print background graphics.
    display_header_footer
        Whether to display header and footer.
    header_template
        HTML template for the header.
    footer_template
        HTML template for the footer.

    Returns
    -------
    Path
        The output file path.
    """
    opts = PDFOptions.from_page_size(
        page_size=page_size,
        margins=margins,
        landscape=landscape,
        scale=scale,
        print_background=print_background,
    )
    opts.display_header_footer = display_header_footer
    opts.header_template = header_template
    opts.footer_template = footer_template

    params: dict[str, Any] = opts.to_cdp()

    result = session._send("Page.printToPDF", params)
    data = base64.b64decode(result["data"])

    # Write to file
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)

    return file

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ._session import Session
from ._types import ClipRect, Expand, PaperSize, PDFOptions

# CSS pixels per inch (the CSS standard)
_CSS_PX_PER_INCH = 96.0


def _apply_expand(clip: ClipRect, expand: Expand) -> ClipRect:
    """Apply expand padding to a clip rect."""
    return ClipRect(
        x=max(0, clip.x - expand.left),
        y=max(0, clip.y - expand.top),
        width=clip.width + expand.left + expand.right,
        height=clip.height + expand.top + expand.bottom,
        scale=clip.scale,
    )


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


def capture_element_pdf(
    session: Session,
    file: Path,
    selector: str | list[str] | None = None,
    cliprect: tuple[float, float, float, float] | None = None,
    expand: int | tuple[int, int, int, int] = 0,
    print_background: bool = True,
) -> Path:
    """
    Generate a tightly-bounded PDF of a specific element.

    Unlike `capture_pdf` which produces a standard-page PDF, this captures only
    the region around a specific element (similar to how screenshots work) but
    outputs as a vector PDF with selectable text.

    The approach:
    1. Measure the element's bounding box
    2. Inject @media print CSS to isolate the element at (0, 0) and hide
       everything else
    3. Set paper dimensions to match the element size (+ expand)
    4. Call Page.printToPDF with zero margins

    Parameters
    ----------
    session
        The active CDP session to print from.
    file
        Output PDF file path.
    selector
        CSS selector(s) to capture. The PDF is sized to fit the element's
        bounding box. Mutually exclusive with `cliprect`.
    cliprect
        Explicit clip rectangle as (x, y, width, height) in CSS pixels.
        Mutually exclusive with `selector`.
    expand
        Pixels to expand around the element bounding box. Single int for all
        sides, or (top, right, bottom, left) tuple.
    print_background
        Whether to print background graphics. Defaults to True since element
        captures typically need backgrounds (e.g., styled tables).

    Returns
    -------
    Path
        The output file path.
    """
    if selector is not None and cliprect is not None:
        raise ValueError("Cannot specify both 'selector' and 'cliprect'.")

    if selector is None and cliprect is None:
        raise ValueError("Either 'selector' or 'cliprect' must be provided.")

    # Determine the target clip region
    if selector is not None:
        if isinstance(selector, str):
            clip = session.get_element_bounds(selector)
            sel_str = selector
        else:
            clip = session.get_elements_union_bounds(selector)
            sel_str = ", ".join(selector)
    else:
        assert cliprect is not None
        clip = ClipRect(
            x=cliprect[0], y=cliprect[1], width=cliprect[2], height=cliprect[3]
        )
        sel_str = None

    # Apply expand padding and track offsets for positioning
    offset_left = 0
    offset_top = 0
    if expand:
        exp = Expand.from_value(expand)
        offset_left = exp.left
        offset_top = exp.top
        clip = _apply_expand(clip, exp)

    # Calculate paper dimensions in inches
    paper_width = clip.width / _CSS_PX_PER_INCH
    paper_height = clip.height / _CSS_PX_PER_INCH

    # Enforce minimum dimensions (Chrome requires > 0)
    paper_width = max(paper_width, 0.1)
    paper_height = max(paper_height, 0.1)

    # Inject print-isolation CSS via JavaScript
    # Strategy: hide everything, then show only the target element repositioned
    # within the page, offset by expand so whitespace is even on all sides.
    if sel_str is not None:
        # Use the selector to isolate the element for @media print
        inject_js = f"""
        (() => {{
            const style = document.createElement('style');
            style.id = '__nokap_element_pdf_style';
            style.textContent = `
                @media print {{
                    body * {{
                        visibility: hidden !important;
                    }}
                    {sel_str},
                    {sel_str} * {{
                        visibility: visible !important;
                    }}
                    {sel_str} {{
                        position: fixed !important;
                        left: {offset_left}px !important;
                        top: {offset_top}px !important;
                        margin: 0 !important;
                    }}
                    @page {{
                        margin: 0;
                    }}
                }}
            `;
            document.head.appendChild(style);
            return true;
        }})()
        """
    else:
        # For cliprect-based capture, we hide everything and use a clipping
        # approach: create an overlay element that shows only the target region
        inject_js = f"""
        (() => {{
            const style = document.createElement('style');
            style.id = '__nokap_element_pdf_style';
            style.textContent = `
                @media print {{
                    html, body {{
                        margin: 0 !important;
                        padding: 0 !important;
                    }}
                    body {{
                        position: relative !important;
                        transform: translate({-clip.x}px, {-clip.y}px) !important;
                        overflow: hidden !important;
                    }}
                    @page {{
                        margin: 0;
                        size: {clip.width}px {clip.height}px;
                    }}
                }}
            `;
            document.head.appendChild(style);
            return true;
        }})()
        """

    session.evaluate(inject_js)

    try:
        # Build PDF params with element-fitted paper size and zero margins
        params: dict[str, Any] = {
            "paperWidth": paper_width,
            "paperHeight": paper_height,
            "marginTop": 0,
            "marginBottom": 0,
            "marginLeft": 0,
            "marginRight": 0,
            "scale": 1.0,
            "printBackground": print_background,
            "displayHeaderFooter": False,
            "headerTemplate": "",
            "footerTemplate": "",
            "transferMode": "ReturnAsBase64",
        }

        result = session._send("Page.printToPDF", params)
        data = base64.b64decode(result["data"])

        # Write to file
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)

        return file

    finally:
        # Remove the injected style
        cleanup_js = """
        (() => {
            const el = document.getElementById('__nokap_element_pdf_style');
            if (el) el.remove();
        })()
        """
        try:
            session.evaluate(cleanup_js)
        except Exception:
            pass

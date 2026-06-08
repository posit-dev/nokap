from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ._session import Session
from ._types import ClipRect, Expand, ImageFormat


def _resolve_format(file: Path) -> ImageFormat:
    """Determine the image format from the file extension."""
    ext = file.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return "jpeg"
    if ext == ".webp":
        return "webp"
    return "png"


def _apply_expand(clip: ClipRect, expand: Expand) -> ClipRect:
    """Apply expand padding to a clip rect."""
    return ClipRect(
        x=max(0, clip.x - expand.left),
        y=max(0, clip.y - expand.top),
        width=clip.width + expand.left + expand.right,
        height=clip.height + expand.top + expand.bottom,
        scale=clip.scale,
    )


def capture_screenshot(
    session: Session,
    file: Path,
    selector: str | list[str] | None = None,
    cliprect: tuple[float, float, float, float] | None = None,
    expand: int | tuple[int, int, int, int] = 0,
    zoom: float = 1,
    quality: int | None = None,
) -> Path:
    """
    Capture a screenshot from the current page.

    Parameters
    ----------
    session
        The active CDP session to capture from.
    file
        Output file path. Format is determined by extension (.png, .jpg, .webp).
    selector
        CSS selector(s) to capture. If provided, the screenshot is cropped to
        the element's bounding box. Mutually exclusive with `cliprect`.
    cliprect
        Explicit clip rectangle as (x, y, width, height). Mutually exclusive
        with `selector`.
    expand
        Pixels to expand around the selector bounding box. Single int for all
        sides, or (top, right, bottom, left) tuple.
    zoom
        Zoom/scale factor. Values > 1 produce higher resolution images.
    quality
        JPEG/WebP quality (0-100). Ignored for PNG.

    Returns
    -------
    Path
        The output file path.
    """
    if selector is not None and cliprect is not None:
        raise ValueError("Cannot specify both 'selector' and 'cliprect'.")

    fmt = _resolve_format(file)

    # Widen the viewport so elements (especially tables) can expand to their
    # natural/intrinsic width without being constrained by the viewport.
    if selector is not None:
        _WIDE_VIEWPORT = 16384
        session.set_viewport(
            _WIDE_VIEWPORT,
            session._height,
            device_scale_factor=zoom if zoom != 1 else 1.0,
        )
        # Force layout reflow
        session.evaluate("document.body.offsetHeight")
    elif zoom != 1:
        # Apply zoom via device scale factor
        session.set_viewport(session._width, session._height, device_scale_factor=zoom)

    # Determine clip region
    clip: ClipRect | None = None

    if selector is not None:
        if isinstance(selector, str):
            clip = session.get_element_bounds(selector)
        else:
            clip = session.get_elements_union_bounds(selector)

        # Apply expand
        if expand:
            exp = Expand.from_value(expand)
            clip = _apply_expand(clip, exp)

    elif cliprect is not None:
        clip = ClipRect(
            x=cliprect[0], y=cliprect[1], width=cliprect[2], height=cliprect[3]
        )

    # Build CDP params
    params: dict[str, Any] = {
        "format": fmt,
        "captureBeyondViewport": True,
    }
    if quality is not None and fmt in ("jpeg", "webp"):
        params["quality"] = quality
    if clip is not None:
        params["clip"] = clip.to_cdp()

    # Capture
    result = session._send("Page.captureScreenshot", params)
    data = base64.b64decode(result["data"])

    # Write to file
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(data)

    return file

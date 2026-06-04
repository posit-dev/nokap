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



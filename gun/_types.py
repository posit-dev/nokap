from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ImageFormat = Literal["png", "jpeg", "webp"]
PaperSize = Literal["letter", "legal", "tabloid", "ledger", "a0", "a1", "a2", "a3", "a4", "a5", "a6"]


# Paper dimensions in inches (width, height)
PAPER_SIZES: dict[str, tuple[float, float]] = {
    "letter": (8.5, 11),
    "legal": (8.5, 14),
    "tabloid": (11, 17),
    "ledger": (17, 11),
    "a0": (33.1, 46.8),
    "a1": (23.4, 33.1),
    "a2": (16.5, 23.4),
    "a3": (11.7, 16.5),
    "a4": (8.27, 11.7),
    "a5": (5.83, 8.27),
    "a6": (4.13, 5.83),
}


@dataclass(frozen=True)
class ClipRect:
    """A rectangle defining a capture region."""

    x: float
    y: float
    width: float
    height: float
    scale: float = 1.0

    def to_cdp(self) -> dict[str, float]:
        """Convert to CDP clip parameter format."""
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "scale": self.scale,
        }


@dataclass(frozen=True)
class Expand:
    """Padding to add around a selector's bounding box."""

    top: int = 0
    right: int = 0
    bottom: int = 0
    left: int = 0

    @classmethod
    def from_value(cls, value: int | tuple[int, int, int, int]) -> Expand:
        """Create from a single int (all sides) or 4-tuple (top, right, bottom, left)."""
        if isinstance(value, int):
            return cls(top=value, right=value, bottom=value, left=value)
        return cls(top=value[0], right=value[1], bottom=value[2], left=value[3])



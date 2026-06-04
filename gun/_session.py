from __future__ import annotations

import asyncio
import time
from typing import Any

from ._cdp import SyncCDP
from ._types import ClipRect, Expand


class Session:
    """
    A CDP session representing a single browser tab.

    Provides methods for navigation, viewport control, JavaScript evaluation,
    and DOM queries needed for screenshot capture.

    Parameters
    ----------
    cdp
        The SyncCDP connection to use.
    width
        Initial viewport width in pixels.
    height
        Initial viewport height in pixels.
    """

    def __init__(self, cdp: SyncCDP, width: int = 992, height: int = 744) -> None:
        self._cdp = cdp
        self._session_id: str | None = None
        self._target_id: str | None = None
        self._width = width
        self._height = height
        self._device_scale_factor = 1.0
        self._closed = False

        self._create()

    def _create(self) -> None:
        """Create a new target (tab) and attach to it."""
        # Create a new blank tab
        result = self._cdp.send("Target.createTarget", {"url": "about:blank"})
        self._target_id = result["targetId"]

        # Attach to the target with flatten mode (session messages on same WS)
        result = self._cdp.send(
            "Target.attachToTarget",
            {"targetId": self._target_id, "flatten": True},
        )
        self._session_id = result["sessionId"]

        # Enable required domains
        self._send("Page.enable")
        self._send("DOM.enable")
        self._send("Runtime.enable")

        # Set viewport
        self.set_viewport(self._width, self._height)

    def _send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a command scoped to this session."""
        return self._cdp.send(method, params, session_id=self._session_id)

    def navigate(self, url: str, timeout: float = 30.0) -> None:
        """
        Navigate to a URL and wait for the page to load.

        Parameters
        ----------
        url
            The URL to navigate to.
        timeout
            Maximum seconds to wait for the page to load.
        """
        # Set up a load event waiter
        load_fired = {"done": False}

        def on_load(params: dict[str, Any]) -> None:
            load_fired["done"] = True

        self._cdp.on("Page.loadEventFired", on_load)

        try:
            result = self._send("Page.navigate", {"url": url})
            if "errorText" in result:
                raise RuntimeError(f"Navigation failed: {result['errorText']}")

            # Wait for load event
            deadline = time.monotonic() + timeout
            while not load_fired["done"] and time.monotonic() < deadline:
                time.sleep(0.05)

            if not load_fired["done"]:
                raise TimeoutError(f"Page load timed out after {timeout}s: {url}")
        finally:
            self._cdp.off("Page.loadEventFired", on_load)

    def set_viewport(
        self,
        width: int,
        height: int,
        device_scale_factor: float = 1.0,
        mobile: bool = False,
    ) -> None:
        """
        Set the viewport dimensions.

        Parameters
        ----------
        width
            Viewport width in pixels.
        height
            Viewport height in pixels.
        device_scale_factor
            Device scale factor (e.g., 2 for retina).
        mobile
            Whether to emulate a mobile device.
        """
        self._width = width
        self._height = height
        self._device_scale_factor = device_scale_factor
        self._send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": width,
                "height": height,
                "deviceScaleFactor": device_scale_factor,
                "mobile": mobile,
            },
        )


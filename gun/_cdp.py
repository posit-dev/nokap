from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from typing import Any

import websockets
import websockets.asyncio.client


class CDPConnection:
    """
    Async CDP WebSocket client.

    Sends commands and receives responses/events from a Chrome DevTools Protocol
    endpoint. Each command gets a unique incremental ID; responses are matched by ID.

    Parameters
    ----------
    ws_url
        The WebSocket URL from Chrome's remote debugging port.
    timeout
        Default timeout in seconds for command responses.
    """

    def __init__(self, ws_url: str, timeout: float = 30.0) -> None:
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws: websockets.asyncio.client.ClientConnection | None = None
        self._cmd_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._event_listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._recv_task: asyncio.Task[None] | None = None
        self._closed = False

    async def connect(self) -> None:
        """Establish the WebSocket connection and start the message receiver."""
        self._ws = await websockets.asyncio.client.connect(
            self._ws_url,
            max_size=100 * 1024 * 1024,  # 100MB max message size for screenshots
        )
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Continuously read messages from the WebSocket and dispatch them."""
        assert self._ws is not None
        try:
            async for raw_msg in self._ws:
                if isinstance(raw_msg, bytes):
                    raw_msg = raw_msg.decode("utf-8")
                msg: dict[str, Any] = json.loads(raw_msg)

                if "id" in msg:
                    # Command response
                    cmd_id = msg["id"]
                    future = self._pending.pop(cmd_id, None)
                    if future and not future.done():
                        if "error" in msg:
                            future.set_exception(
                                CDPError(msg["error"].get("message", "Unknown CDP error"), msg["error"])
                            )
                        else:
                            future.set_result(msg.get("result", {}))
                elif "method" in msg:
                    # Event notification
                    method = msg["method"]
                    params = msg.get("params", {})
                    listeners = self._event_listeners.get(method, [])
                    for listener in listeners:
                        listener(params)
        except websockets.exceptions.ConnectionClosed:
            if not self._closed:
                # Resolve all pending futures with an error
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(ConnectionError("WebSocket connection closed unexpectedly"))
                self._pending.clear()


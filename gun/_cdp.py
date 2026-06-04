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

    async def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """
        Send a CDP command and wait for the response.

        Parameters
        ----------
        method
            The CDP method name (e.g., "Page.navigate").
        params
            Parameters for the CDP command.
        session_id
            Optional session ID for session-scoped commands.
        timeout
            Override the default timeout for this command.

        Returns
        -------
        dict
            The result from the CDP response.

        Raises
        ------
        CDPError
            If the CDP command returns an error.
        asyncio.TimeoutError
            If the command times out.
        """
        if self._ws is None:
            raise RuntimeError("Not connected. Call connect() first.")

        self._cmd_id += 1
        cmd_id = self._cmd_id

        msg: dict[str, Any] = {"id": cmd_id, "method": method}
        if params:
            msg["params"] = params
        if session_id:
            msg["sessionId"] = session_id

        loop = asyncio.get_event_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[cmd_id] = future

        await self._ws.send(json.dumps(msg))

        return await asyncio.wait_for(future, timeout=timeout or self._timeout)

    def on(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """Register a listener for a CDP event."""
        if event not in self._event_listeners:
            self._event_listeners[event] = []
        self._event_listeners[event].append(callback)

    def off(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        """Remove a listener for a CDP event."""
        listeners = self._event_listeners.get(event, [])
        if callback in listeners:
            listeners.remove(callback)

    async def close(self) -> None:
        """Close the WebSocket connection."""
        self._closed = True
        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            await self._ws.close()
            self._ws = None
        # Cancel any remaining pending futures
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()



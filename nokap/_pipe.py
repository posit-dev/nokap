from __future__ import annotations

import json
import os
import selectors
import threading
from collections.abc import Callable
from concurrent.futures import Future
from contextlib import ExitStack
from typing import Any

from ._errors import CDPError, ConnectionError_


class SyncPipeCDP:
    """CDP commands and events over Chrome's NUL-delimited pipe transport."""

    def __init__(self, read_fd: int, write_fd: int, timeout: float = 30.0) -> None:
        self._timeout = timeout
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._cmd_id = 0
        self._pending: dict[int, Future[dict[str, Any]]] = {}
        self._listeners: dict[str, list[Callable[[dict[str, Any]], None]]] = {}
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._closed = False
        with ExitStack() as resources:
            self._read_fd = os.dup(read_fd)
            resources.callback(os.close, self._read_fd)
            self._write_fd = os.dup(write_fd)
            resources.callback(os.close, self._write_fd)
            self._cancel_read, self._cancel_write = os.pipe()
            resources.callback(os.close, self._cancel_read)
            resources.callback(os.close, self._cancel_write)
            self._resources = resources.pop_all()

    def connect(self) -> None:
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        # A protocol response establishes readiness without a listening port.
        self.send("Browser.getVersion")

    def _receive_loop(self) -> None:
        buffer = bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self._read_fd, selectors.EVENT_READ)
                selector.register(self._cancel_read, selectors.EVENT_READ)
                while True:
                    for key, _ in selector.select():
                        if key.fd == self._cancel_read:
                            return
                        chunk = os.read(self._read_fd, 65536)
                        if not chunk:
                            raise ConnectionError_("Chrome DevTools pipe closed")
                        buffer.extend(chunk)
                        while (end := buffer.find(0)) >= 0:
                            message: dict[str, Any] = json.loads(buffer[:end])
                            del buffer[: end + 1]
                            self._dispatch(message)
        except Exception as error:
            self._fail_pending(error)

    def _dispatch(self, message: dict[str, Any]) -> None:
        with self._lock:
            if "id" in message:
                future = self._pending.pop(message["id"], None)
                callbacks = []
            else:
                future = None
                callbacks = list(self._listeners.get(message.get("method", ""), []))
        if future is not None:
            if "error" in message:
                error = message["error"]
                future.set_exception(CDPError(error["message"], error))
            else:
                future.set_result(message.get("result", {}))
        for callback in callbacks:
            callback(message.get("params", {}))

    def _fail_pending(self, error: BaseException) -> None:
        with self._lock:
            self._error = error
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            future.set_exception(error)

    def send(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        session_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._closed:
                raise ConnectionError_("Chrome DevTools pipe is closed")
            if self._error is not None:
                raise self._error
            self._cmd_id += 1
            command_id = self._cmd_id
            message: dict[str, Any] = {"id": command_id, "method": method}
            if params:
                message["params"] = params
            if session_id:
                message["sessionId"] = session_id
            future: Future[dict[str, Any]] = Future()
            self._pending[command_id] = future
        try:
            # Keep receiving events while a command is being written.
            with self._write_lock:
                data = memoryview(json.dumps(message).encode() + b"\0")
                while data:
                    written = os.write(self._write_fd, data)
                    data = data[written:]
            return future.result(timeout=timeout or self._timeout)
        finally:
            with self._lock:
                self._pending.pop(command_id, None)

    def on(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners.setdefault(event, []).append(callback)

    def off(self, event: str, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._listeners[event].remove(callback)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        os.write(self._cancel_write, b"\0")
        if self._thread is not None:
            self._thread.join()
        self._fail_pending(ConnectionError_("Chrome DevTools pipe is closed"))
        self._resources.close()

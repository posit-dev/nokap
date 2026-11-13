import errno
import json
import os
import sys
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from nokap._errors import CDPError, ConnectionError_
from nokap._pipe import SyncPipeCDP

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX pipes")

Reply = Callable[[dict[str, Any]], bytes]


class FakeChrome:
    """Answer NUL-delimited commands on a pair of pipes from a background thread."""

    def __init__(self, reply: Reply) -> None:
        self._commands, self.write_fd = os.pipe()
        self.read_fd, self._responses = os.pipe()
        self._reply = reply
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        buffer = b""
        while chunk := os.read(self._commands, 65536):
            buffer += chunk
            while b"\0" in buffer:
                raw, buffer = buffer.split(b"\0", 1)
                data = memoryview(self._reply(json.loads(raw)))
                while data:
                    data = data[os.write(self._responses, data) :]

    def close(self) -> None:
        os.close(self.write_fd)
        self._thread.join(timeout=5)
        for fd in (self._commands, self.read_fd, self._responses):
            os.close(fd)


def frame(*messages: dict[str, Any]) -> bytes:
    return b"".join(json.dumps(message).encode() + b"\0" for message in messages)


@pytest.fixture
def connect() -> Iterator[Callable[[Reply], SyncPipeCDP]]:
    opened: list[tuple[FakeChrome, SyncPipeCDP]] = []

    def start(reply: Reply) -> SyncPipeCDP:
        chrome = FakeChrome(reply)
        connection = SyncPipeCDP(chrome.read_fd, chrome.write_fd, timeout=5)
        opened.append((chrome, connection))
        connection.connect()
        return connection

    yield start
    for chrome, connection in opened:
        connection.close()
        chrome.close()


def test_messages_split_and_batched_across_reads(connect) -> None:
    large = "x" * 300_000
    events: list[dict[str, Any]] = []

    def reply(message: dict[str, Any]) -> bytes:
        if message["method"] != "Test.large":
            return frame({"id": message["id"], "result": {}})
        # Several messages in one write, one far larger than a pipe read
        return frame(
            {"method": "Test.event", "params": {"n": 1}},
            {"method": "Test.event", "params": {"n": 2}},
            {"id": message["id"], "result": {"data": large}},
        )

    connection = connect(reply)
    connection.on("Test.event", events.append)
    assert connection.send("Test.large") == {"data": large}
    assert events == [{"n": 1}, {"n": 2}]


def test_malformed_message_fails_as_connection_error(connect) -> None:
    def reply(message: dict[str, Any]) -> bytes:
        if message["method"] == "Browser.getVersion":
            return frame({"id": message["id"], "result": {}})
        return b"{not json\0"

    connection = connect(reply)
    with pytest.raises(ConnectionError_) as first:
        connection.send("Test.break")
    assert isinstance(first.value.__cause__, json.JSONDecodeError)
    # Later sends report the failure without reusing one exception object
    with pytest.raises(ConnectionError_) as second:
        connection.send("Test.again")
    assert second.value is not first.value
    assert second.value.__cause__ is first.value


def test_error_without_message_keeps_connection(connect) -> None:
    def reply(message: dict[str, Any]) -> bytes:
        if message["method"] == "Test.fail":
            return frame({"id": message["id"], "error": {"code": -1}})
        return frame({"id": message["id"], "result": {"ok": True}})

    connection = connect(reply)
    with pytest.raises(CDPError, match="Unknown CDP error"):
        connection.send("Test.fail")
    assert connection.send("Test.ok") == {"ok": True}


def test_off_ignores_unknown_listeners(connect) -> None:
    connection = connect(lambda message: frame({"id": message["id"], "result": {}}))
    connection.off("Test.never", print)
    connection.on("Test.event", print)
    connection.off("Test.event", repr)


@pytest.mark.parametrize("failure", ["second_dup", "cancel_pipe"])
def test_allocation_failure_closes_descriptors(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    source = os.pipe()
    allocate_pipe, duplicate = os.pipe, os.dup
    allocated: list[int] = []
    allocation_error = OSError(errno.EMFILE, "Too many open files")

    def dup(fd: int) -> int:
        if failure == "second_dup" and allocated:
            raise allocation_error
        allocated.append(duplicate(fd))
        return allocated[-1]

    def pipe() -> tuple[int, int]:
        if failure == "cancel_pipe":
            raise allocation_error
        descriptors = allocate_pipe()
        allocated.extend(descriptors)
        return descriptors

    monkeypatch.setattr(os, "dup", dup)
    monkeypatch.setattr(os, "pipe", pipe)
    try:
        with pytest.raises(OSError) as raised:
            SyncPipeCDP(*source)
        assert raised.value is allocation_error
        for descriptor in allocated:
            with pytest.raises(OSError) as closed:
                os.fstat(descriptor)
            assert closed.value.errno == errno.EBADF
    finally:
        for descriptor in source:
            os.close(descriptor)

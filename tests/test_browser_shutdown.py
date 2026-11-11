import json
import os
import shlex
import signal
import sys
import textwrap
from contextlib import suppress
from pathlib import Path

import pytest

import nokap

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable fixture"),
]


@pytest.mark.parametrize("transport", ["pipe", "websocket"])
def test_close_waits_for_profile_flush(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, transport: str
) -> None:
    monkeypatch.delenv("NOKAP_CHROME_ARGS", raising=False)
    finished = tmp_path / "finished"
    details = tmp_path / "processes.json"
    program = tmp_path / "browser.py"
    program.write_text(
        textwrap.dedent("""
            import atexit
            import json
            import os
            from pathlib import Path
            import subprocess
            import sys

            if sys.argv[1] == "child":
                print("ready", flush=True)
                if sys.stdin.buffer.read(1) != b"x":
                    raise SystemExit(2)
                state = Path(sys.argv[2]) / "Default" / "Network Persistent State"
                state.parent.mkdir(parents=True)
                state.write_text("profile flushed")
                Path(sys.argv[3]).write_text("flushed")
                raise SystemExit(0)

            finished, details, *arguments = sys.argv[1:]
            profile = next(arg.split("=", 1)[1] for arg in arguments
                           if arg.startswith("--user-data-dir="))
            child = subprocess.Popen(
                [sys.executable, __file__, "child", profile, finished],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            )
            assert child.stdout.readline() == b"ready\\n"
            Path(details).write_text(json.dumps({
                "browser_pid": os.getpid(), "child_pid": child.pid, "profile": profile,
            }))
            atexit.register(
                Path(finished).with_name("browser-finished").write_text, "exited"
            )

            def handle(message):
                assert message["method"] in ("Browser.getVersion", "Browser.close")
                closing = message["method"] == "Browser.close"
                return {"id": message["id"], "result": {}}, closing

            def drain():
                child.stdin.write(b"x")
                child.stdin.flush()
                assert child.wait(timeout=10) == 0

            if "--remote-debugging-pipe" in arguments:
                with os.fdopen(3, "rb", buffering=0) as reader:
                    message = bytearray()
                    while byte := reader.read(1):
                        if byte != b"\\0":
                            message.extend(byte)
                            continue
                        response, closing = handle(json.loads(message))
                        try:
                            os.write(4, json.dumps(response).encode() + b"\\0")
                        finally:
                            if closing:
                                drain()
                        message.clear()
                        if closing:
                            break
            else:
                from threading import Event, Thread
                from websockets.exceptions import ConnectionClosed
                from websockets.sync.server import serve

                drained = Event()

                def connection(socket):
                    for message in socket:
                        response, closing = handle(json.loads(message))
                        if closing:
                            try:
                                socket.send(json.dumps(response))
                            except ConnectionClosed:
                                pass
                            finally:
                                drain()
                                drained.set()
                            return
                        socket.send(json.dumps(response))

                port = int(next(arg.split("=", 1)[1] for arg in arguments
                                if arg.startswith("--remote-debugging-port=")))
                with serve(connection, "127.0.0.1", port) as server:
                    serving = Thread(target=server.serve_forever)
                    serving.start()
                    print(f"DevTools listening on ws://127.0.0.1:{port}/browser",
                          file=sys.stderr, flush=True)
                    drained.wait()
                serving.join()
            """)
    )
    executable = tmp_path / "chrome"
    executable.write_text(
        "#!/bin/sh\nexec "
        + shlex.join([sys.executable, str(program), str(finished), str(details)])
        + ' "$@"\n'
    )
    executable.chmod(0o755)
    try:
        with nokap.Chrome(str(executable), transport=transport) as chrome:
            processes = json.loads(details.read_text())
            assert chrome.pid == processes["browser_pid"]
            assert chrome.is_alive()
            os.kill(processes["child_pid"], 0)
            assert not finished.exists()
        assert finished.is_file(), "Chrome closed before the child flushed its profile"
        assert finished.read_text() == "flushed"
        assert (tmp_path / "browser-finished").read_text() == "exited"
        with pytest.raises(ProcessLookupError):
            os.kill(processes["child_pid"], 0)
        assert not Path(processes["profile"]).exists()
        chrome.close()
        assert not chrome.is_alive()
    finally:
        if details.exists():
            processes = json.loads(details.read_text())
            for key in ("child_pid", "browser_pid"):
                with suppress(ProcessLookupError):
                    os.kill(processes[key], signal.SIGKILL)

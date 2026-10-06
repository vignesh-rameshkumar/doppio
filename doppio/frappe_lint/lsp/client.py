"""
A minimal, real LSP client: speaks actual JSON-RPC-over-stdio framing to
a real `bench lint-lsp` subprocess. Shared by smoke_test.py (automated
protocol assertions) and watch_file.py (an interactive terminal client
for trying the server out by hand, without an editor).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time


class LspClient:
    def __init__(self, cmd: list[str], cwd: str | None = None):
        self.proc = subprocess.Popen(
            cmd, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
        )
        self._id = 0
        self.notifications: list[dict] = []
        self._responses: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_lines: list[str] = []
        self._stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._stderr_reader.start()

    def _read_stderr(self):
        for line in self.proc.stderr:
            self._stderr_lines.append(line.decode(errors="replace").rstrip())

    def _read_loop(self):
        buf = b""
        while True:
            chunk = self.proc.stdout.read(1)
            if not chunk:
                return
            buf += chunk
            if buf.endswith(b"\r\n\r\n") and b"Content-Length" in buf:
                length = int(buf.split(b"Content-Length:")[1].split(b"\r\n")[0].strip())
                body = b""
                while len(body) < length:
                    body += self.proc.stdout.read(length - len(body))
                msg = json.loads(body)
                with self._lock:
                    if "id" in msg and "method" not in msg:
                        self._responses[msg["id"]] = msg
                    else:
                        self.notifications.append(msg)
                buf = b""

    def _send(self, payload: dict):
        body = json.dumps(payload).encode()
        header = f"Content-Length: {len(body)}\r\n\r\n".encode()
        self.proc.stdin.write(header + body)
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout: float = 5.0) -> dict:
        self._id += 1
        msg_id = self._id
        self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                if msg_id in self._responses:
                    return self._responses.pop(msg_id)
            time.sleep(0.02)
        raise TimeoutError(f"no response to {method} within {timeout}s")

    def notify(self, method: str, params: dict):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def notification_count(self) -> int:
        with self._lock:
            return len(self.notifications)

    def wait_for_diagnostics(self, uri: str, after: int = 0, timeout: float = 3.0) -> list:
        """`after` must be a count captured BEFORE the notify() that's
        expected to trigger new diagnostics -- capturing it here instead,
        after any caller-side sleep, would silently skip a notification
        that already arrived during that sleep and then time out for the
        wrong reason (a real bug this harness hit once during development)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                for n in self.notifications[after:]:
                    if n.get("method") == "textDocument/publishDiagnostics" \
                            and n["params"]["uri"] == uri:
                        return n["params"]["diagnostics"]
            time.sleep(0.02)
        raise TimeoutError(f"no publishDiagnostics for {uri} within {timeout}s")

    def shutdown(self):
        try:
            self.request("shutdown", {}, timeout=2.0)
            self.notify("exit", {})
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def uri_for(path: str) -> str:
    return "file://" + os.path.abspath(path)

"""
An interactive way to see frappe-lint's live diagnostics working, without
needing an editor's LSP client set up first.

Starts a real `bench lint-lsp` subprocess, opens the file you point it
at, then polls that file on disk every 0.5s -- when it changes (edited
with any text editor, vim, even `echo >>`), sends a real textDocument/
didChange notification and prints whatever diagnostics come back.

This is not what a production editor integration does (a real editor
sends didChange on every keystroke, not by polling a file's mtime) --
it's a stand-in for "I don't have VS Code or Neovim wired up yet, but I
want to see this work right now." The server-side behavior it exercises
(debounce, baseline suppression, last-good-AST fallback on a syntax
error) is identical either way; only who's calling didChange differs.

Run: bench lint-lsp-watch <path/to/file.py>
 or: python3 -m doppio.frappe_lint.lsp.watch_file <path/to/file.py>

Ctrl+C to stop.
"""
from __future__ import annotations

import functools
import os
import sys
import time

from doppio.frappe_lint.lsp.client import LspClient, uri_for

print = functools.partial(print, flush=True)  # reliable output whether stdout is a TTY or piped

_SEVERITY_LABEL = {1: "ERROR", 2: "WARN ", 3: "INFO "}


def _print_diagnostics(path: str, diags: list) -> None:
    # Deliberately no clear-screen escape here: this needs to work the same
    # whether stdout is a real TTY or piped/redirected (e.g. into a log file
    # while testing) -- a clear-screen code sent into a non-TTY pipe either
    # does nothing useful or corrupts captured output. A divider line is a
    # little less pretty in a real terminal but works everywhere.
    print("=" * 70)
    print(f"watching: {path}")
    print(f"({time.strftime('%H:%M:%S')}) {len(diags)} finding(s)\n")
    if not diags:
        print("  (clean)")
    for d in sorted(diags, key=lambda x: x["range"]["start"]["line"]):
        line = d["range"]["start"]["line"] + 1
        sev = _SEVERITY_LABEL.get(d.get("severity"), "?    ")
        print(f"  {sev} L{line:<4} {d['message']}")
    print()


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python3 -m doppio.frappe_lint.lsp.watch_file <path/to/file.py>")
        return 2
    path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(path):
        print(f"no such file: {path}")
        return 2

    # sys.executable is whatever interpreter is currently running this file --
    # correct whether that's `bench lint-lsp-watch` (the bench's own venv
    # python) or a manual `env/bin/python3 -m doppio.frappe_lint.lsp.watch_file`,
    # and unlike a hardcoded path, doesn't break on a different machine.
    client = LspClient([sys.executable, "-m", "doppio.frappe_lint.lsp.server"])
    uri = uri_for(path)

    try:
        client.request("initialize", {"processId": os.getpid(), "rootUri": None, "capabilities": {}})
        client.notify("initialized", {})

        source = open(path, encoding="utf-8").read()
        before = client.notification_count()
        client.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": source},
        })
        try:
            diags = client.wait_for_diagnostics(uri, after=before, timeout=15.0)
        except TimeoutError:
            diags = []
        _print_diagnostics(path, diags)

        version = 1
        last_mtime = os.path.getmtime(path)
        while True:
            time.sleep(0.5)
            if client.proc.poll() is not None:
                print("\nserver process exited unexpectedly.")
                if client._stderr_lines:
                    print("--- stderr ---")
                    for line in client._stderr_lines[-20:]:
                        print(" ", line)
                return 1
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if mtime == last_mtime:
                continue
            last_mtime = mtime
            version += 1
            try:
                source = open(path, encoding="utf-8").read()
            except OSError:
                continue
            before = client.notification_count()
            client.notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": source}],
            })
            try:
                diags = client.wait_for_diagnostics(uri, after=before, timeout=3.0)
                _print_diagnostics(path, diags)
            except TimeoutError:
                pass  # debounced pass produced no new publish (e.g. transient syntax error); keep last view
    except KeyboardInterrupt:
        print("\nstopping.")
        return 0
    finally:
        client.shutdown()


if __name__ == "__main__":
    sys.exit(main())

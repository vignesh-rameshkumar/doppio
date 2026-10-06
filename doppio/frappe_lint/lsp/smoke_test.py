"""
A real LSP client, speaking real JSON-RPC-over-stdio framing, driving a
real `bench lint-lsp` subprocess. Not a mock, not a unit test against
internal functions -- this proves the server behaves correctly from the
outside, the same way an editor would actually talk to it: initialize,
open a file with a known bug, read back textDocument/publishDiagnostics,
edit it, wait out the debounce, read the updated diagnostics.

This exists because a GUI editor can't be driven from this environment --
this is the rigorous substitute for "open it in VS Code and look."

Run: python3 -m doppio.frappe_lint.lsp.smoke_test
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time

from doppio.frappe_lint.lsp.client import LspClient, uri_for as _uri

_HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    workdir = os.path.join(_HERE, "..", "..", "..", "..")  # bench root-ish, doesn't matter here
    bench_python = None
    for candidate in ("/home/vignesh/frappe14/env/bin/python3",):
        if os.path.exists(candidate):
            bench_python = candidate
    if not bench_python:
        print("SKIP: no bench python found to launch the server with")
        return 0

    server_cmd = [bench_python, "-m", "doppio.frappe_lint.lsp.server"]
    client = LspClient(server_cmd)
    failures = []
    tmpdir = tempfile.mkdtemp(prefix="frappe_lint_smoke_")

    try:
        init = client.request("initialize", {
            "processId": os.getpid(),
            "rootUri": None,
            "capabilities": {},
        })
        assert "result" in init, f"initialize failed: {init}"
        client.notify("initialized", {})
        print("[ok] initialize handshake")

        # --- 1. a file with a real, known bug: FRP-SCH001 (unknown DocType) ---
        bad_path = os.path.join(tmpdir, "_smoke_bad.py")
        bad_src = 'import frappe\n\ndef leak():\n    return frappe.get_all("Definitely_Not_Real")\n'
        with open(bad_path, "w") as f:
            f.write(bad_src)
        uri = _uri(bad_path)
        before = client.notification_count()
        client.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": "python", "version": 1, "text": bad_src},
        })
        diags = client.wait_for_diagnostics(uri, after=before)
        sch001 = [d for d in diags if d.get("code") == "FRP-SCH001"]
        if sch001:
            print(f"[ok] didOpen -> FRP-SCH001 diagnostic received: {sch001[0]['message'][:70]}")
        else:
            failures.append(f"didOpen: expected FRP-SCH001, got {[d.get('code') for d in diags]}")

        # --- 2. edit it to remove the offending call, confirm the debounced
        # re-lint clears it. Deliberately NOT swapping in another get_all()
        # call: with no frappe_lint.toml anywhere above this tempdir, the
        # schema is an empty SchemaIndex, under which EVERY doctype name
        # looks unknown -- a real DocType would still (correctly, given an
        # empty schema) trigger SCH001, which would make this a broken test
        # of the harness, not a signal about the server.
        good_src = 'import frappe\n\ndef ok():\n    return 1 + 1\n'
        before = client.notification_count()
        client.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"text": good_src}],
        })
        diags2 = client.wait_for_diagnostics(uri, after=before)
        sch001_after = [d for d in diags2 if d.get("code") == "FRP-SCH001"]
        if not sch001_after:
            print("[ok] didChange (debounced) -> FRP-SCH001 cleared after fixing the code")
        else:
            failures.append(f"didChange: FRP-SCH001 should have cleared, still present: {sch001_after}")

        # --- 3. transiently invalid syntax mid-edit -- must not crash the server,
        # and should keep serving the last-good (good_src, zero findings) diagnostics
        broken_src = good_src + "def unterminated(\n"
        before = client.notification_count()
        client.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": 3},
            "contentChanges": [{"text": broken_src}],
        })
        try:
            diags3 = client.wait_for_diagnostics(uri, after=before, timeout=2.0)
            still_clean = not diags3
        except TimeoutError:
            still_clean = None  # no new publish at all is also acceptable here
        if client.proc.poll() is None:
            label = "clean" if still_clean else ("no new publish" if still_clean is None else "unexpected findings")
            print(f"[ok] didChange with a SyntaxError did not crash the server ({label})")
        else:
            failures.append("server process died on invalid syntax")

        # --- 4. baseline respecting: freeze the SCH001 finding, confirm it's suppressed ---
        with open(bad_path, "w") as f:
            f.write(bad_src)
        toml_path = os.path.join(tmpdir, "frappe_lint.toml")
        baseline_path = os.path.join(tmpdir, ".frappe_lint_baseline.json")
        with open(toml_path, "w") as f:
            f.write("[rules]\n")
        # key format is "RULE:<path relative to the baseline's directory>:line"
        key = "FRP-SCH001:_smoke_bad.py:4"
        with open(baseline_path, "w") as f:
            json.dump({"keys": [key]}, f)

        before = client.notification_count()
        client.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": "python", "version": 4, "text": bad_src},
        })
        diags4 = client.wait_for_diagnostics(uri, after=before)
        sch001_baselined = [d for d in diags4 if d.get("code") == "FRP-SCH001"]
        if not sch001_baselined:
            print("[ok] baseline respected -- pre-existing FRP-SCH001 finding suppressed")
        else:
            failures.append(f"baseline: FRP-SCH001 should be suppressed, still shown: {sch001_baselined}")

    finally:
        client.shutdown()
        shutil.rmtree(tmpdir, ignore_errors=True)
        if client._stderr_lines:
            print("\n--- server stderr (last 20 lines) ---")
            for line in client._stderr_lines[-20:]:
                print(" ", line)

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print("  -", f)
        return 1
    print("all LSP smoke checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())

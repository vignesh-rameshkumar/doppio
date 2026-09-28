"""
Inline suppression: `# frappe-lint: ignore[FRP-XXX] reason text`.

The reason is mandatory -- an ignore with no justification is itself a
finding (FRP-META001), because an unexplained suppression is invisible
debt: nobody reviewing the diff later can tell if it's still valid.
"""
from __future__ import annotations

import re

from doppio.frappe_lint.engine import Diagnostic

_PATTERN = re.compile(r"#\s*frappe-lint:\s*ignore\[([A-Z0-9\-]+)\]\s*(.*)")


def apply_suppressions(diagnostics: list[Diagnostic], lines_by_file: dict[str, list[str]]) -> list[Diagnostic]:
    out = []
    for d in diagnostics:
        lines = lines_by_file.get(d.file, [])
        line_text = lines[d.line - 1] if 0 < d.line <= len(lines) else ""
        m = _PATTERN.search(line_text)
        if m and m.group(1) == d.rule_id:
            reason = m.group(2).strip()
            if not reason:
                out.append(Diagnostic(
                    rule_id="FRP-META001",
                    message=f"suppression of {d.rule_id} has no reason -- "
                            f"add '# frappe-lint: ignore[{d.rule_id}] because ...'",
                    file=d.file, line=d.line, severity="warn", origin="meta",
                ))
            continue
        out.append(d)
    return out

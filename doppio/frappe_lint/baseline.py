"""
Baseline: freeze today's existing findings so CI fails only on genuinely
NEW violations, not the debt that already exists in the target app. Burn
the baseline down deliberately over time instead of turning the tool on
unbaselined and having the team disable it in week one.

Keys are `rule_id:<path relative to the baseline file's directory>:line`.
The baseline file lives at the target app's repo root and is committed
there, so it has to mean the same thing on every machine: an earlier
version keyed on the path exactly as the scan saw it, which for
`bench lint` is absolute (/home/<you>/<bench>/apps/<app>/...) -- a
teammate with a different bench path, or a CI checkout that passes a
relative path, would match none of it and see the entire backlog as new.
Anchoring on the baseline file's own directory makes the key identical
whether the scan was started as `bench lint core`, `check core` from the
app root in CI, or an editor handing the LSP an absolute file path.

Remaining caveat: the line number still drifts if code above a finding
is added or removed. A hardened version would hash a normalized snippet
of the surrounding statement instead of the raw line number.
"""
from __future__ import annotations

import json
import os

from doppio.frappe_lint.engine import Diagnostic


def portable_key(d: Diagnostic, baseline_path: str) -> str:
    root = os.path.dirname(os.path.abspath(baseline_path))
    rel = os.path.relpath(os.path.abspath(d.file), root).replace(os.sep, "/")
    return f"{d.rule_id}:{rel}:{d.line}"


def load_baseline(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data.get("keys", []))


def save_baseline(path: str, diagnostics: list[Diagnostic]) -> None:
    data = {"keys": sorted({portable_key(d, path) for d in diagnostics})}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def split_baselined(diagnostics: list[Diagnostic], baseline_keys: set[str], baseline_path: str):
    """Returns (new, baselined)."""
    new, baselined = [], []
    for d in diagnostics:
        (baselined if portable_key(d, baseline_path) in baseline_keys else new).append(d)
    return new, baselined

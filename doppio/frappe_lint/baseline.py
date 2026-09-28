"""
Baseline: freeze today's existing findings so CI fails only on genuinely
NEW violations, not the debt that already exists in the target app. Burn
the baseline down deliberately over time instead of turning the tool on
unbaselined and having the team disable it in week one.

Prototype caveat: keys are rule_id:file:line, which drifts if the file is
reformatted or lines shift above the finding. A hardened version should
hash a normalized snippet of the surrounding statement instead of the raw
line number -- noted here rather than silently shipped as if it were robust.
"""
from __future__ import annotations

import json
import os

from doppio.frappe_lint.engine import Diagnostic


def load_baseline(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data.get("keys", []))


def save_baseline(path: str, diagnostics: list[Diagnostic]) -> None:
    data = {"keys": sorted({d.key() for d in diagnostics})}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def split_baselined(diagnostics: list[Diagnostic], baseline_keys: set[str]):
    """Returns (new, baselined)."""
    new, baselined = [], []
    for d in diagnostics:
        (baselined if d.key() in baseline_keys else new).append(d)
    return new, baselined

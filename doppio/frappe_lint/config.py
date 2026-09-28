"""
Rule lifecycle: turning a rule off, downgrading it, or scoping it to a path
is a config edit, never a code change. Precedence, lowest to highest:
  rule's own default_severity
    -> frappe_lint.toml [rules] entry
      -> that entry's path-scoped override
        -> inline `# frappe-lint: ignore[ID] reason` (handled in suppressions.py)

Uses `tomli` rather than the `toml` package: this ships inside a Frappe app
that has to run on whatever Python version the bench happens to be on, and
`tomli` is the same parser Python 3.11+ ships as stdlib `tomllib` -- so this
becomes a straight `import tomllib` swap whenever the bench's minimum
Python version moves past 3.11, with zero format-compatibility risk.
"""
from __future__ import annotations

import os

import tomli

DEFAULT_CONFIG: dict = {
    "rules": {},
    "baseline": {"file": ".frappe_lint_baseline.json", "fail_on": "new_only"},
}


class LintConfig:
    def __init__(self, data: dict):
        self.rules_cfg = data.get("rules", {})
        self.baseline_file = data.get("baseline", {}).get("file", ".frappe_lint_baseline.json")
        self.fail_on = data.get("baseline", {}).get("fail_on", "new_only")

    @classmethod
    def load(cls, path: str | None) -> "LintConfig":
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                return cls(tomli.load(fh))
        return cls(DEFAULT_CONFIG)

    def effective_severity(self, rule_id: str, default_severity: str, file_path: str) -> str | None:
        """Returns None if the rule is suppressed entirely for this file."""
        entry = self.rules_cfg.get(rule_id)
        if entry is None:
            return default_severity
        if isinstance(entry, str):
            return None if entry == "off" else entry
        if isinstance(entry, dict):
            paths = entry.get("paths")
            norm = file_path.replace("\\", "/")
            if paths and not any(p.strip("*") in norm for p in paths):
                return default_severity  # override doesn't apply to this path
            sev = entry.get("severity", default_severity)
            return None if sev == "off" else sev
        return default_severity

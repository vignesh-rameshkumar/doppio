"""
Builds a DocType -> fieldnames index from every doctype/*.json across all
installed apps in a bench, so rules can resolve "is this DocType real?" and
"does it actually have this field?" without a running Frappe site.
"""
from __future__ import annotations

import json
import glob
import os
from dataclasses import dataclass, field

# Fields every Frappe DocType carries even if not declared in its own JSON.
IMPLICIT_FIELDS = {
    "name", "owner", "creation", "modified", "modified_by", "docstatus",
    "idx", "parent", "parenttype", "parentfield",
    "_user_tags", "_comments", "_assign", "_liked_by",
}


@dataclass
class DocTypeInfo:
    name: str
    fields: set = field(default_factory=set)
    app: str = ""
    json_path: str = ""
    is_child_table: bool = False


class SchemaIndex:
    """DocType name -> DocTypeInfo, built once and reused across a lint run."""

    def __init__(self):
        self.doctypes: dict[str, DocTypeInfo] = {}

    def __contains__(self, name: str) -> bool:
        return name in self.doctypes

    def __getitem__(self, name: str) -> DocTypeInfo:
        return self.doctypes[name]

    def get(self, name: str) -> DocTypeInfo | None:
        return self.doctypes.get(name)

    def has_field(self, doctype: str, fieldname: str) -> bool:
        info = self.doctypes.get(doctype)
        if info is None:
            return True  # unknown doctype is SCH001's problem, not SCH002's
        base = fieldname.split(".")[0].strip()
        if not base or base.startswith("`") or base == "*" or "(" in base:
            # backtick-quoted raw SQL, "*", and SQL expressions like
            # "count(name) as total" aren't real fieldnames -- can't resolve
            # them against the schema, so don't flag them as unknown.
            return True
        return base in info.fields or base in IMPLICIT_FIELDS

    def to_json(self, path: str) -> None:
        """Serialize the index so it can be committed and reused where the
        full bench isn't checked out -- e.g. a CI runner that only clones
        one app's repo and has no sibling apps to walk."""
        data = {
            name: {"fields": sorted(info.fields), "app": info.app, "is_child_table": info.is_child_table}
            for name, info in self.doctypes.items()
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")

    @classmethod
    def load_cache(cls, path: str) -> "SchemaIndex":
        idx = cls()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        for name, info in data.items():
            idx.doctypes[name] = DocTypeInfo(
                name=name, fields=set(info.get("fields", [])),
                app=info.get("app", ""), json_path="<cache>",
                is_child_table=bool(info.get("is_child_table")),
            )
        return idx

    @classmethod
    def build(cls, apps_root: str) -> "SchemaIndex":
        idx = cls()
        pattern = os.path.join(apps_root, "*", "**", "doctype", "*", "*.json")
        for path in glob.glob(pattern, recursive=True):
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict) or data.get("doctype") != "DocType":
                continue
            name = data.get("name")
            if not name:
                continue
            fieldnames = {
                f.get("fieldname")
                for f in data.get("fields", [])
                if isinstance(f, dict) and f.get("fieldname")
            }
            rel = os.path.relpath(path, apps_root)
            app = rel.split(os.sep)[0]
            idx.doctypes[name] = DocTypeInfo(
                name=name,
                fields=fieldnames,
                app=app,
                json_path=path,
                is_child_table=bool(data.get("istable")),
            )
        return idx

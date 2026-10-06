"""
frappe-lint Language Server.

Architecture, and the numbers that shaped it (measured against the
`core` app in this session before writing this file -- and re-measured,
with a correction, when a later question asked why the schema is cached
at all rather than always scanned live):

  SchemaIndex.build(whole bench)   ~0.9s   -- NEVER on a keystroke, but
                                               fine once per session on
                                               save/first-open: live-built
                                               from the real bench
                                               whenever apps_root is
                                               reliable (frappe
                                               importable), ignoring any
                                               .frappe_lint_schema_cache
                                               .json even if one exists,
                                               so this session is never
                                               working from a stale
                                               snapshot. Falls back to
                                               the cache file only when
                                               there's no reliable bench
                                               under this process at all
                                               -- an earlier "~9s, so it
                                               must be cached" framing
                                               overstated the speed
                                               argument (that number was
                                               a cold-filesystem-cache
                                               outlier); the real reason
                                               the cache file exists is
                                               portability -- CI/a solo
                                               checkout that doesn't have
                                               the other apps' DocType
                                               JSON on disk at all, not
                                               performance.
  ProjectIndex.build(one app)      ~0.64s  -- fine on save, not on every
                                               keystroke. Cached; rebuilt
                                               only on textDocument/didSave.
  full 19-rule pass, one file       ~4ms   -- this is the only thing that
                                               runs on every debounced
                                               keystroke, reusing the
                                               cached schema+project.

That's the whole design: expensive whole-bench/whole-app state is cached
IN MEMORY per session and only ever rebuilt on an explicit trigger (save,
or the frappe-lint.reloadSchema command); the per-keystroke path only
ever touches the one file being edited. Whether that in-memory state
came from a live scan or a cache file is a separate question from
whether it's rebuilt on every keystroke -- it never is, either way.

Other decisions carried over from the CLI, deliberately kept identical
rather than reimplemented:
  - Baseline-respecting: a file's pre-existing (baselined) findings don't
    light up on open -- only genuinely new ones do. Same reasoning as
    the CI baseline: showing 400 red squiggles on file-open is how a
    team disables the extension, not how it gets adopted.
  - Config resolution is nearest-ancestor frappe_lint.toml lookup, since
    an editor only ever hands us a file path, never an app name the way
    `bench lint <app>` gets one.
  - Tier-A YAML rules are re-read from rules.d/ on every lint pass rather
    than file-watched -- at 5 small files this is sub-millisecond, so a
    saved rule edit takes effect on the very next keystroke with no
    watcher, no restart, and no added dependency.
  - Every rule runs inside its own try/except -- one rule's bug must not
    blank out diagnostics for the other 18.

Launch: `bench lint-lsp` (stdio transport) -- see doppio/commands/frappe_lint.py.
"""
from __future__ import annotations

import ast
import asyncio
import os

from lsprotocol import types
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from doppio.frappe_lint.baseline import load_baseline, portable_key
from doppio.frappe_lint.cli import get_bench_apps_root
from doppio.frappe_lint.config import LintConfig
from doppio.frappe_lint.engine import ProjectIndex, RuleContext, registered_rules
from doppio.frappe_lint.schema import SchemaIndex
from doppio.frappe_lint.suppressions import apply_suppressions
from doppio.frappe_lint.yaml_engine import load_yaml_rules, run_yaml_rules
import doppio.frappe_lint.rules  # noqa: F401  (import registers all Tier-B rules)

DEBOUNCE_SECONDS = 0.3
_HERE = os.path.dirname(os.path.abspath(__file__))
_RULES_DIR = os.path.join(os.path.dirname(_HERE), "rules.d")

_SEVERITY_MAP = {
    "error": types.DiagnosticSeverity.Error,
    "warn": types.DiagnosticSeverity.Warning,
    "info": types.DiagnosticSeverity.Information,
}

# Full-document sync, not pygls's default Incremental: every handler here
# reads doc.source as the complete current text (never applies a diff
# itself), so there's no reason to take on incremental-patch complexity.
server = LanguageServer("frappe-lint", "0.1.0",
                         text_document_sync_kind=types.TextDocumentSyncKind.Full)

# The DocType schema is bench-wide -- there's exactly one, regardless of
# which app's file triggered the lookup -- so it's a single session-wide
# value, not something keyed per app_root the way ProjectIndex is (each
# app genuinely has its own project state; the bench has one schema).
_schema_singleton: SchemaIndex | None = None
_warned_no_schema = False

# app_root -> cached ProjectIndex (this one IS legitimately per-app).
_project_by_root: dict[str, ProjectIndex] = {}

# uri -> (source, tree) from the last successfully-parsed version of that
# file, used while the buffer is transiently unparseable mid-edit so
# diagnostics don't flash to nothing on every incomplete keystroke.
_last_good: dict[str, tuple[str, ast.AST]] = {}

# uri -> monotonically increasing generation counter, for the async
# debounce pattern below (cancel-by-comparison instead of literal task
# cancellation, since pygls dispatches one coroutine per notification).
_generation: dict[str, int] = {}


def _find_nearest(fs_path: str, marker_filename: str) -> str | None:
    """Walk up from a file path looking for a marker file -- the same
    "nearest config wins" convention eslint/ruff use, since an editor
    only ever gives us a file path, never an app name."""
    current = os.path.dirname(os.path.abspath(fs_path))
    for _ in range(30):  # bounded: never walk past a sane repo depth
        if os.path.exists(os.path.join(current, marker_filename)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent
    return None


def _find_app_root(fs_path: str) -> str | None:
    """Nearest frappe_lint.toml -- used for CONFIG and BASELINE, which are
    genuinely per-app. Deliberately NOT used to decide whether a schema is
    available: an earlier version gated _get_schema behind this, which
    meant a file in any app with no frappe_lint.toml yet (every app, in
    this bench, as of when this bug was found -- none has one committed)
    got an EMPTY schema, and every real DocType reference in it looked
    unknown. Schema only depends on whether a real bench exists at all,
    which _get_schema checks independently below."""
    return _find_nearest(fs_path, "frappe_lint.toml")


def _get_schema(ls: LanguageServer, fs_path: str) -> SchemaIndex:
    """Bench-wide and session-wide: built (or loaded) once, reused for
    every file in every app for the rest of the session, regardless of
    whether that app has a frappe_lint.toml. Live scan wins whenever a
    real bench is available -- same reasoning as cli.py's _load_schema:
    measured well under a second on a warm local filesystem (an earlier
    "~9s" estimate here was a cold-cache outlier during development, not
    a stable cost of the approach), and always fresh.

    The cache file is reached only when this process doesn't have a
    reliable bench under it at all (frappe isn't importable) -- e.g. an
    editor whose configured interpreter isn't the bench's own venv. In
    that narrower case there's no apps_root to derive a single bench-wide
    answer from, so the nearest .frappe_lint_schema_cache.json to the
    file actually being linted is used instead."""
    global _schema_singleton, _warned_no_schema
    if _schema_singleton is not None:
        return _schema_singleton

    apps_root = get_bench_apps_root()
    if apps_root:
        _schema_singleton = SchemaIndex.build(apps_root)
        return _schema_singleton

    cache_root = _find_nearest(fs_path, ".frappe_lint_schema_cache.json")
    if cache_root:
        _schema_singleton = SchemaIndex.load_cache(
            os.path.join(cache_root, ".frappe_lint_schema_cache.json"))
        return _schema_singleton

    if not _warned_no_schema:
        _warned_no_schema = True
        ls.window_show_message(types.ShowMessageParams(
            type=types.MessageType.Warning,
            message=("frappe-lint: no bench available (frappe isn't importable from this "
                     "process) and no .frappe_lint_schema_cache.json found above any open "
                     "file -- schema-aware rules (unknown DocType/field checks) are disabled "
                     "for this session. Run 'bench lint-schema <app>' and commit the cache, "
                     "or point this editor's Python at the bench's own env/bin/python3."),
        ))
    _schema_singleton = SchemaIndex()  # empty: schema-dependent rules will just find nothing to flag
    return _schema_singleton


def _find_project_root(fs_path: str) -> str | None:
    """The directory to build the cross-file ProjectIndex from -- the same
    apps/<app>/<app> package directory `bench lint <app>` scans, so the
    editor and the CLI agree on what "the project" is.

    Derived from the file's position under the bench, NOT from finding a
    frappe_lint.toml. An earlier version only built a project index when a
    toml was found; none of the apps had one, so every cross-file rule
    (CACHE001/CACHE006/SCH006) silently never ran in the editor -- 24
    CACHE001 findings the CLI reported on one file showed as zero in VS
    Code. Falls back to the toml's directory only when this process has
    no bench to derive a path from."""
    apps_root = get_bench_apps_root()
    if apps_root:
        rel = os.path.relpath(os.path.abspath(fs_path), apps_root)
        if not rel.startswith(".."):
            app = rel.split(os.sep)[0]
            package_dir = os.path.join(apps_root, app, app)
            if os.path.isdir(package_dir):
                return package_dir
    return _find_app_root(fs_path)


def _get_project(project_root: str, rebuild: bool = False) -> ProjectIndex:
    if rebuild or project_root not in _project_by_root:
        _project_by_root[project_root] = ProjectIndex.build(project_root)
    return _project_by_root[project_root]


def _to_lsp_diagnostics(diags, source: str) -> list[types.Diagnostic]:
    """Three-tier fallback, from most to least precise, depending on what
    the originating Diagnostic actually captured:
      1. Full span (col + end_line + end_col) -- e.g. an unknown DocType
         string, an unbounded get_all() call -- squiggles exactly that
         token/expression, nothing more.
      2. col only, no end -- e.g. a bare `except:` -- squiggles from that
         column to the end of ITS OWN line (never the node's own AST
         "end", which for a compound statement like an except block would
         span the whole body).
      3. Neither -- squiggles the whole line, same as every diagnostic did
         before this was added. Never worse than the old behavior, only
         better when position info is available (which is most rules)."""
    lines = source.splitlines()
    out = []
    for d in diags:
        line0 = max(0, d.line - 1)
        line_text_len = len(lines[line0]) if line0 < len(lines) else 0

        if d.col is not None and d.end_line is not None and d.end_col is not None:
            start_char, end_line0, end_char = d.col, max(0, d.end_line - 1), d.end_col
        elif d.col is not None:
            start_char, end_line0, end_char = d.col, line0, line_text_len
        else:
            start_char, end_line0, end_char = 0, line0, line_text_len

        out.append(types.Diagnostic(
            range=types.Range(
                start=types.Position(line=line0, character=start_char),
                end=types.Position(line=end_line0, character=end_char),
            ),
            message=f"[{d.rule_id}] {d.message}",
            severity=_SEVERITY_MAP.get(d.severity, types.DiagnosticSeverity.Warning),
            source="frappe-lint",
            code=d.rule_id,
        ))
    return out


def _lint_and_publish(ls: LanguageServer, uri: str, force_project_rebuild: bool = False) -> None:
    doc = ls.workspace.get_text_document(uri)
    source = doc.source
    fs_path = to_fs_path(uri) or uri

    try:
        tree = ast.parse(source)
        _last_good[uri] = (source, tree)
    except SyntaxError:
        cached = _last_good.get(uri)
        if cached is None:
            ls.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))
            return
        source, tree = cached  # lint the last version that actually parsed

    app_root = _find_app_root(fs_path)  # per-app config + baseline only; optional
    config = LintConfig.load(os.path.join(app_root, "frappe_lint.toml") if app_root else None)
    schema = _get_schema(ls, fs_path)  # bench-wide: needs no app_root
    project_root = _find_project_root(fs_path)  # derived from bench layout: needs no toml either
    project = _get_project(project_root, rebuild=force_project_rebuild) if project_root else None

    ctx = RuleContext(path=fs_path, source=source, tree=tree, schema=schema, project_index=project)

    all_diags = []
    for cls in registered_rules():
        try:
            all_diags.extend(cls(ctx).run())
        except Exception as exc:  # one broken rule must not blank every other rule's diagnostics
            ls.window_log_message(types.LogMessageParams(
                type=types.MessageType.Error,
                message=f"frappe-lint: rule {getattr(cls, 'rule_id', cls.__name__)} crashed on "
                        f"{fs_path}: {exc!r}",
            ))

    try:
        yaml_rules = load_yaml_rules(_RULES_DIR)  # re-read every pass -- true hot reload, <1ms
        all_diags.extend(run_yaml_rules(yaml_rules, fs_path, tree))
    except Exception as exc:
        ls.window_log_message(types.LogMessageParams(
            type=types.MessageType.Error,
            message=f"frappe-lint: YAML rule evaluation failed: {exc!r}",
        ))

    resolved = []
    for d in all_diags:
        sev = config.effective_severity(d.rule_id, d.severity, d.file)
        if sev is None:
            continue
        d.severity = sev
        resolved.append(d)
    resolved = apply_suppressions(resolved, {fs_path: source.splitlines()})

    if app_root:
        baseline_path = os.path.join(app_root, ".frappe_lint_baseline.json")
        baseline_keys = load_baseline(baseline_path)
        resolved = [d for d in resolved if portable_key(d, baseline_path) not in baseline_keys]

    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=_to_lsp_diagnostics(resolved, source)))


async def _debounced_lint(ls: LanguageServer, uri: str) -> None:
    gen = _generation.get(uri, 0) + 1
    _generation[uri] = gen
    await asyncio.sleep(DEBOUNCE_SECONDS)
    if _generation.get(uri) != gen:
        return  # a newer edit superseded this one while we were sleeping
    _lint_and_publish(ls, uri)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: LanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    _lint_and_publish(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(ls: LanguageServer, params: types.DidChangeTextDocumentParams) -> None:
    await _debounced_lint(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: LanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    uri = params.text_document.uri
    _generation[uri] = _generation.get(uri, 0) + 1  # invalidate any in-flight debounce
    _lint_and_publish(ls, uri, force_project_rebuild=True)


@server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
def did_close(ls: LanguageServer, params: types.DidCloseTextDocumentParams) -> None:
    uri = params.text_document.uri
    _last_good.pop(uri, None)
    _generation.pop(uri, None)
    ls.text_document_publish_diagnostics(types.PublishDiagnosticsParams(uri=uri, diagnostics=[]))


@server.command("frappe-lint.reloadSchema")
def reload_schema(ls: LanguageServer, *args) -> None:
    """Drop the cached SchemaIndex and every cached ProjectIndex so the
    next lint pass rebuilds them -- for when a DocType changed elsewhere
    in the bench, or an app's code changed enough to warrant a fresh
    ProjectIndex sooner than the next save."""
    global _schema_singleton, _warned_no_schema
    _schema_singleton = None
    _warned_no_schema = False
    _project_by_root.clear()
    ls.window_show_message(types.ShowMessageParams(
        type=types.MessageType.Info, message="frappe-lint: schema and project caches cleared."))


def main() -> None:
    server.start_io()


if __name__ == "__main__":
    main()

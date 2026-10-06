"""
Regression test for the VS Code extension packaging.

The bug this guards against: the first version of vscode_install.py ran
`npx @vscode/vsce package`, which crashed on a teammate's Node 18 bench
(`util.styleText is not a function`) because npx pulled a vsce newer than
that Node could run -- and pinning an older vsce just failed differently.
Packaging is now done in Python, with no dependence on the Node version.

Two checks, neither touching a real VS Code:
  1. build_vsix() produces a structurally valid .vsix: well-formed manifest
     whose identity matches package.json, .vscodeignore honored, lockfile
     excluded.
  2. The full install() flow runs to completion with fake `code`/`npm`
     binaries on a PATH that contains NO `npx` -- so if anything ever
     starts shelling out to npx again, this fails.

Run via `bench lint-selftest`, or: python3 -m doppio.frappe_lint.selftest_vsix
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import zipfile
from xml.etree import ElementTree

from doppio.frappe_lint.vscode_install import build_vsix, install

_NS = {"v": "http://schemas.microsoft.com/developer/vsx-schema/2011"}


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _check_structure(failures: list, workdir: str) -> None:
    ext = os.path.join(workdir, "ext")
    _write(os.path.join(ext, "package.json"), json.dumps({
        "name": "demo-ext", "displayName": "Demo & <Ext>", "publisher": "acme",
        "version": "1.2.3", "description": 'Uses "quotes" & <angle> brackets',
        "engines": {"vscode": "^1.75.0"}, "categories": ["Linters"], "main": "./extension.js",
    }))
    _write(os.path.join(ext, "extension.js"), "exports.activate = () => {};\n")
    _write(os.path.join(ext, "package-lock.json"), "{}")
    _write(os.path.join(ext, ".vscodeignore"), "demo_workspace/**\n.vscodeignore\n")
    _write(os.path.join(ext, "demo_workspace", "sample.py"), "x = 1\n")
    _write(os.path.join(ext, "node_modules", "dep", "index.js"), "module.exports = 1;\n")
    _write(os.path.join(ext, "node_modules", ".package-lock.json"), "{}")

    out = os.path.join(workdir, "out.vsix")
    build_vsix(ext, out)
    names = set(zipfile.ZipFile(out).namelist())

    for required in ("[Content_Types].xml", "extension.vsixmanifest", "extension/package.json",
                     "extension/extension.js", "extension/node_modules/dep/index.js"):
        if required not in names:
            failures.append(f"vsix is missing {required}")
    for unwanted in ("extension/package-lock.json", "extension/.vscodeignore",
                     "extension/demo_workspace/sample.py", "extension/node_modules/.package-lock.json"):
        if unwanted in names:
            failures.append(f"vsix should not contain {unwanted}")

    try:
        manifest = ElementTree.fromstring(zipfile.ZipFile(out).read("extension.vsixmanifest"))
        ident = manifest.find("v:Metadata/v:Identity", _NS)
        got = (ident.get("Publisher"), ident.get("Id"), ident.get("Version"))
        if got != ("acme", "demo-ext", "1.2.3"):
            failures.append(f"manifest identity {got} does not match package.json")
        desc = manifest.find("v:Metadata/v:Description", _NS).text
        if desc != 'Uses "quotes" & <angle> brackets':
            failures.append(f"manifest description was not escaped/round-tripped correctly: {desc!r}")
    except ElementTree.ParseError as exc:
        failures.append(f"extension.vsixmanifest is not well-formed XML: {exc}")


def _check_install_flow(failures: list, workdir: str) -> None:
    fakebin = os.path.join(workdir, "fakebin")
    captured = os.path.join(workdir, "captured.vsix")
    log = os.path.join(workdir, "code_args.txt")
    os.makedirs(fakebin)
    # fake `code`: record its args, keep a copy of the .vsix it was handed
    # (install() deletes its temp dir afterwards, so copy it out now).
    # Absolute /bin/cp: PATH is deliberately restricted to this directory.
    _write(os.path.join(fakebin, "code"),
           f'#!/bin/sh\necho "$@" > "{log}"\n/bin/cp "$2" "{captured}"\nexit 0\n')
    _write(os.path.join(fakebin, "npm"), "#!/bin/sh\nexit 0\n")  # never needs to create anything
    for name in ("code", "npm"):
        p = os.path.join(fakebin, name)
        os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)

    messages: list[str] = []
    old_path = os.environ.get("PATH", "")
    os.environ["PATH"] = fakebin  # deliberately no npx, no real node
    try:
        ok = install(echo=messages.append)
    finally:
        os.environ["PATH"] = old_path

    if not ok:
        failures.append(f"install() failed with fake code/npm and no npx on PATH -- packaging must not "
                        f"depend on npx/vsce any more. Messages: {messages}")
        return
    if not os.path.exists(log):
        failures.append("install() returned True but never invoked `code`")
        return
    args = open(log).read().split()
    if args[:1] != ["--install-extension"] or not args[1].endswith(".vsix") or "--force" not in args:
        failures.append(f"unexpected `code` arguments: {args}")
    if not zipfile.is_zipfile(captured) or "extension.vsixmanifest" not in zipfile.ZipFile(captured).namelist():
        failures.append("the file handed to `code --install-extension` is not a valid .vsix")


def main() -> int:
    failures: list[str] = []
    workdir = tempfile.mkdtemp(prefix="frappe_lint_vsix_test_")
    try:
        _check_structure(failures, workdir)
        _check_install_flow(failures, workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if failures:
        print("vsix packaging: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("[ok] vsix packaging: valid manifest + contents, .vscodeignore honored, and the full "
          "install() flow works with no npx/vsce on PATH")
    return 0


if __name__ == "__main__":
    sys.exit(main())

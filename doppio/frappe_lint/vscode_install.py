"""
Packages the VS Code client shim into a .vsix and installs it into the
user's actual VS Code (not a throwaway Extension Development Host) via
`code --install-extension`. Wired into doppio's after_install hook so
`bench install-app doppio` sets this up with no separate step -- and also
exposed as `bench lint-vscode-install` to run by hand (e.g. VS Code
wasn't installed yet when doppio was, or to reinstall after an update).

Safe to call in any context, including a non-interactive CI/server site
install with no VS Code and no desktop at all: every step is defensive,
missing prerequisites are logged and skipped, never raised -- this must
never be able to break `bench install-app doppio` itself.

Why the .vsix is built here in Python rather than with `npx @vscode/vsce`:
the first version shelled out to vsce and failed on a teammate's bench
(Node 18) with `util.styleText is not a function`. Unpinned, `npx` pulls
whatever vsce is current -- which had already moved from 3.x (Node >= 20)
to 4.0 (Node >= 22) -- and pinning an older vsce didn't help either: 2.32
declares Node >= 16 but crashed on 18.20.2 with `File is not defined`, a
Node-20-only global in one of its dependencies. Any pin trades one Node
floor for another, and every bench has whatever Node Frappe wanted.
A .vsix is just a zip -- two small XML files plus an extension/ folder --
so building it directly removes the Node-version coupling, the npx
download, and the network call at install time. The only Node tool still
needed is `npm install`, to fetch the extension's one runtime dependency.
"""
from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from xml.sax.saxutils import escape

_EXT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "editors", "vscode")

# What vsce leaves out of a package regardless of .vscodeignore.
_ALWAYS_IGNORED = ("package-lock.json", "yarn.lock", "*.vsix",
                   "node_modules/.package-lock.json", "node_modules/.bin/**")

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension=".json" ContentType="application/json"/>'
    '<Default Extension=".vsixmanifest" ContentType="text/xml"/>'
    '<Default Extension=".js" ContentType="application/javascript"/>'
    '<Default Extension=".ts" ContentType="video/mp2t"/>'
    '<Default Extension=".sh" ContentType="application/x-sh"/>'
    '<Default Extension=".txt" ContentType="text/plain"/>'
    '<Default Extension=".cmd" ContentType="application/octet-stream"/>'
    '<Default Extension=".md" ContentType="text/markdown"/>'
    '<Default Extension=".bnf" ContentType="application/octet-stream"/>'
    '<Default Extension=".yml" ContentType="text/yaml"/>'
    '</Types>'
)


def _attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def _manifest_xml(pkg: dict) -> str:
    """Same shape vsce emits (compared against real vsce output before
    this replaced it)."""
    return f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="{_attr(pkg["name"])}" Version="{_attr(pkg["version"])}" Publisher="{_attr(pkg["publisher"])}" />
    <DisplayName>{escape(pkg.get("displayName", pkg["name"]))}</DisplayName>
    <Description xml:space="preserve">{escape(pkg.get("description", ""))}</Description>
    <Tags></Tags>
    <Categories>{escape(",".join(pkg.get("categories", [])))}</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="{_attr(pkg["engines"]["vscode"])}" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionDependencies" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionPack" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="workspace" />
      <Property Id="Microsoft.VisualStudio.Code.LocalizedLanguages" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.EnabledApiProposals" Value="" />
      <Property Id="Microsoft.VisualStudio.Code.ExecutesCode" Value="true" />
      <Property Id="Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown" Value="true" />
      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
  </Assets>
</PackageManifest>
'''


def _ignore_patterns(ext_dir: str) -> list[str]:
    patterns = list(_ALWAYS_IGNORED)
    path = os.path.join(ext_dir, ".vscodeignore")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            patterns += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    return patterns


def _is_ignored(rel: str, patterns: list[str]) -> bool:
    base = rel.rsplit("/", 1)[-1]
    for pat in patterns:
        if pat.endswith("/**"):
            if rel.startswith(pat[:-2]):
                return True
        elif fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(base, pat):
            return True
    return False


def build_vsix(ext_dir: str, out_path: str) -> int:
    """Zip ext_dir into a .vsix at out_path. Returns the number of files
    packaged under extension/. Honors .vscodeignore."""
    with open(os.path.join(ext_dir, "package.json"), encoding="utf-8") as fh:
        pkg = json.load(fh)
    patterns = _ignore_patterns(ext_dir)

    count = 0
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _CONTENT_TYPES)
        zf.writestr("extension.vsixmanifest", _manifest_xml(pkg))
        for dirpath, dirnames, filenames in os.walk(ext_dir):
            dirnames.sort()
            for fn in sorted(filenames):
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ext_dir).replace(os.sep, "/")
                if _is_ignored(rel, patterns):
                    continue
                zf.write(full, f"extension/{rel}")
                count += 1
    return count


def _tail(text: str, lines: int = 3) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def install(echo=print) -> bool:
    """Returns True if the extension was (re)installed, False if skipped
    or failed -- never raises."""
    code_bin = shutil.which("code")
    if not code_bin:
        echo("frappe-lint: no 'code' CLI found on PATH -- skipping VS Code extension install "
             "(expected on a server/CI install with no desktop; run 'bench lint-vscode-install' "
             "by hand later if VS Code is installed on this machine).")
        return False

    npm_bin = shutil.which("npm")
    if not npm_bin:
        echo("frappe-lint: no 'npm' found on PATH -- can't fetch the VS Code extension's "
             "dependency (needs Node.js). Skipping.")
        return False

    tmpdir = tempfile.mkdtemp(prefix="frappe_lint_vsix_")
    try:
        if not os.path.isdir(os.path.join(_EXT_DIR, "node_modules")):
            echo("frappe-lint: installing the VS Code extension's dependency...")
            subprocess.run([npm_bin, "install", "--omit=dev", "--no-audit", "--no-fund"],
                           cwd=_EXT_DIR, check=True, capture_output=True, text=True)

        vsix_path = os.path.join(tmpdir, "frappe-lint.vsix")
        echo("frappe-lint: packaging the VS Code extension...")
        build_vsix(_EXT_DIR, vsix_path)

        echo("frappe-lint: installing into VS Code...")
        subprocess.run([code_bin, "--install-extension", vsix_path, "--force"],
                       check=True, capture_output=True, text=True)

        echo("frappe-lint: VS Code extension installed. Reload any open VS Code window "
             "(command palette -> 'Developer: Reload Window') to activate it -- diagnostics "
             "then appear automatically on any Python file inside this bench, no settings needed.")
        return True
    except subprocess.CalledProcessError as e:
        cmd = os.path.basename(str(e.cmd[0])) if e.cmd else "command"
        echo(f"frappe-lint: VS Code extension install skipped -- `{cmd}` failed "
             f"(exit {e.returncode}): {_tail(e.stderr) or 'no output'}\n"
             f"Not fatal; the linter itself is unaffected. Run 'bench lint-vscode-install' to retry.")
        return False
    except Exception as e:
        echo(f"frappe-lint: VS Code extension install skipped -- unexpected error: {e!r}. "
             f"Not fatal; run 'bench lint-vscode-install' to retry.")
        return False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

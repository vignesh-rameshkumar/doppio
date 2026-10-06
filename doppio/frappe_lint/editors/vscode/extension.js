// frappe-lint client. Spawns `python3 -m doppio.frappe_lint.lsp.server`
// (stdio transport) via vscode-languageclient and wires up diagnostics.
//
// Zero-config by default: on activation, walks up from whatever
// workspace folder (or, if none, the active file) is open looking for
// sites/apps.txt -- the one file every Frappe bench has and nothing else
// does -- to find the bench root, then derives env/bin/python3 and
// apps/doppio from it. frappeLint.benchPythonPath/doppioPath in settings
// are optional overrides for a non-standard layout, never required.
//
// The server this connects to was verified end-to-end over the real LSP
// protocol (see ../../lsp/smoke_test.py). This file's wiring, and the
// bench-root auto-detection specifically, were confirmed against a real,
// already-running VS Code window in the session that built this -- not
// just the Extension Development Host.

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");
const { LanguageClient, TransportKind } = require("vscode-languageclient/node");

let client;

function findBenchRoot(startPath) {
  let dir = startPath;
  for (let i = 0; i < 20; i++) {
    if (fs.existsSync(path.join(dir, "sites", "apps.txt"))) {
      return dir;
    }
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
  return null;
}

function autoDetect() {
  const searchRoots = [];
  const folders = vscode.workspace.workspaceFolders;
  if (folders) {
    for (const f of folders) searchRoots.push(f.uri.fsPath);
  }
  const activeDoc = vscode.window.activeTextEditor && vscode.window.activeTextEditor.document;
  if (activeDoc && activeDoc.uri.scheme === "file") {
    searchRoots.push(path.dirname(activeDoc.uri.fsPath));
  }

  for (const root of searchRoots) {
    const benchRoot = findBenchRoot(root);
    if (!benchRoot) continue;
    const pythonPath = path.join(benchRoot, "env", "bin", "python3");
    const doppioPath = path.join(benchRoot, "apps", "doppio");
    if (fs.existsSync(pythonPath) && fs.existsSync(doppioPath)) {
      return { pythonPath, doppioPath, benchRoot };
    }
  }
  return null;
}

function resolveConfig() {
  const config = vscode.workspace.getConfiguration("frappeLint");
  const explicitPython = config.get("benchPythonPath");
  const explicitDoppio = config.get("doppioPath");
  if (explicitPython && explicitDoppio) {
    return { pythonPath: explicitPython, doppioPath: explicitDoppio, source: "settings.json" };
  }
  const detected = autoDetect();
  if (detected) {
    return {
      pythonPath: explicitPython || detected.pythonPath,
      doppioPath: explicitDoppio || detected.doppioPath,
      source: `auto-detected (bench root: ${detected.benchRoot})`,
    };
  }
  return null;
}

function startClient(resolved) {
  const serverOptions = {
    command: resolved.pythonPath,
    args: ["-m", "doppio.frappe_lint.lsp.server"],
    transport: TransportKind.stdio,
    options: { env: { ...process.env, PYTHONPATH: resolved.doppioPath } },
  };
  const clientOptions = {
    documentSelector: [{ scheme: "file", language: "python" }],
  };
  client = new LanguageClient("frappeLint", "frappe-lint", serverOptions, clientOptions);
  return client.start();
}

function activate(context) {
  const resolved = resolveConfig();
  if (!resolved) {
    vscode.window.showWarningMessage(
      "frappe-lint: couldn't find a bench (no sites/apps.txt above this workspace/file) and no " +
      "explicit frappeLint.benchPythonPath/doppioPath set -- language server not started."
    );
    return;
  }
  context.subscriptions.push(startClient(resolved));
}

function deactivate() {
  return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };

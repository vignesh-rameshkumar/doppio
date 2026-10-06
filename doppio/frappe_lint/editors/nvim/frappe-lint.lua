-- frappe-lint Neovim LSP client config -- no extension/plugin needed,
-- Neovim's built-in LSP client (vim.lsp, 0.8+) attaches to any stdio
-- server directly.
--
-- Copy this into your Neovim config (e.g. ~/.config/nvim/after/ftplugin/python.lua,
-- or source it from init.lua), and set BENCH_PATH to your bench's root.
--
-- Not GUI-tested in this session (no way to drive an interactive editor
-- from here) -- but the underlying server was verified end-to-end over
-- the real LSP protocol (see ../../lsp/smoke_test.py), and this config
-- is the standard, minimal vim.lsp.start() shape.

local bench_path = vim.fn.expand("$BENCH_PATH")
if bench_path == "$BENCH_PATH" or bench_path == "" then
	bench_path = "/home/vignesh/frappe14" -- adjust, or export BENCH_PATH in your shell
end

vim.lsp.start({
	name = "frappe-lint",
	cmd = { bench_path .. "/env/bin/python3", "-m", "doppio.frappe_lint.lsp.server" },
	cmd_env = {
		PYTHONPATH = bench_path .. "/apps/doppio",
	},
	root_dir = vim.fs.dirname(vim.fs.find({ "frappe_lint.toml", ".git" }, { upward = true })[1]),
})

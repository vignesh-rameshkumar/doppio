import json
import click
import subprocess

from pathlib import Path
from .boilerplates import *
from .utils import (
	create_file,
	add_build_command_to_package_json,
	add_routing_rule_to_hooks,
)


class SPAGenerator:
	def __init__(self, framework, spa_name, app, add_tailwindcss, typescript):
		"""Initialize a new SPAGenerator instance"""
		self.framework = framework
		self.app = app
		self.app_path = Path("../apps") / app
		self.spa_name = spa_name
		self.spa_path: Path = self.app_path / self.spa_name
		self.add_tailwindcss = add_tailwindcss
		self.use_typescript = typescript

		self.validate_spa_name()

	def validate_spa_name(self):
		if self.spa_name == self.app:
			click.echo("Dashboard name must not be same as app name", err=True, color=True)
			exit(1)

	def generate_spa(self):
		click.echo("Generating spa...")
		if self.framework == "vue":
			self.initialize_vue_vite_project()
			self.link_controller_files()
			self.setup_proxy_options()
			self.setup_vue_vite_config()
			self.setup_vue_router()
			self.create_vue_files()

		elif self.framework == "react":
			self.initialize_react_vite_project()
			self.setup_proxy_options()
			self.setup_react_vite_config()
			self.create_react_files()

		# Common to all frameworks
		add_build_command_to_package_json(self.app, self.spa_name)
		self.create_www_directory()
		self.add_csrf_to_html()

		if self.add_tailwindcss:
			self.setup_tailwindcss()

		add_routing_rule_to_hooks(self.app, self.spa_name)

		click.echo(f"Run: cd {self.spa_path.absolute().resolve()} && yarn dev")
		click.echo("to start the development server and visit: http://<site>:8080")

	def setup_tailwindcss(self):
		subprocess.run(
			[
				"npm",
				"install",
				"-D",
				"tailwindcss@latest",
				"postcss@latest",
				"autoprefixer@latest",
			],
			cwd=self.spa_path,
		)

		subprocess.run(["npx", "tailwindcss", "init", "-p"], cwd=self.spa_path)

		index_css_path: Path = self.spa_path / "src/index.css"

		INDEX_CSS_BOILERPLATE = """@tailwind base;
@tailwind components;
@tailwind utilities;
"""
		create_file(index_css_path, INDEX_CSS_BOILERPLATE)

		tailwind_config_path: Path = self.spa_path / "tailwind.config.js"
		if not tailwind_config_path.exists():
			tailwind_config_path = self.spa_path / "tailwind.config.ts"

		tailwind_config_path: Path = self.spa_path / "tailwind.config.js"
		tailwind_config = tailwind_config_path.read_text()
		tailwind_config = tailwind_config.replace(
			"content: [],", 'content: ["./src/**/*.{html,jsx,tsx,vue,js,ts}"],'
		)
		tailwind_config_path.write_text(tailwind_config)

	def create_vue_files(self):
		app_vue = self.spa_path / "src/App.vue"
		create_file(app_vue, APP_VUE_BOILERPLATE)

		views_dir: Path = self.spa_path / "src/views"
		if not views_dir.exists():
			views_dir.mkdir()

		home_vue = views_dir / "Home.vue"
		login_vue = views_dir / "Login.vue"

		create_file(home_vue, HOME_VUE_BOILERPLATE)
		create_file(login_vue, LOGIN_VUE_BOILERPLATE)

	def setup_vue_router(self):
		router_dir_path: Path = self.spa_path / "src/router"
		router_dir_path.mkdir()

		router_index_file = router_dir_path / "index.js"
		create_file(
			router_index_file, ROUTER_INDEX_BOILERPLATE.replace("{{name}}", self.spa_name)
		)

		auth_routes_file = router_dir_path / "auth.js"
		create_file(auth_routes_file, AUTH_ROUTES_BOILERPLATE)

	def initialize_vue_vite_project(self):
		print("Scafolding vue project...")
		if self.use_typescript:
			subprocess.run(
				["yarn", "create", "vite", self.spa_name, "--template", "vue-ts"], cwd=self.app_path
			)
		else:
			subprocess.run(
				["yarn", "create", "vite", self.spa_name, "--template", "vue"], cwd=self.app_path
			)

		print("Installing dependencies...")
		subprocess.run(
			["yarn", "add", "vue-router@^4", "socket.io-client@^4.5.1"], cwd=self.spa_path
		)

	def link_controller_files(self):
		print("Linking controller files...")
		main_js: Path = self.app_path / (
			f"{self.spa_name}/src/main.ts"
			if self.use_typescript
			else f"{self.spa_name}/src/main.js"
		)

		if main_js.exists():
			with main_js.open("w") as f:
				boilerplate = MAIN_JS_BOILERPLATE

				if self.add_tailwindcss:
					boilerplate = "import './index.css';\n" + boilerplate

				f.write(boilerplate)
		else:
			click.echo("src/main.js not found!")

	def setup_proxy_options(self):
		proxy_options_file: Path = self.spa_path / "proxyOptions.js"
		create_file(proxy_options_file, PROXY_OPTIONS_BOILERPLATE)

	def setup_vue_vite_config(self):
		vite_config_file: Path = self.spa_path / (
			"vite.config.ts" if self.use_typescript else "vite.config.js"
		)
		if not vite_config_file.exists():
			vite_config_file.touch()
		with vite_config_file.open("w") as f:
			boilerplate = VUE_VITE_CONFIG_BOILERPLATE.replace("{{app}}", self.app)
			boilerplate = boilerplate.replace("{{name}}", self.spa_name)
			f.write(boilerplate)

	def create_www_directory(self):
		www_dir_path: Path = self.app_path / f"{self.app}/www"
		if not www_dir_path.exists():
			www_dir_path.mkdir()

	def add_csrf_to_html(self):
		index_html_file_path = self.spa_path / "index.html"
		with index_html_file_path.open("r") as f:
			current_html = f.read()

		updated_html = current_html.replace(
			"</div>", "</div>\n\t\t<script>window.csrf_token = '{{ frappe.session.csrf_token }}';</script>"
		)

		with index_html_file_path.open("w") as f:
			f.write(updated_html)

	def initialize_react_vite_project(self):
		print("Scaffolding React project...")

		template = f"{self.framework}"
		if self.use_typescript:
			template += "-ts"

		# Step 1: Scaffold only (create-vite writes files but does NOT run yarn install)
		subprocess.run(
			["npx", "create-vite@6.1.0", self.spa_name, "--template", template],
			cwd=self.app_path,
			check=True
		)

		# Step 2: Patch package.json BEFORE yarn install to fix Node 18 incompatibility.
		# create-vite@6.1.0 react-ts template ships "typescript-eslint": "^8.x" which
		# pulls eslint-visitor-keys@5 requiring Node >=20. We replace it with the
		# split @typescript-eslint v7 packages that support Node >=18.
		if self.use_typescript:
			self._patch_react_ts_package_json()
			self._write_eslint_config_v7()

		# Step 3: Pin vite version in devDependencies
		pkg_json_path = self.spa_path / "package.json"
		with pkg_json_path.open("r") as f:
			pkg = json.load(f)
		pkg.setdefault("devDependencies", {})["vite"] = "6.1.0"
		with pkg_json_path.open("w") as f:
			json.dump(pkg, f, indent=2)

		# Step 4: Now run yarn install with the patched package.json
		subprocess.run(
			["yarn", "install"],
			cwd=self.spa_path,
			check=True
		)

		# Step 5: Add runtime deps
		subprocess.run(
			["yarn", "add", "frappe-react-sdk", "socket.io-client@^4.5.1"],
			cwd=self.spa_path,
			check=True
		)

	def _patch_react_ts_package_json(self):
		"""
		Replaces the Node 20-only 'typescript-eslint' v8 unified package with
		the split '@typescript-eslint/eslint-plugin' + '@typescript-eslint/parser'
		v7 packages, which fully support Node 18.
		Also removes 'eslint-visitor-keys' if it snuck in as a direct dep.
		"""
		pkg_json_path = self.spa_path / "package.json"
		with pkg_json_path.open("r") as f:
			pkg = json.load(f)

		dev_deps = pkg.get("devDependencies", {})

		# Remove the unified v8 package (requires Node >=20)
		dev_deps.pop("typescript-eslint", None)

		# Pin split v7 packages (last major line supporting Node 18)
		dev_deps["@typescript-eslint/eslint-plugin"] = "^7.18.0"
		dev_deps["@typescript-eslint/parser"] = "^7.18.0"

		# Also cap eslint to v8 to match @typescript-eslint v7 peer requirements
		# (@typescript-eslint v7 supports eslint ^8.56.0)
		if "eslint" in dev_deps:
			dev_deps["eslint"] = "^8.57.0"

		pkg["devDependencies"] = dev_deps

		with pkg_json_path.open("w") as f:
			json.dump(pkg, f, indent=2)

		click.echo("✔ Patched package.json: replaced typescript-eslint v8 with @typescript-eslint v7 (Node 18 compatible)")

	def _write_eslint_config_v7(self):
		"""
		create-vite react-ts generates an eslint.config.js using the new flat-config
		API from typescript-eslint v8. Since we're downgrading to v7 (which uses the
		legacy config API), we overwrite eslint.config.js with a compatible version.
		"""
		eslint_config_path = self.spa_path / "eslint.config.js"
		# Write a v7-compatible flat-config shim
		eslint_config_content = REACT_TS_ESLINT_CONFIG_BOILERPLATE
		create_file(eslint_config_path, eslint_config_content)
		click.echo("✔ Wrote eslint.config.js compatible with @typescript-eslint v7 and Node 18")

	def setup_react_vite_config(self):
		vite_config_file: Path = self.spa_path / (
			"vite.config.ts" if self.use_typescript else "vite.config.js"
		)
		if not vite_config_file.exists():
			vite_config_file.touch()
		with vite_config_file.open("w") as f:
			boilerplate = REACT_VITE_CONFIG_BOILERPLATE.replace("{{app}}", self.app)
			boilerplate = boilerplate.replace("{{name}}", self.spa_name)
			f.write(boilerplate)

	def create_react_files(self):
		app_react = self.spa_path / ("src/App.tsx" if self.use_typescript else "src/App.jsx")
		create_file(app_react, APP_REACT_BOILERPLATE)
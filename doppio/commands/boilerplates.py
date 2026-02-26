PROXY_OPTIONS_BOILERPLATE = """import { readFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

// Resolve relative to this file's location, not cwd
// proxyOptions.js lives at: apps/<app>/<spa_name>/proxyOptions.js
// sites/ lives at:          sites/  (sibling of apps/)
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const sitesPath = path.resolve(__dirname, '..', '..', '..', 'sites', 'common_site_config.json');

const common_site_config = JSON.parse(readFileSync(sitesPath, 'utf8'));
const webserver_port = common_site_config.webserver_port || 8000;

export default {
	'^/(app|api|assets|files|private)': {
		target: `http://127.0.0.1:${webserver_port}`,
		ws: true,
		router: function(req) {
			const site_name = req.headers.host.split(':')[0];
			return `http://127.0.0.1:${webserver_port}`;
		}
	}
};
"""

VUE_VITE_CONFIG_BOILERPLATE = """import path from 'path';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import proxyOptions from './proxyOptions';

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [vue()],
	server: {
		port: 8080,
		proxy: proxyOptions
	},
	resolve: {
		alias: {
			'@': path.resolve(__dirname, 'src')
		}
	},
	build: {
		outDir: '../{{app}}/public/{{name}}',
		emptyOutDir: true,
		target: 'es2015',
	},
});
"""

REACT_VITE_CONFIG_BOILERPLATE = """import path from 'path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react'
import proxyOptions from './proxyOptions';

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [react()],
	server: {
		port: 8080,
		proxy: proxyOptions
	},
	resolve: {
		alias: {
			'@': path.resolve(__dirname, 'src')
		}
	},
	build: {
		outDir: '../{{app}}/public/{{name}}',
		emptyOutDir: true,
		target: 'es2015',
	},
});
"""

# ESLint flat-config compatible with @typescript-eslint v7 + eslint v8 + Node 18.
# create-vite@6.1.0 react-ts template ships the unified 'typescript-eslint' v8 package
# which requires Node >=20. This config uses the split v7 packages instead.
REACT_TS_ESLINT_CONFIG_BOILERPLATE = """import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';

export default [
  { ignores: ['dist'] },
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
      parser: tsParser,
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      '@typescript-eslint': tsPlugin,
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...js.configs.recommended.rules,
      ...tsPlugin.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
    },
  },
];
"""

APP_REACT_BOILERPLATE = """import { useState } from 'react'
import reactLogo from './assets/react.svg'
import './App.css'
import { FrappeProvider } from 'frappe-react-sdk'

function App() {
  const [count, setCount] = useState(0)

  return (
    <div className="App">
      <FrappeProvider>
        <div>
          <div>
            <a href="https://vitejs.dev" target="_blank">
              <img src="/vite.svg" className="logo" alt="Vite logo" />
            </a>
            <a href="https://reactjs.org" target="_blank">
              <img src={reactLogo} className="logo react" alt="React logo" />
            </a>
          </div>
          <h1>Vite + React + Frappe</h1>
          <div className="card">
            <button onClick={() => setCount((count) => count + 1)}>
              count is {count}
            </button>
            <p>
              Edit <code>src/App.tsx</code> and save to test HMR
            </p>
          </div>
          <p className="read-the-docs">
            Click on the Vite and React logos to learn more
          </p>
        </div>
      </FrappeProvider>
    </div>
  )
}

export default App
"""

MAIN_JS_BOILERPLATE = """import { createApp } from 'vue';
import { createPinia } from 'pinia';
import App from './App.vue';
import router from './router';

import './assets/main.css';

const app = createApp(App);
app.use(createPinia());
app.use(router);
app.mount('#app');
"""

APP_VUE_BOILERPLATE = """<template>
  <RouterView />
</template>
"""

HOME_VUE_BOILERPLATE = """<template>
  <main>
    <h1>Home</h1>
  </main>
</template>
"""

LOGIN_VUE_BOILERPLATE = """<template>
  <main>
    <h1>Login</h1>
  </main>
</template>
"""

ROUTER_INDEX_BOILERPLATE = """import { createRouter, createWebHistory } from "vue-router";
import Home from "../views/Home.vue";
import authRoutes from './auth';

const routes = [
  {
    path: "/",
    name: "Home",
    component: Home,
  },
  ...authRoutes,
];

const router = createRouter({
  base: "/{{name}}/",
  history: createWebHistory(),
  routes,
});

export default router;
"""

AUTH_ROUTES_BOILERPLATE = """export default [
    {
		path: '/login',
		name: 'Login',
		component: () =>
			import(/* webpackChunkName: "login" */ '../views/Login.vue'),
		meta: {
			isLoginPage: true
		},
		props: true
	}
]
"""
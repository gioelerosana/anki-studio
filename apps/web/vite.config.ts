import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';

// Inietta in dist/sw.js l'elenco completo dei file della build e un'impronta
// del loro contenuto: il service worker li mette tutti in cache
// all'installazione (uso offline) e cambia a ogni build, così il browser
// installa la versione nuova.
function precacheManifest(): Plugin {
  let outDir = '';
  return {
    name: 'app-precache-manifest',
    apply: 'build',
    configResolved(config) {
      outDir = path.resolve(config.root, config.build.outDir);
    },
    closeBundle() {
      const swPath = path.join(outDir, 'sw.js');
      const files = readdirSync(outDir, { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => path.relative(outDir, path.join(entry.parentPath, entry.name)).split(path.sep).join('/'))
        .filter((file) => file !== 'sw.js' && !file.endsWith('.map'))
        .sort();
      const hash = createHash('sha256');
      for (const file of files) hash.update(file).update(readFileSync(path.join(outDir, file)));
      const sw = readFileSync(swPath, 'utf8')
        .replace('__APP_BUILD__', hash.digest('hex').slice(0, 12))
        .replace('__APP_PRECACHE__', JSON.stringify(files));
      writeFileSync(swPath, sw);
    },
  };
}

// In sviluppo `/sw.js` è un service worker che si autodistrugge. Un dispositivo che ha
// installato la PWA da una build di produzione tiene il service worker di produzione, che mette in
// cache anche i moduli del server di sviluppo e li serve vecchi per sempre (né si aggiorna:
// il `sw.js` di `public/` senza segnaposto sostituiti non è valido). Questo lo sostituisce,
// svuota le cache dell'app, si deregistra e ricarica le schede aperte.
const SELF_DESTROYING_SW = `
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k.startsWith('anki-studio-')).map((k) => caches.delete(k)));
    await self.registration.unregister();
    const clients = await self.clients.matchAll({ type: 'window' });
    for (const client of clients) client.navigate(client.url);
  })());
});
`;

function devServiceWorkerReset(): Plugin {
  return {
    name: 'app-dev-sw-reset',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use('/sw.js', (_req, res) => {
        res.setHeader('Content-Type', 'text/javascript');
        res.setHeader('Cache-Control', 'no-store');
        res.end(SELF_DESTROYING_SW);
      });
    },
  };
}

// Versione dell'app, mostrata nella UI.
const appVersion: string = JSON.parse(readFileSync(path.resolve(__dirname, 'package.json'), 'utf8')).version;

export default defineConfig({
  base: '/',
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  plugins: [react(), precacheManifest(), devServiceWorkerReset()],
  build: {
    // MathJax (src/study/math.ts) è un chunk a parte da ~1,8 MB (640 kB gzip), caricato solo
    // alla prima carta con una formula e messo in cache dal service worker: l'avviso non serve.
    chunkSizeWarningLimit: 2000,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@anki-studio/ui-kit/theme.css': path.resolve(__dirname, '../../packages/ui-kit/src/theme.css'),
      '@anki-studio/ui-kit': path.resolve(__dirname, '../../packages/ui-kit/src/index.ts'),
    },
  },
  server: {
    port: 5173,
    host: true,
    // Test dall'iPad via Tailscale (tailscale serve).
    allowedHosts: ['.ts.net'],
    // In sviluppo l'API gira a parte (pnpm dev:api): stessa origine grazie al proxy,
    // come in produzione dove nginx fa lo stesso lavoro.
    proxy: {
      '/api': { target: process.env.API_URL ?? 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  preview: {
    port: 4173,
    host: true,
    allowedHosts: ['.ts.net'],
    proxy: {
      '/api': { target: process.env.API_URL ?? 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
});

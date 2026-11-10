// Service worker della PWA: mette in cache solo la shell dell'app (HTML, JS,
// CSS, icone). Le chiamate /api/* NON passano mai dalla cache: i dati della
// collezione vengono sempre dal backend.
//
// All'installazione mette in cache l'intera build (elenco iniettato da
// `vite build`, vedi `precacheManifest` in vite.config.ts): così l'app parte
// offline anche se è stata aperta una sola volta. Prima i bundle JS/CSS finivano
// in cache solo se richiesti a SW già attivo, cosa che sulla PWA di iPadOS (che
// ha storage separato da Safari) al primo avvio non succede.
const VERSION = '__APP_BUILD__';
const PRECACHE = /** @type {string[]} */ (__APP_PRECACHE__);
const CACHE = `anki-studio-${VERSION}`;
// Oltre questo tempo una navigazione ripiega sulla copia in cache: su iPad, con
// Wi-Fi senza Internet, `fetch` può restare appeso invece di fallire subito.
const NAVIGATION_TIMEOUT_MS = 3000;

const scoped = (path) => new URL(path, self.registration.scope).href;
const SHELL = scoped('./');

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      // `reload`: niente risposte vecchie dalla cache HTTP del browser.
      .then((cache) => cache.addAll([SHELL, ...PRECACHE.map(scoped)].map((url) => new Request(url, { cache: 'reload' }))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('anki-studio-') && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      }
    );
  });
}

async function put(request, response) {
  if (!response.ok || response.type !== 'basic') return;
  const cache = await caches.open(CACHE);
  await cache.put(request, response);
}

// Navigazioni: rete prima (per vedere subito una nuova versione), con timeout,
// poi la shell in cache.
async function handleNavigation(event) {
  const network = fetch(event.request);
  try {
    const response = await withTimeout(network, NAVIGATION_TIMEOUT_MS);
    if (response.ok && !response.redirected) {
      event.waitUntil(put(SHELL, response.clone()));
      return response;
    }
  } catch {
    // offline o rete appesa: si ripiega sulla cache
  }
  const cached = (await caches.match(SHELL)) || (await caches.match(event.request, { ignoreSearch: true }));
  return cached || network;
}

// Resto (bundle con hash, icone): cache prima, rete come ripiego.
async function handleAsset(event) {
  const cached = await caches.match(event.request, { ignoreSearch: true });
  if (cached) return cached;
  const response = await fetch(event.request);
  event.waitUntil(put(event.request, response.clone()));
  return response;
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  // API e media delle carte: sempre dalla rete (il backend gestisce la cache HTTP dei media).
  // Anche il server MCP (/mcp) e la discovery OAuth (/.well-known/): non sono parte della shell,
  // e una risposta di autenticazione in cache romperebbe il collegamento degli agenti.
  if (
    url.pathname.startsWith('/api/') ||
    url.pathname === '/mcp' ||
    url.pathname.startsWith('/mcp/') ||
    url.pathname.startsWith('/.well-known/')
  )
    return;
  event.respondWith(request.mode === 'navigate' ? handleNavigation(event) : handleAsset(event));
});

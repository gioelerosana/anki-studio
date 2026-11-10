/*
 * Navigazione minima basata sull'hash (#/study/123).
 *
 * Perché l'hash e non la History API: la PWA installata su iPad non ha barra
 * degli indirizzi né tasto indietro, ma un ricaricamento (o iPadOS che
 * riapre l'app dopo averla sospesa) deve riportare sulla stessa schermata.
 * L'hash non arriva mai al server, quindi il backend e il service worker servono
 * sempre la stessa shell.
 */
import { useSyncExternalStore } from 'react';

export type Route =
  | { name: 'decks' }
  | { name: 'study'; deckId: number }
  | { name: 'add'; deckId: number | null }
  | { name: 'settings' }
  | { name: 'remote' }
  | { name: 'library' }
  | { name: 'inbox' };

export function parseRoute(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#/, '').split('?');
  const parts = path.split('/').filter(Boolean);
  const params = new URLSearchParams(query);
  if (parts[0] === 'study' && /^\d+$/.test(parts[1] ?? '')) return { name: 'study', deckId: Number(parts[1]) };
  if (parts[0] === 'add') {
    const deck = params.get('deck');
    return { name: 'add', deckId: deck && /^\d+$/.test(deck) ? Number(deck) : null };
  }
  if (parts[0] === 'settings') return { name: 'settings' };
  if (parts[0] === 'remote') return { name: 'remote' };
  if (parts[0] === 'library') return { name: 'library' };
  if (parts[0] === 'inbox') return { name: 'inbox' };
  return { name: 'decks' };
}

export function routeToHash(route: Route): string {
  switch (route.name) {
    case 'study':
      return `#/study/${route.deckId}`;
    case 'add':
      return route.deckId ? `#/add?deck=${route.deckId}` : '#/add';
    case 'settings':
      return '#/settings';
    case 'remote':
      return '#/remote';
    case 'library':
      return '#/library';
    case 'inbox':
      return '#/inbox';
    default:
      return '#/';
  }
}

export function navigate(route: Route, { replace = false } = {}): void {
  const hash = routeToHash(route);
  if (window.location.hash === hash) return;
  if (replace) window.history.replaceState(null, '', hash);
  else window.history.pushState(null, '', hash);
  // pushState/replaceState non emettono hashchange: lo notifichiamo noi.
  window.dispatchEvent(new HashChangeEvent('hashchange'));
}

function subscribe(listener: () => void) {
  window.addEventListener('hashchange', listener);
  window.addEventListener('popstate', listener);
  return () => {
    window.removeEventListener('hashchange', listener);
    window.removeEventListener('popstate', listener);
  };
}

const getHash = () => window.location.hash;

export function useRoute(): Route {
  return parseRoute(useSyncExternalStore(subscribe, getHash));
}

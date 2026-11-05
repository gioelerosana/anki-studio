/*
 * Preferenze locali dell'app (per dispositivo), in localStorage sotto una sola chiave.
 * Ogni campo è validato da solo: un JSON corrotto ricade sui default.
 */
import { useCallback, useEffect, useSyncExternalStore } from 'react';

export type ThemePreference = 'system' | 'light' | 'dark';

export interface Settings {
  theme: ThemePreference;
  reduceMotion: boolean;
  /** Ultimi tipo di nota e mazzo usati in «Aggiungi carta» (0 = nessuno). */
  lastNotetypeId: number;
  lastDeckId: number;
}

const KEY = 'anki-studio.settings';
const DARK_QUERY = '(prefers-color-scheme: dark)';
const THEMES: readonly ThemePreference[] = ['system', 'light', 'dark'];

const defaults = (): Settings => ({
  theme: 'system',
  reduceMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  lastNotetypeId: 0,
  lastDeckId: 0,
});

function read(): Settings {
  const base = defaults();
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, unknown>;
    return {
      theme: THEMES.find((t) => t === raw.theme) ?? base.theme,
      reduceMotion: typeof raw.reduceMotion === 'boolean' ? raw.reduceMotion : base.reduceMotion,
      lastNotetypeId: typeof raw.lastNotetypeId === 'number' ? raw.lastNotetypeId : base.lastNotetypeId,
      lastDeckId: typeof raw.lastDeckId === 'number' ? raw.lastDeckId : base.lastDeckId,
    };
  } catch {
    return base;
  }
}

let current: Settings = read();

// Le versioni con il token lo tenevano qui: riscrivendo le preferenze sparisce.
try {
  if (localStorage.getItem(KEY)?.includes('"apiToken"')) localStorage.setItem(KEY, JSON.stringify(current));
} catch {
  // storage bloccato: niente da pulire
}
const listeners = new Set<() => void>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      current = read();
      listener();
    }
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export function getSettings(): Settings {
  return current;
}

export function updateSettings(patch: Partial<Settings>): void {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(current));
  } catch {
    // storage pieno o bloccato: la preferenza vale solo per questa sessione
  }
  listeners.forEach((l) => l());
}

function subscribeDark(listener: () => void) {
  const mql = window.matchMedia(DARK_QUERY);
  mql.addEventListener('change', listener);
  return () => mql.removeEventListener('change', listener);
}

export function useSettings() {
  const settings = useSyncExternalStore(subscribe, getSettings);
  const systemDark = useSyncExternalStore(subscribeDark, () => window.matchMedia(DARK_QUERY).matches);
  const darkMode = settings.theme === 'dark' || (settings.theme === 'system' && systemDark);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', darkMode);
  }, [darkMode]);
  useEffect(() => {
    document.documentElement.classList.toggle('reduce-motion', settings.reduceMotion);
  }, [settings.reduceMotion]);

  const update = useCallback((patch: Partial<Settings>) => updateSettings(patch), []);
  return { settings, darkMode, update };
}

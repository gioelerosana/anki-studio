/*
 * Preferenze locali dell'app (per dispositivo), in localStorage sotto una sola chiave.
 * Ogni campo è validato da solo: un JSON corrotto ricade sui default.
 */
import { useCallback, useEffect, useSyncExternalStore } from 'react';

export type ThemePreference = 'system' | 'light' | 'dark';

export interface Settings {
  theme: ThemePreference;
  reduceMotion: boolean;
  /** Token del backend (ANKI_API_TOKEN). Vuoto = schermata di collegamento. */
  apiToken: string;
}

const KEY = 'anki-studio.settings';
const DARK_QUERY = '(prefers-color-scheme: dark)';
const THEMES: readonly ThemePreference[] = ['system', 'light', 'dark'];

const defaults = (): Settings => ({
  theme: 'system',
  reduceMotion: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false,
  apiToken: '',
});

function read(): Settings {
  const base = defaults();
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, unknown>;
    return {
      theme: THEMES.find((t) => t === raw.theme) ?? base.theme,
      reduceMotion: typeof raw.reduceMotion === 'boolean' ? raw.reduceMotion : base.reduceMotion,
      apiToken: typeof raw.apiToken === 'string' ? raw.apiToken : base.apiToken,
    };
  } catch {
    return base;
  }
}

let current: Settings = read();
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

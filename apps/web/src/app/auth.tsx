/*
 * Accesso con Authentik, senza token da inserire.
 *
 * All'avvio si chiede al backend chi è collegato (GET /api/auth/me). Senza sessione
 * si naviga su /api/auth/login: il backend porta su Authentik e, a login fatto, torna
 * qui con il cookie di sessione (HttpOnly, il JavaScript non lo vede). Se Authentik ha
 * già una sessione non chiede niente e sembra un semplice ricaricamento.
 *
 * È una navigazione e non un popup: nella PWA installata su iPad i popup non tornano
 * all'app, una navigazione sì (stessa finestra, stesso cookie jar).
 *
 * Se il server non risponde (offline, Wi-Fi senza Internet) l'app si apre lo stesso:
 * la shell è in cache e le schermate mostrano il loro errore. Un 401 più tardi, da
 * qualunque chiamata, fa ripartire il login.
 */
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { api, ApiError, onUnauthorized } from '../api/client';
import type { AuthUser } from '../api/types';
import { LoginScreen } from '../screens/LoginScreen';

type AuthState =
  | { status: 'checking' }
  /** `user` null: server non raggiungibile, si prova lo stesso. */
  | { status: 'in'; user: AuthUser | null }
  | { status: 'redirecting' }
  | { status: 'out'; error: string };

const ERRORS: Record<string, string> = {
  denied: 'Authentik non ha concesso l’accesso.',
  forbidden: 'Questo account non è autorizzato a usare Anki Studio.',
  expired: 'Il login è scaduto prima di finire. Riprova.',
  unreachable: 'Authentik non è raggiungibile in questo momento.',
  unconfigured: 'Il login non è configurato sul server.',
  blocked: 'Troppi tentativi non riusciti: riprova tra qualche minuto.',
  failed: 'Accesso non riuscito. Riprova.',
};

// Un login automatico che torna subito senza sessione (es. cookie bloccati) non deve
// rimbalzare all'infinito tra app e Authentik: il secondo giro chiede un tocco.
const LAST_REDIRECT_KEY = 'anki-studio.login-redirect-at';
const REDIRECT_GUARD_MS = 60_000;

function loginUrl(): string {
  const { pathname, search, hash } = window.location;
  return `/api/auth/login?${new URLSearchParams({ next: pathname + search + hash })}`;
}

export function startLogin(): void {
  try {
    sessionStorage.setItem(LAST_REDIRECT_KEY, String(Date.now()));
  } catch {
    // storage bloccato: niente protezione dai rimbalzi, il login funziona comunque
  }
  window.location.assign(loginUrl());
}

function recentlyRedirected(): boolean {
  try {
    return Date.now() - Number(sessionStorage.getItem(LAST_REDIRECT_KEY) ?? 0) < REDIRECT_GUARD_MS;
  } catch {
    return false;
  }
}

/** Legge e toglie dall'URL l'esito di un login fallito (`?auth_error=…`). */
function takeAuthError(): string | null {
  const url = new URL(window.location.href);
  const code = url.searchParams.get('auth_error');
  if (code === null) return null;
  url.searchParams.delete('auth_error');
  window.history.replaceState(null, '', url.pathname + url.search + url.hash);
  return ERRORS[code] ?? ERRORS.failed;
}

interface AuthContextValue {
  user: AuthUser | null;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth fuori da AuthGate');
  return ctx;
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'checking' });

  const loginOrExplain = useCallback((error: string | null) => {
    if (error) setState({ status: 'out', error });
    else if (recentlyRedirected()) setState({ status: 'out', error: 'Accesso non completato. Riprova.' });
    else {
      setState({ status: 'redirecting' });
      startLogin();
    }
  }, []);

  useEffect(() => {
    const error = takeAuthError();
    let cancelled = false;
    api
      .me()
      .then((user) => {
        if (cancelled) return;
        try {
          sessionStorage.removeItem(LAST_REDIRECT_KEY);
        } catch {
          // niente da fare
        }
        setState({ status: 'in', user });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) loginOrExplain(error);
        else setState({ status: 'in', user: null });
      });
    return () => {
      cancelled = true;
    };
  }, [loginOrExplain]);

  // Sessione scaduta mentre l'app è aperta: si rifà il login e si torna qui.
  useEffect(
    () =>
      onUnauthorized(() =>
        setState((s) => {
          if (s.status !== 'in') return s;
          queueMicrotask(() => loginOrExplain(null));
          return { status: 'checking' };
        }),
      ),
    [loginOrExplain],
  );

  const logout = useCallback(async () => {
    const res = await api.logout().catch(() => null);
    // Anche la sessione di Authentik, altrimenti il prossimo avvio rientrerebbe da solo.
    window.location.assign(res?.logout_url ?? '/');
  }, []);

  if (state.status === 'in') {
    return <AuthContext.Provider value={{ user: state.user, logout }}>{children}</AuthContext.Provider>;
  }
  return (
    <LoginScreen
      busy={state.status !== 'out'}
      error={state.status === 'out' ? state.error : null}
      onLogin={() => {
        setState({ status: 'redirecting' });
        startLogin();
      }}
    />
  );
}

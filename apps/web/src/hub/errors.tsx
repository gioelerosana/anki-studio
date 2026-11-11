/*
 * Errori di rete e dell'API mostrati in modo uniforme da libreria e agenti.
 *
 * Il 503 è un caso a parte: il backend lo risponde mentre una sync tiene occupata la
 * collezione (Retry-After 5 s). Non è un guasto, basta riprovare: l'avviso lo dice e
 * offre «Riprova».
 */
import { Button, Banner } from '@anki-studio/ui-kit';
import { ApiError } from '../api/client';

export interface DescribedError {
  message: string;
  /** Vale la pena riprovare (rete assente, collezione occupata). */
  retryable: boolean;
  /** Collezione occupata da una sync. */
  busy: boolean;
}

export function describeError(err: unknown, fallback = 'Qualcosa è andato storto'): DescribedError {
  if (err instanceof ApiError) {
    if (err.status === 503) return { message: 'Sync in corso: la collezione è occupata, riprova tra qualche secondo.', retryable: true, busy: true };
    if (err.status === 403) return { message: 'Operazione non permessa per questo accesso.', retryable: false, busy: false };
    if (err.status === 401) return { message: 'Sessione scaduta: accedi di nuovo.', retryable: false, busy: false };
    return { message: err.message || fallback, retryable: err.status >= 500, busy: false };
  }
  // fetch() fallisce con TypeError quando il server non risponde
  if (err instanceof TypeError) return { message: 'Server non raggiungibile.', retryable: true, busy: false };
  return { message: err instanceof Error && err.message ? err.message : fallback, retryable: false, busy: false };
}

export function ErrorBanner({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  className?: string;
}) {
  const info = describeError(error);
  return (
    <Banner
      variant={info.busy ? 'warning' : 'error'}
      className={className}
      action={
        info.retryable && onRetry ? (
          <Button size="xs" variant="outline" onClick={onRetry} className="coarse:h-8">
            Riprova
          </Button>
        ) : null
      }
    >
      {info.message}
    </Banner>
  );
}

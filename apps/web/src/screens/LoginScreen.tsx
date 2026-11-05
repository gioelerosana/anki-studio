/*
 * Schermata di accesso. Di solito si vede solo un istante (verifica della sessione e
 * passaggio su Authentik); resta ferma con il pulsante solo se il login non è riuscito.
 */
import { LogIn } from 'lucide-react';
import { Banner, Button, Card, Spinner } from '@anki-studio/ui-kit';

interface LoginScreenProps {
  busy: boolean;
  error: string | null;
  onLogin: () => void;
}

export function LoginScreen({ busy, error, onLogin }: LoginScreenProps) {
  if (busy) {
    return (
      <main className="flex flex-1 items-center justify-center p-6 pt-[max(1.5rem,env(safe-area-inset-top))]">
        <Spinner className="size-5 text-muted-foreground" label="Accesso in corso" />
      </main>
    );
  }
  return (
    <main className="flex flex-1 items-center justify-center p-6 pt-[max(1.5rem,env(safe-area-inset-top))]">
      <Card className="w-full max-w-sm p-6">
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-base font-semibold">Accedi ad Anki Studio</h1>
            <p className="text-sm text-muted-foreground">Con il tuo account Authentik.</p>
          </div>
          {error ? <Banner variant="error">{error}</Banner> : null}
          <Button size="lg" icon={<LogIn />} onClick={onLogin}>
            Accedi
          </Button>
        </div>
      </Card>
    </main>
  );
}

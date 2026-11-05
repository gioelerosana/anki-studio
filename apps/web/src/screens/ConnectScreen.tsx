import { useState, type FormEvent } from 'react';
import { KeyRound } from 'lucide-react';
import { Banner, Button, Card, Field, Input } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import { updateSettings } from '../settings';

export function ConnectScreen() {
  const [token, setToken] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    updateSettings({ apiToken: token.trim() });
    try {
      await api.createSession();
    } catch (err) {
      updateSettings({ apiToken: '' });
      setError(err instanceof ApiError && err.status === 401 ? 'Token non valido' : 'Server non raggiungibile');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex flex-1 items-center justify-center p-6">
      <Card className="w-full max-w-sm p-6">
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <h1 className="text-base font-semibold">Collega Anki Studio</h1>
            <p className="text-sm text-muted-foreground">
              Inserisci il token del server. Resta salvato solo su questo dispositivo.
            </p>
          </div>
          {error ? <Banner variant="error">{error}</Banner> : null}
          <Field label="Token">
            <Input
              type="password"
              autoComplete="current-password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              leading={<KeyRound className="size-4" />}
              size="lg"
            />
          </Field>
          <Button type="submit" size="lg" loading={loading} disabled={!token.trim()}>
            Collega
          </Button>
        </form>
      </Card>
    </main>
  );
}

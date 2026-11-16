/*
 * Impostazioni > Telecomando, solo nell'app desktop: il ponte con cui questo computer si mostra
 * al telefono attraverso il server (backend/app/remote_bridge.py).
 *
 * Il telefono apre il server, l'app desktop ha un backend suo con una copia locale: il backend
 * del desktop apre una connessione in uscita verso il telecomando del server, con un token
 * «Solo telecomando» creato là. La configurazione la tiene il backend locale (un file 0600
 * nella cartella dati), mai localStorage: il token lo si incolla qui una volta e non torna
 * indietro, la pagina sa solo se c'è (AGENTS.md, regola 2). Il campo si svuota dopo il
 * salvataggio, così il token in chiaro non resta nemmeno nello stato della pagina.
 *
 * Lo stato si rilegge ogni pochi secondi finché la sezione è aperta: la connessione cade e si
 * ricollega da sola, e qui si vede.
 */
import { useCallback, useEffect, useState } from 'react';
import { Link2, Link2Off, Trash2 } from 'lucide-react';
import { Badge, Banner, Button, Field, Input, Spinner } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { RemoteBridgeStatus } from '../api/types';
import { formatRelative } from '../app/format';
import { useToast } from '../app/toasts';
import { Group } from '../components/SettingsParts';
import { describeError } from '../hub/errors';

/** Il server di Joel (COMPOSE/compose.anki-studio.yml nello stack, ANKI_PUBLIC_URL). */
const DEFAULT_SERVER = 'https://anki.jshep.xyz';
const POLL_MS = 2000;

export function RemoteBridgeSection() {
  const [status, setStatus] = useState<RemoteBridgeStatus | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [serverUrl, setServerUrl] = useState<string | null>(null);
  const [token, setToken] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const next = await api.remoteBridge();
      setStatus(next);
      setLoadError(null);
      // il campo prende il valore salvato una volta sola: dopo è di chi scrive
      setServerUrl((current) => current ?? (next.server_url || DEFAULT_SERVER));
    } catch (err) {
      setLoadError(err);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  async function save(enabled: boolean) {
    if (busy || serverUrl === null) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api.configureRemoteBridge({ server_url: serverUrl.trim(), token: token.trim() || null, enabled });
      setStatus(next);
      setToken('');
      toast('success', enabled ? 'Ponte del telecomando attivato' : 'Telecomando scollegato');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function forget() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.forgetRemoteBridge());
      setToken('');
      toast('success', 'Token cancellato da questo computer');
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (status === null) {
    return (
      <Group title="Telecomando dal telefono">
        {loadError ? (
          <Banner variant="error" className="m-3">
            {describeError(loadError).message}
          </Banner>
        ) : (
          <div className="flex justify-center p-6 text-muted-foreground">
            <Spinner />
          </div>
        )}
      </Group>
    );
  }

  const active = status.enabled && status.status !== 'off';
  const canConnect = !!serverUrl?.trim() && (status.token_set || !!token.trim());

  return (
    <Group title="Telecomando dal telefono">
      <div className="flex flex-col gap-4 p-4">
        <p className="text-xs text-muted-foreground">
          Il telefono apre Anki Studio sul server: con il ponte vede la schermata di studio di questo computer e la comanda, come il telecomando nel browser. Sul server crea un token «Solo telecomando» (Impostazioni → Agenti → Nuovo agente) e incollalo qui. Il token non legge né modifica le carte; la collezione resta quella locale, allineata con la sync di AnkiWeb.
        </p>

        <BridgeState status={status} />

        {error ? <Banner variant="error">{describeError(error).message}</Banner> : null}

        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (canConnect) void save(true);
          }}
        >
          <Field label="Indirizzo del server" hint="Lo stesso che apri dal telefono.">
            <Input
              value={serverUrl ?? ''}
              onChange={(e) => setServerUrl(e.target.value)}
              type="url"
              inputMode="url"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              maxLength={500}
              disabled={busy}
            />
          </Field>
          <Field label="Token" hint={status.token_set ? 'Impostato. Incollane uno nuovo solo per sostituirlo.' : 'Inizia con ask_. Si vede una volta sola, quando lo crei sul server.'}>
            <Input
              value={token}
              onChange={(e) => setToken(e.target.value)}
              type="password"
              placeholder={status.token_set ? 'Impostato' : 'ask_…'}
              autoComplete="off"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              maxLength={200}
              mono
              disabled={busy}
            />
          </Field>
          <div className="flex flex-wrap items-center gap-2">
            {active ? (
              <>
                {token.trim() ? (
                  <Button type="submit" loading={busy} icon={<Link2 />}>
                    Salva e ricollega
                  </Button>
                ) : null}
                <Button type="button" variant={token.trim() ? 'outline' : 'default'} icon={<Link2Off />} loading={busy && !token.trim()} onClick={() => void save(false)}>
                  Scollega
                </Button>
              </>
            ) : (
              <Button type="submit" loading={busy} disabled={!canConnect} icon={<Link2 />}>
                Collega
              </Button>
            )}
            {status.token_set ? (
              <Button type="button" variant="ghost-destructive" icon={<Trash2 />} disabled={busy} onClick={() => void forget()} className="ml-auto">
                Dimentica il token
              </Button>
            ) : null}
          </div>
        </form>
      </div>
    </Group>
  );
}

function BridgeState({ status }: { status: RemoteBridgeStatus }) {
  if (status.status === 'connected') {
    const phones = status.remotes === 0 ? 'nessun telefono aperto' : status.remotes === 1 ? '1 telefono collegato' : `${status.remotes} telefoni collegati`;
    return (
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="success">Collegato</Badge>
        <span>
          {status.connected_at ? `collegato ${formatRelative(status.connected_at)} · ` : ''}
          {phones}
        </span>
      </div>
    );
  }
  if (status.status === 'connecting' || status.status === 'retrying') {
    const retry = status.retry_at ? Math.max(0, Math.round(status.retry_at - Date.now() / 1000)) : null;
    return (
      <div className="flex flex-col gap-1 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <Badge variant="warning">{status.status === 'connecting' ? 'Collegamento…' : 'In riconnessione'}</Badge>
          {retry !== null ? <span>nuovo tentativo tra {retry} s</span> : null}
        </div>
        {status.last_error ? <span>{status.last_error}</span> : null}
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <Badge variant="secondary">Scollegato</Badge>
      <span>Il telefono non vede questo computer.</span>
    </div>
  );
}

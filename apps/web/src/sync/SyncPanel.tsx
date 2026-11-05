/*
 * Pannello AnkiWeb: collegamento dell'account, ultima sync, avanzamento media.
 *
 * La password va al backend una volta sola, che la scambia con una chiave di
 * sessione e non la salva; nemmeno la PWA la tiene (il campo si svuota).
 */
import { useState, type FormEvent } from 'react';
import { Cloud, LogOut, Mail, Lock } from 'lucide-react';
import { Banner, Button, Field, Input, Modal, Spinner } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import type { SyncStatus } from '../api/types';
import { formatRelative } from '../app/format';

const OUTCOME_LABEL: Record<string, string> = {
  no_changes: 'nessuna modifica',
  synced: 'riuscita',
  full_download: 'collezione scaricata',
  full_upload: 'collezione caricata',
  full_sync_required: 'serve una sync completa',
  not_logged_in: 'non collegato',
  error: 'non riuscita',
};

export function SyncPanel({
  isOpen,
  onClose,
  status,
  running,
  onSync,
  onResolve,
  onStatusChange,
}: {
  isOpen: boolean;
  onClose: () => void;
  status: SyncStatus | null;
  running: boolean;
  onSync: () => void;
  onResolve: () => void;
  onStatusChange: () => Promise<void>;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function login(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.syncLogin(username.trim(), password);
      setPassword('');
      await onStatusChange();
      // Primo collegamento: la sync scarica la collezione (o dice che serve scegliere).
      onSync();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Email o password non corrette' : 'AnkiWeb non raggiungibile');
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    setBusy(true);
    try {
      await api.syncLogout();
      await onStatusChange();
    } finally {
      setBusy(false);
    }
  }

  const loggedIn = status?.logged_in ?? false;
  const last = status?.last_result ?? null;
  const media = status?.media;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="AnkiWeb"
      description={loggedIn ? undefined : 'Collega il tuo account per sincronizzare con Anki desktop e AnkiMobile.'}
      footer={
        loggedIn ? (
          <>
            <Button variant="ghost-destructive" icon={<LogOut />} onClick={logout} disabled={busy || running} className="mr-auto coarse:h-10">
              Scollega
            </Button>
            <Button icon={<Cloud />} onClick={onSync} loading={running} className="coarse:h-10">
              Sincronizza ora
            </Button>
          </>
        ) : undefined
      }
    >
      {status === null ? (
        <div className="flex justify-center p-6 text-muted-foreground">
          <Spinner />
        </div>
      ) : loggedIn ? (
        <dl className="flex flex-col divide-y text-sm">
          <Row label="Account">{status.username ?? '—'}</Row>
          <Row label="Ultima sync">
            {last ? `${formatRelative(last.finished_at)} · ${OUTCOME_LABEL[last.outcome] ?? last.outcome}` : 'mai'}
          </Row>
          {status.running ? (
            <Row label="In corso">
              <span className="flex items-center gap-2">
                <Spinner className="size-3.5" />
                <span className="font-mono text-xs tabular-nums">{describeProgress(status)}</span>
              </span>
            </Row>
          ) : null}
          {media?.active ? (
            <Row label="Media">
              <span className="flex items-center gap-2">
                <Spinner className="size-3.5" />
                <span className="font-mono text-xs tabular-nums">
                  {[media.checked && `${media.checked} controllati`, media.added && `${media.added} aggiunti`, media.removed && `${media.removed} rimossi`]
                    .filter(Boolean)
                    .join(' · ') || 'in corso'}
                </span>
              </span>
            </Row>
          ) : null}
          {status.full_sync_required && !status.running ? (
            <div className="pt-3">
              <Banner
                variant="warning"
                title="Serve una sync completa"
                action={
                  <Button variant="outline" size="sm" onClick={onResolve}>
                    Scegli
                  </Button>
                }
              >
                Le sync sono ferme finché non scegli quale collezione tenere.
              </Banner>
            </div>
          ) : null}
          {status.endpoint_mismatch ? (
            <div className="pt-3">
              <Banner variant="warning">La chiave salvata è di un altro server di sync: scollega e rifai il login.</Banner>
            </div>
          ) : null}
          {last?.error && !status.full_sync_required ? (
            <div className="pt-3">
              <Banner variant="error">{last.error}</Banner>
            </div>
          ) : null}
          {media?.error ? (
            <div className="pt-3">
              <Banner variant="warning" title="Sync dei media non riuscita">
                {media.error}
              </Banner>
            </div>
          ) : null}
        </dl>
      ) : (
        <form onSubmit={login} className="flex flex-col gap-4">
          {error ? <Banner variant="error">{error}</Banner> : null}
          <Field label="Email">
            <Input
              type="email"
              autoComplete="username"
              autoCapitalize="none"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              leading={<Mail className="size-4" />}
              size="lg"
            />
          </Field>
          <Field label="Password" hint="Non viene salvata: il server tiene solo la chiave di sessione di AnkiWeb.">
            <Input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              leading={<Lock className="size-4" />}
              size="lg"
            />
          </Field>
          <Button type="submit" size="lg" loading={busy} disabled={!username.trim() || !password}>
            Collega AnkiWeb
          </Button>
        </form>
      )}
    </Modal>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 first:pt-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right">{children}</dd>
    </div>
  );
}

function describeProgress(status: SyncStatus): string {
  const p = status.progress;
  if (p?.kind === 'full_sync' && p.transferred != null) {
    const mb = (n: number) => `${(n / 1_048_576).toFixed(1)} MB`;
    return p.total ? `${mb(p.transferred)} di ${mb(p.total)}` : mb(p.transferred);
  }
  if (p?.kind === 'normal_sync' && p.stage) return p.stage;
  if (status.running === 'full_download') return 'download della collezione';
  if (status.running === 'full_upload') return 'upload della collezione';
  return 'sync in corso';
}

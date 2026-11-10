/*
 * Impostazioni > Agenti: i token con cui Claude, Hermes Agent o uno script scrivono nella
 * collezione (docs/PIANO-HUB.md), più le istruzioni per collegarli.
 *
 * Il token in chiaro esiste solo nella risposta alla creazione: lo si mostra una volta,
 * nel riquadro del dialog, e sta in uno stato locale che sparisce alla chiusura. Non va
 * mai in localStorage, nei log né in un contesto più largo del dialog (AGENTS.md, regola 2).
 * Le istruzioni sono testo statico con l'origine della pagina: non si interroga /mcp.
 */
import { useCallback, useEffect, useState } from 'react';
import { Bot, Check, Copy, Pencil, Plus, Trash2 } from 'lucide-react';
import { Badge, Banner, Button, Field, IconButton, Input, Modal, SegmentedControl, Spinner, Switch } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { ApiToken, ApiTokenCreated, TokenScope } from '../api/types';
import { formatRelative } from '../app/format';
import { copyText } from '../app/text';
import { useToast } from '../app/toasts';
import { Group } from '../components/SettingsParts';
import { ConfirmDialog } from '../hub/ConfirmDialog';
import { ErrorBanner, describeError } from '../hub/errors';

const SCOPE_ITEMS: { id: TokenScope; label: string }[] = [
  { id: 'write', label: 'Scrittura' },
  { id: 'read', label: 'Sola lettura' },
];

const SCOPE_HINT: Record<TokenScope, string> = {
  write: 'Legge, crea e modifica le proprie note. Non cancella mai e non fa la sync completa.',
  read: 'Può solo leggere mazzi, tag e note.',
};

/** Come il backend ricava il tag `agent::<nome>` dal nome del token. */
const agentSlug = (name: string) =>
  name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '');

export function AgentsSection() {
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ApiToken | null>(null);
  const [revoking, setRevoking] = useState<ApiToken | null>(null);
  const [revokeBusy, setRevokeBusy] = useState(false);
  const [revokeError, setRevokeError] = useState<unknown>(null);
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      setTokens(await api.tokens());
      setError(null);
    } catch (err) {
      setError(err);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function revoke() {
    if (!revoking) return;
    setRevokeBusy(true);
    setRevokeError(null);
    try {
      await api.deleteToken(revoking.id);
      toast('success', `Agente «${revoking.name}» revocato`);
      setRevoking(null);
      await load();
    } catch (err) {
      setRevokeError(err);
    } finally {
      setRevokeBusy(false);
    }
  }

  const origin = window.location.origin;

  return (
    <>
      <Group
        title="Agenti"
        action={
          <Button variant="outline" size="xs" icon={<Plus />} onClick={() => setCreating(true)} className="coarse:h-8">
            Nuovo agente
          </Button>
        }
      >
        {error ? <ErrorBanner error={error} onRetry={() => void load()} className="m-3" /> : null}
        {tokens === null ? (
          error ? null : (
            <div className="flex justify-center p-6 text-muted-foreground">
              <Spinner />
            </div>
          )
        ) : tokens.length === 0 ? (
          <p className="px-4 py-4 text-xs text-muted-foreground">
            Nessun agente collegato. Crea un token per far scrivere carte a Claude, a Hermes Agent o a uno script: le sue note possono arrivare come bozze da approvare nell’Inbox.
          </p>
        ) : (
          <ul className="divide-y">
            {tokens.map((t) => (
              <TokenRow key={t.id} token={t} onEdit={() => setEditing(t)} onRevoke={() => { setRevokeError(null); setRevoking(t); }} />
            ))}
          </ul>
        )}
      </Group>

      <Group title="Collega Hermes Agent">
        <div className="flex flex-col gap-3 p-4">
          <p className="text-xs text-muted-foreground">
            Nella configurazione di Hermes Agent aggiungi il server MCP sotto <code className="font-mono">mcp_servers</code> e sostituisci <code className="font-mono">&lt;token&gt;</code> con un token di un agente creato qui sopra.
          </p>
          <CodeBlock label="Configurazione di Hermes Agent" code={`mcp_servers:\n  anki-studio:\n    url: "${origin}/mcp"\n    headers:\n      Authorization: "Bearer <token>"`} />
        </div>
      </Group>

      <Group title="Collega l’app Claude">
        <div className="flex flex-col gap-3 p-4">
          <ol className="list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
            <li>Nell’app Claude apri le impostazioni dei connettori e scegli «Aggiungi connettore personalizzato».</li>
            <li>Come URL del server incolla l’indirizzo qui sotto.</li>
            <li>Quando richiesto, accedi con Authentik: l’accesso passa da lì, senza token.</li>
          </ol>
          <CodeBlock label="URL del server MCP" code={`${origin}/mcp`} />
          <p className="text-2xs text-muted-foreground">Le note create dall’app Claude arrivano come bozze nell’Inbox.</p>
        </div>
      </Group>

      <CreateTokenDialog
        isOpen={creating}
        onClose={() => setCreating(false)}
        onCreated={() => void load()}
      />
      <EditTokenDialog
        token={editing}
        onClose={() => setEditing(null)}
        onSaved={() => {
          setEditing(null);
          toast('success', 'Agente aggiornato');
          void load();
        }}
      />
      <ConfirmDialog
        isOpen={revoking !== null}
        title={`Revocare «${revoking?.name ?? ''}»?`}
        description="Da subito questo agente non può più accedere. Le note che ha già creato restano nella collezione."
        confirmLabel="Revoca"
        busy={revokeBusy}
        error={revokeError}
        onConfirm={() => void revoke()}
        onClose={() => setRevoking(null)}
      />
    </>
  );
}

function TokenRow({ token, onEdit, onRevoke }: { token: ApiToken; onEdit: () => void; onRevoke: () => void }) {
  return (
    <li className="flex items-center gap-3 px-4 py-3 coarse:min-h-14">
      <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border bg-muted text-muted-foreground">
        <Bot className="size-4" aria-hidden />
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="truncate text-sm font-medium">{token.name}</span>
          <Badge variant="secondary">{token.scope === 'write' ? 'Scrittura' : 'Sola lettura'}</Badge>
          {token.scope === 'write' ? <Badge variant={token.review ? 'info' : 'outline'}>{token.review ? 'Bozze' : 'Dirette'}</Badge> : null}
        </div>
        <span className="text-2xs text-muted-foreground">
          Creato {formatRelative(token.created_at)} · {token.last_used_at ? `ultimo uso ${formatRelative(token.last_used_at)}` : 'mai usato'}
        </span>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">
        <IconButton label={`Modifica «${token.name}»`} onClick={onEdit} className="coarse:size-10">
          <Pencil />
        </IconButton>
        <IconButton label={`Revoca «${token.name}»`} variant="ghost-destructive" onClick={onRevoke} className="coarse:size-10">
          <Trash2 />
        </IconButton>
      </div>
    </li>
  );
}

function ScopeFields({
  scope,
  review,
  onScope,
  onReview,
}: {
  scope: TokenScope;
  review: boolean;
  onScope: (s: TokenScope) => void;
  onReview: (r: boolean) => void;
}) {
  return (
    <>
      <Field label="Cosa può fare" hint={SCOPE_HINT[scope]}>
        <SegmentedControl items={SCOPE_ITEMS} activeId={scope} onChange={onScope} aria-label="Scope del token" className="self-start" />
      </Field>
      <div className="flex flex-col gap-1">
        <Switch
          checked={review}
          onCheckedChange={onReview}
          disabled={scope === 'read'}
          label="Le sue note arrivano come bozze"
        />
        <span className="pl-11 text-2xs text-muted-foreground">
          {scope === 'read' ? 'Un agente in sola lettura non crea note.' : 'Le carte restano sospese nell’Inbox finché non le approvi.'}
        </span>
      </div>
    </>
  );
}

function CreateTokenDialog({ isOpen, onClose, onCreated }: { isOpen: boolean; onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('');
  const [scope, setScope] = useState<TokenScope>('write');
  const [review, setReview] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  // Il token in chiaro vive solo qui, finché il dialog è aperto.
  const [created, setCreated] = useState<ApiTokenCreated | null>(null);

  useEffect(() => {
    if (!isOpen) {
      setName('');
      setScope('write');
      setReview(true);
      setError(null);
      setCreated(null);
    }
  }, [isOpen]);

  const slug = agentSlug(name);

  async function create() {
    if (!slug || saving) return;
    setSaving(true);
    setError(null);
    try {
      setCreated(await api.createToken({ name: name.trim(), scope, review: scope === 'write' ? review : false }));
      onCreated();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  if (created) {
    return (
      <Modal
        isOpen={isOpen}
        onClose={onClose}
        title={`Token di «${created.name}»`}
        description="Copialo adesso: per sicurezza non potrai più vederlo."
        size="md"
        footer={
          <Button onClick={onClose} className="coarse:h-10">
            Fatto
          </Button>
        }
      >
        <div className="flex flex-col gap-3">
          <Banner variant="warning">Questo è l’unico momento in cui il token è visibile. Se lo perdi, revoca l’agente e creane uno nuovo.</Banner>
          <TokenBox token={created.token} />
        </div>
      </Modal>
    );
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={saving ? () => {} : onClose}
      title="Nuovo agente"
      description="Dai un nome a chi userà il token: Claude, Hermes, uno script."
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving} className="coarse:h-10">
            Annulla
          </Button>
          <Button loading={saving} disabled={!slug} onClick={() => void create()} className="coarse:h-10">
            Crea token
          </Button>
        </>
      }
    >
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          void create();
        }}
      >
        {error ? <Banner variant="error">{describeError(error).message}</Banner> : null}
        <Field label="Nome" hint={slug ? `Le sue note avranno il tag agent::${slug}` : 'Lettere, numeri e trattini'}>
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} size="lg" autoFocus autoCapitalize="none" autoCorrect="off" spellCheck={false} inputClassName="coarse:text-base" />
        </Field>
        <ScopeFields scope={scope} review={review} onScope={setScope} onReview={setReview} />
        {/* invio da tastiera nel campo nome */}
        <button type="submit" hidden />
      </form>
    </Modal>
  );
}

function EditTokenDialog({ token, onClose, onSaved }: { token: ApiToken | null; onClose: () => void; onSaved: () => void }) {
  const [scope, setScope] = useState<TokenScope>('write');
  const [review, setReview] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (token) {
      setScope(token.scope);
      setReview(token.review);
      setError(null);
    }
  }, [token]);

  async function save() {
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateToken(token.id, { scope, review });
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  }

  const dirty = !!token && (scope !== token.scope || review !== token.review);

  return (
    <Modal
      isOpen={token !== null}
      onClose={saving ? () => {} : onClose}
      title={`Modifica «${token?.name ?? ''}»`}
      description="Il nome non cambia: è la provenienza delle note già create."
      size="md"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving} className="coarse:h-10">
            Annulla
          </Button>
          <Button loading={saving} disabled={!dirty} onClick={() => void save()} className="coarse:h-10">
            Salva
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {error ? <Banner variant="error">{describeError(error).message}</Banner> : null}
        <ScopeFields scope={scope} review={review} onScope={setScope} onReview={setReview} />
      </div>
    </Modal>
  );
}

/** Il token appena creato: campo di sola lettura che si seleziona con un tocco, più «Copia». */
function TokenBox({ token }: { token: string }) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();

  async function copy() {
    const ok = await copyText(token);
    setCopied(ok);
    if (!ok) toast('error', 'Copia non riuscita: tieni premuto sul token e copialo a mano');
  }

  return (
    <div className="flex items-center gap-2">
      <Input
        readOnly
        mono
        size="lg"
        value={token}
        aria-label="Token dell’agente"
        onFocus={(e) => e.currentTarget.select()}
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        inputClassName="coarse:text-base"
      />
      <Button variant="outline" icon={copied ? <Check /> : <Copy />} onClick={() => void copy()} className="shrink-0 coarse:h-10">
        {copied ? 'Copiato' : 'Copia'}
      </Button>
    </div>
  );
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const toast = useToast();

  async function copy() {
    const ok = await copyText(code);
    setCopied(ok);
    if (ok) window.setTimeout(() => setCopied(false), 2000);
    else toast('error', 'Copia non riuscita: seleziona il testo a mano');
  }

  return (
    <div className="relative">
      <pre role="region" aria-label={label} tabIndex={0} className="overflow-x-auto rounded-lg border bg-muted py-2.5 pl-3 pr-12 font-mono text-xs leading-5 text-foreground">
        {code}
      </pre>
      <IconButton label={copied ? 'Copiato' : `Copia: ${label}`} size="sm" onClick={() => void copy()} className="absolute right-1.5 top-1.5 coarse:size-9">
        {copied ? <Check /> : <Copy />}
      </IconButton>
    </div>
  );
}

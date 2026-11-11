/*
 * Attività recenti degli agenti: il diario delle operazioni (`GET /hub/operations`) con
 * «Annulla». È la rete di sicurezza: gli agenti scrivono note vere e attive,
 * e ogni loro operazione (una batch di note, una modifica, un mazzo) si può rimettere a posto da qui.
 *
 * Annullare è un gesto dell'utente e passa dalla sessione della PWA (i token `read` non
 * possono annullare, la sessione sì). Si chiede sempre conferma, spiegando che
 * le note create si cancellano; dopo l'annullamento un dialog dice cosa è stato fatto, anche
 * per le note saltate perché toccate o studiate nel frattempo, e il chiamante ricarica la sua
 * vista (`onUndone`: la Libreria rilegge i risultati).
 *
 * Lo usano Impostazioni > Agenti (a colpo d'occhio, insieme ai token) e un foglio della
 * Libreria (dove ci si accorge che una carta è sbagliata).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, History } from 'lucide-react';
import { Badge, Banner, Button, EmptyHint, Modal, Spinner } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import type { OperationOut } from '../api/types';
import { formatRelative } from '../app/format';
import { useToast } from '../app/toasts';
import { ConfirmDialog } from '../hub/ConfirmDialog';
import { ErrorBanner } from '../hub/errors';
import { canUndo, statusLabel, summarizeUndo, undoExplanation, undoLabel, type UndoReport } from './operations';

const LIMIT = 50;
/** Rientrando sull'app non si rilegge più spesso di così (visibilitychange e focus arrivano insieme). */
const MIN_INTERVAL_MS = 2000;

const fullDate = (epochSeconds: number) => new Date(epochSeconds * 1000).toLocaleString('it', { dateStyle: 'medium', timeStyle: 'short' });

export function ActivityList({ onUndone }: { onUndone?: () => void }) {
  const toast = useToast();
  const [operations, setOperations] = useState<OperationOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirming, setConfirming] = useState<OperationOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [undoError, setUndoError] = useState<unknown>(null);
  const [report, setReport] = useState<UndoReport | null>(null);
  const lastLoad = useRef(0);
  const alive = useRef(true);

  const load = useCallback(async () => {
    lastLoad.current = Date.now();
    try {
      const r = await api.operations(LIMIT);
      if (!alive.current) return;
      setOperations(r.operations);
      setError(null);
    } catch (err) {
      if (alive.current) setError(err);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void load();
    // Un agente può aver scritto mentre l'app era in secondo piano (standby di iPad).
    const onVisible = () => {
      if (!document.hidden && Date.now() - lastLoad.current > MIN_INTERVAL_MS) void load();
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    return () => {
      alive.current = false;
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
    };
  }, [load]);

  async function undo() {
    if (!confirming) return;
    setBusy(true);
    setUndoError(null);
    try {
      const out = await api.undoOperation(confirming.id);
      setConfirming(null);
      const summary = summarizeUndo(out);
      setReport(summary);
      toast(summary.tone === 'success' ? 'success' : 'info', summary.short);
      onUndone?.();
      await load();
    } catch (err) {
      setUndoError(err);
      // 404 o 409: l'operazione non c'è più o l'ha già annullata un altro schermo, la lista va riallineata
      if (err instanceof ApiError && (err.status === 404 || err.status === 409)) await load();
    } finally {
      setBusy(false);
    }
  }

  const askUndo = (op: OperationOut) => {
    setUndoError(null);
    setConfirming(op);
  };

  return (
    <>
      {error ? <ErrorBanner error={error} onRetry={() => void load()} className="m-3" /> : null}
      {operations === null ? (
        error ? null : (
          <div className="flex justify-center p-6 text-muted-foreground" aria-busy>
            <Spinner />
          </div>
        )
      ) : operations.length === 0 ? (
        <EmptyHint
          icon={<History />}
          title="Nessuna attività"
          description="Quando un agente aggiunge o modifica carte, lo trovi qui e puoi annullarlo."
        />
      ) : (
        <>
          <ul className="divide-y">
            {operations.map((op) => (
              <OperationRow key={op.id} op={op} onUndo={() => askUndo(op)} />
            ))}
          </ul>
          {operations.length >= LIMIT ? <p className="border-t px-4 py-2 text-2xs text-muted-foreground">Le ultime {LIMIT} operazioni.</p> : null}
        </>
      )}

      <ConfirmDialog
        isOpen={confirming !== null}
        title={confirming?.status === 'partial' ? 'Riprovare ad annullare?' : 'Annullare questa operazione?'}
        description={confirming ? `${confirming.agent}: ${confirming.summary}` : undefined}
        confirmLabel={confirming ? undoLabel(confirming) : 'Annulla'}
        tone={confirming?.kind === 'update_note' ? 'default' : 'destructive'}
        busy={busy}
        error={undoError}
        onConfirm={() => void undo()}
        onClose={() => setConfirming(null)}
      >
        <div className="flex flex-col gap-2 text-sm text-muted-foreground">
          {confirming ? undoExplanation(confirming.kind).map((line) => <p key={line}>{line}</p>) : null}
          {confirming?.status === 'partial' ? <p>Riprovo con le note rimaste: quelle già sistemate non vengono toccate di nuovo.</p> : null}
        </div>
      </ConfirmDialog>

      <Modal
        isOpen={report !== null}
        onClose={() => setReport(null)}
        title={report?.title ?? ''}
        size="sm"
        footer={
          <Button onClick={() => setReport(null)} className="coarse:h-10">
            Fatto
          </Button>
        }
      >
        {report ? (
          <div className="flex flex-col gap-3">
            {report.tone === 'warning' ? <Banner variant="warning">Alcune note non sono state toccate perché sono cambiate dopo l’operazione. Puoi riprovare più tardi dalla lista.</Banner> : null}
            <ul className="flex flex-col gap-1 text-sm">
              {report.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Modal>
    </>
  );
}

function OperationRow({ op, onUndo }: { op: OperationOut; onUndo: () => void }) {
  const label = statusLabel(op.status);
  return (
    <li className="flex items-start gap-3 px-4 py-3 coarse:min-h-14">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <p className="break-words text-sm">{op.summary}</p>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-muted-foreground">
          <Badge variant="outline" icon={<Bot />} title={`Operazione dell’agente ${op.agent}`}>
            {op.agent}
          </Badge>
          <time dateTime={new Date(op.created_at * 1000).toISOString()} title={fullDate(op.created_at)}>
            {formatRelative(op.created_at)}
          </time>
          {label ? <Badge variant={op.status === 'partial' ? 'warning' : 'secondary'}>{label}</Badge> : null}
          {op.status === 'undone' && op.undone_at ? <span>{formatRelative(op.undone_at)}</span> : null}
        </div>
      </div>
      <Button
        variant="outline"
        size="sm"
        disabled={!canUndo(op)}
        onClick={onUndo}
        aria-label={`${undoLabel(op)}: ${op.summary}`}
        className="shrink-0 coarse:h-10"
      >
        {undoLabel(op)}
      </Button>
    </li>
  );
}

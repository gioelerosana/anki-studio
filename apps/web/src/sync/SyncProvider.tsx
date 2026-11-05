/*
 * Stato della sync con AnkiWeb, condiviso da tutta l'app.
 *
 * Perché un provider: la sync parte dall'elenco mazzi, dalla fine di una
 * sessione e dalle impostazioni, ma il conflitto (409) e il login vanno
 * gestiti in un solo posto, con un solo dialog. `dataVersion` cresce quando
 * la collezione del server è cambiata: le schermate lo usano per ricaricare.
 *
 * Regola 1 di AGENTS.md: la sync completa (che sovrascrive una delle due
 * collezioni) parte solo da `FullSyncDialog`, dopo una scelta esplicita.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { api, ApiError } from '../api/client';
import type { SyncResult, SyncStatus } from '../api/types';
import { useToast } from '../app/toasts';
import { FullSyncDialog } from './FullSyncDialog';
import { SyncPanel } from './SyncPanel';

interface SyncContextValue {
  status: SyncStatus | null;
  running: boolean;
  dataVersion: number;
  /** `quiet`: niente toast di successo e niente pannello di login (sync automatica a fine sessione). */
  runSync: (opts?: { quiet?: boolean }) => Promise<void>;
  openPanel: () => void;
  /** Riapre la scelta della sync completa (conflitto trovato da una sync automatica). */
  openConflict: () => void;
  refreshStatus: () => Promise<SyncStatus | null>;
}

const SyncContext = createContext<SyncContextValue | null>(null);

const POLL_MS = 2000;

const OUTCOME_MESSAGE: Partial<Record<SyncResult['outcome'], string>> = {
  no_changes: 'Già sincronizzato',
  synced: 'Sincronizzato con AnkiWeb',
  full_download: 'Collezione scaricata da AnkiWeb',
  full_upload: 'Collezione caricata su AnkiWeb',
};

export function SyncProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [running, setRunning] = useState(false);
  const [dataVersion, setDataVersion] = useState(0);
  const [panelOpen, setPanelOpen] = useState(false);
  const [conflictOpen, setConflictOpen] = useState(false);
  const runningRef = useRef(false);

  const refreshStatus = useCallback(async () => {
    try {
      const next = await api.syncStatus();
      setStatus(next);
      return next;
    } catch {
      // stato non disponibile: il pannello mostra quello che sa
      return null;
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  // Media in download (dopo una sync completa possono essere migliaia) o sync partita dal
  // server (automatica): si segue l'avanzamento finché non finisce.
  const serverRunning = status?.running ?? null;
  const busyOnServer = (status?.media.active ?? false) || serverRunning !== null;
  useEffect(() => {
    if (!busyOnServer) return;
    const timer = setInterval(() => void refreshStatus(), POLL_MS);
    return () => clearInterval(timer);
  }, [busyOnServer, refreshStatus]);

  // Finita una sync che non abbiamo avviato noi: la collezione può essere cambiata.
  const wasRunning = useRef(serverRunning);
  useEffect(() => {
    if (wasRunning.current && !serverRunning && !runningRef.current) setDataVersion((v) => v + 1);
    wasRunning.current = serverRunning;
  }, [serverRunning]);

  const handleResult = useCallback(
    (result: SyncResult, quiet: boolean) => {
      if (result.outcome !== 'no_changes') setDataVersion((v) => v + 1);
      const message = OUTCOME_MESSAGE[result.outcome];
      if (!quiet && message) toast('success', message);
    },
    [toast],
  );

  const runSync = useCallback(
    async ({ quiet = false } = {}) => {
      if (runningRef.current) return;
      runningRef.current = true;
      setRunning(true);
      try {
        handleResult(await api.sync(), quiet);
      } catch (err) {
        if (err instanceof ApiError && err.status === 409) {
          // 409 è quasi sempre il conflitto; un backend recente lo conferma con
          // `full_sync_required`, altrimenti è una sync rifiutata per proteggere i dati.
          const latest = await refreshStatus();
          if (latest?.full_sync_required === false) toast('error', err.message);
          else {
            // Un dialog alla volta: il conflitto sostituisce il pannello AnkiWeb.
            setPanelOpen(false);
            setConflictOpen(true);
          }
        } else if (err instanceof ApiError && err.status === 401) {
          // 401 qui è "non collegato ad AnkiWeb" (il token dell'app è già passato).
          if (!quiet) setPanelOpen(true);
        } else if (!quiet || !(err instanceof ApiError)) {
          toast('error', err instanceof Error ? `Sync non riuscita: ${err.message}` : 'Sync non riuscita');
        }
      } finally {
        runningRef.current = false;
        setRunning(false);
        void refreshStatus();
      }
    },
    [handleResult, refreshStatus, toast],
  );

  const runFullSync = useCallback(
    async (direction: 'upload' | 'download') => {
      runningRef.current = true;
      setRunning(true);
      try {
        handleResult(await api.fullSync(direction), false);
        setConflictOpen(false);
      } catch (err) {
        toast('error', err instanceof Error ? `Sync completa non riuscita: ${err.message}` : 'Sync completa non riuscita');
      } finally {
        runningRef.current = false;
        setRunning(false);
        void refreshStatus();
      }
    },
    [handleResult, refreshStatus, toast],
  );

  const value = useMemo<SyncContextValue>(
    () => ({
      status,
      running: running || serverRunning !== null,
      dataVersion,
      runSync,
      // Lo stato può essere cambiato altrove (sync automatica del server, media in download).
      openPanel: () => {
        setPanelOpen(true);
        void refreshStatus();
      },
      openConflict: () => {
        setPanelOpen(false);
        setConflictOpen(true);
      },
      refreshStatus,
    }),
    [status, running, serverRunning, dataVersion, runSync, refreshStatus],
  );

  return (
    <SyncContext.Provider value={value}>
      {children}
      <SyncPanel
        isOpen={panelOpen}
        onClose={() => setPanelOpen(false)}
        status={status}
        running={running || serverRunning !== null}
        onSync={() => void runSync()}
        onResolve={() => {
          setPanelOpen(false);
          setConflictOpen(true);
        }}
        onStatusChange={async () => {
          await refreshStatus();
        }}
      />
      <FullSyncDialog
        isOpen={conflictOpen}
        running={running}
        onCancel={() => setConflictOpen(false)}
        onConfirm={(direction) => void runFullSync(direction)}
      />
    </SyncContext.Provider>
  );
}

export function useSync(): SyncContextValue {
  const ctx = useContext(SyncContext);
  if (!ctx) throw new Error('useSync fuori da SyncProvider');
  return ctx;
}

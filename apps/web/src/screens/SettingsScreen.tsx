/*
 * Impostazioni: aspetto, AnkiWeb, dispositivo, scorciatoie, statistiche di oggi.
 * Una sola colonna anche su iPad orizzontale: sono poche righe e restano leggibili.
 */
import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, Unplug } from 'lucide-react';
import {
  Button,
  HeaderBar,
  Kbd,
  KbdGroup,
  Modal,
  SegmentedControl,
  Switch,
} from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { TodayStats } from '../api/types';
import { formatDuration, formatRelative } from '../app/format';
import { navigate } from '../app/route';
import { useSettings, type ThemePreference } from '../settings';
import { useSync } from '../sync/SyncProvider';

const THEME_ITEMS: { id: ThemePreference; label: string }[] = [
  { id: 'system', label: 'Sistema' },
  { id: 'light', label: 'Chiaro' },
  { id: 'dark', label: 'Scuro' },
];

const SHORTCUTS: { keys: string[]; action: string }[] = [
  { keys: ['Spazio'], action: 'Mostra risposta, poi «Bene»' },
  { keys: ['1', '2', '3', '4'], action: 'Di nuovo · Difficile · Bene · Facile' },
  { keys: ['Z'], action: 'Annulla l’ultima risposta' },
  { keys: ['R'], action: 'Riproduci audio' },
  { keys: ['E'], action: 'Modifica nota' },
  { keys: ['A'], action: 'Aggiungi carta' },
  { keys: ['-'], action: 'Seppellisci' },
  { keys: ['@'], action: 'Sospendi' },
  { keys: ['Ctrl', '1–7'], action: 'Flag' },
  { keys: ['Esc'], action: 'Torna ai mazzi' },
  { keys: ['⌘', 'Invio'], action: 'Aggiungi (in «Aggiungi carta»)' },
];

export function SettingsScreen() {
  const { settings, update } = useSettings();
  const { status, openPanel } = useSync();
  const [today, setToday] = useState<TodayStats | null>(null);
  const [confirmUnlink, setConfirmUnlink] = useState(false);

  useEffect(() => {
    api.todayStats().then(setToday).catch(() => {});
  }, []);

  async function unlink() {
    // Il cookie dei media va tolto finché il token è ancora valido per la richiesta.
    await api.deleteSession().catch(() => {});
    update({ apiToken: '' });
    navigate({ name: 'decks' }, { replace: true });
  }

  const last = status?.last_result;

  return (
    <div className="flex h-full flex-col">
      <HeaderBar
        title="Impostazioni"
        leftContent={
          <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'decks' })} className="-ml-1.5 pl-1">
            Mazzi
          </Button>
        }
      />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-4 pb-[max(1.5rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
          <Group title="Oggi">
            <div className="grid grid-cols-3 divide-x">
              <Stat label="Carte" value={today ? String(today.reviews) : '—'} />
              <Stat label="Tempo" value={today ? formatDuration(today.seconds) : '—'} />
              <Stat
                label="Corrette"
                value={today && today.reviews > 0 ? `${Math.round(((today.reviews - today.again) / today.reviews) * 100)}%` : '—'}
              />
            </div>
          </Group>

          <Group title="Aspetto">
            <Row label="Tema">
              <SegmentedControl items={THEME_ITEMS} activeId={settings.theme} onChange={(theme) => update({ theme })} aria-label="Tema" />
            </Row>
            <Row label="Riduci animazioni" hint="Niente dissolvenze tra una carta e l’altra.">
              <Switch checked={settings.reduceMotion} onCheckedChange={(reduceMotion) => update({ reduceMotion })} aria-label="Riduci animazioni" />
            </Row>
          </Group>

          <Group title="Sync">
            <button
              type="button"
              onClick={openPanel}
              className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring coarse:min-h-14"
            >
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-sm">AnkiWeb</span>
                <span className="truncate text-2xs text-muted-foreground">
                  {status === null
                    ? 'Stato non disponibile'
                    : status.logged_in
                      ? `${status.username ?? 'Collegato'}${last ? ` · ultima sync ${formatRelative(last.finished_at)}` : ''}`
                      : 'Non collegato'}
                </span>
              </span>
              <ChevronRight className="size-4 text-muted-foreground" />
            </button>
          </Group>

          <Group title="Questo dispositivo">
            <Row label="Scollega dal server" hint="Il token viene cancellato da questo iPad. La collezione resta sul server.">
              <Button variant="destructive-outline" icon={<Unplug />} onClick={() => setConfirmUnlink(true)} className="coarse:h-10">
                Scollega
              </Button>
            </Row>
          </Group>

          <Group title="Tastiera">
            <ul className="divide-y">
              {SHORTCUTS.map((s) => (
                <li key={s.action} className="flex items-center justify-between gap-4 px-4 py-2 text-sm">
                  <span className="text-muted-foreground">{s.action}</span>
                  <KbdGroup>
                    {s.keys.map((k) => (
                      <Kbd key={k}>{k}</Kbd>
                    ))}
                  </KbdGroup>
                </li>
              ))}
            </ul>
          </Group>

          <p className="text-center text-2xs text-muted-foreground">Anki Studio {__APP_VERSION__}</p>
        </div>
      </main>

      <Modal
        isOpen={confirmUnlink}
        onClose={() => setConfirmUnlink(false)}
        title="Scollegare questo dispositivo?"
        description="Per usare di nuovo Anki Studio qui servirà il token del server."
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmUnlink(false)} className="coarse:h-10">
              Annulla
            </Button>
            <Button variant="destructive" onClick={() => void unlink()} className="coarse:h-10">
              Scollega
            </Button>
          </>
        }
      >
        {null}
      </Modal>
    </div>
  );
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="px-1 text-2xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h2>
      <div className="overflow-hidden rounded-lg border bg-card">{children}</div>
    </section>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b px-4 py-3 last:border-b-0 coarse:min-h-14">
      <div className="flex min-w-0 flex-col">
        <span className="text-sm">{label}</span>
        {hint ? <span className="text-2xs text-muted-foreground">{hint}</span> : null}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-0.5 px-2 py-3">
      <span className="font-mono text-base tabular-nums">{value}</span>
      <span className="text-2xs text-muted-foreground">{label}</span>
    </div>
  );
}

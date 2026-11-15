/*
 * Impostazioni divise in sezioni, come in XMap Studio: elenco a sinistra da iPad in su,
 * schede che scorrono in orizzontale sul telefono. La sezione sta nell'hash
 * (#/settings/aspetto…), così un ricaricamento o iPadOS che riapre l'app tornano lì.
 *
 * «Mazzi» è la sezione principale: apre le opzioni di ogni mazzo (DeckOptionsPanel).
 */
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Bot, ChevronLeft, ChevronRight, Cloud, Info, Keyboard, Layers, LogOut, Palette, UserRound } from 'lucide-react';
import {
  Banner,
  Button,
  HeaderBar,
  Kbd,
  KbdGroup,
  Modal,
  SegmentedControl,
  Spinner,
  Switch,
  cn,
} from '@anki-studio/ui-kit';
import { api } from '../api/client';
import { flattenDecks } from '../api/decks';
import type { DeckNode, TodayStats } from '../api/types';
import { useAuth } from '../app/auth';
import { formatDuration, formatRelative } from '../app/format';
import { navigate, type SettingsSection } from '../app/route';
import { AgentsSection } from '../agents/AgentsSection';
import { Group, Row } from '../components/SettingsParts';
import { DeckOptionsPanel } from '../decks/DeckOptionsPanel';
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

const SECTIONS: { id: SettingsSection; label: string; icon: ReactNode }[] = [
  { id: 'decks', label: 'Mazzi', icon: <Layers /> },
  { id: 'appearance', label: 'Aspetto', icon: <Palette /> },
  { id: 'sync', label: 'Sync', icon: <Cloud /> },
  { id: 'agents', label: 'Agenti', icon: <Bot /> },
  { id: 'account', label: 'Account', icon: <UserRound /> },
  { id: 'shortcuts', label: 'Tastiera', icon: <Keyboard /> },
  { id: 'about', label: 'Informazioni', icon: <Info /> },
];

export function SettingsScreen({ section = 'decks', deckId }: { section?: SettingsSection; deckId?: number }) {
  const { settings, update } = useSettings();
  const { status, openPanel } = useSync();
  const [today, setToday] = useState<TodayStats | null>(null);
  const { user, logout } = useAuth();
  const [confirmLogout, setConfirmLogout] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);

  useEffect(() => {
    api.todayStats().then(setToday).catch(() => {});
  }, []);

  function signOut() {
    setLoggingOut(true);
    void logout();
  }

  const last = status?.last_result;
  const scrollRef = useRef<HTMLDivElement>(null);
  // Cambiando sezione (o mazzo) si riparte dall'alto, non dallo scroll della sezione di prima.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 });
  }, [section, deckId]);

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
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav
          aria-label="Sezioni"
          className="flex shrink-0 gap-1 overflow-x-auto border-b px-3 py-2 pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] md:w-56 md:flex-col md:overflow-visible md:border-b-0 md:border-r md:p-3 md:pl-[max(0.75rem,env(safe-area-inset-left))]"
        >
          {SECTIONS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-current={section === item.id ? 'page' : undefined}
              onClick={() => navigate({ name: 'settings', section: item.id }, { replace: true })}
              className={cn(
                'flex h-8 shrink-0 items-center gap-2 rounded-control px-2.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring coarse:h-10 [&_svg]:size-4 [&_svg]:shrink-0',
                section === item.id
                  ? 'bg-accent font-medium text-foreground'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>

        <main ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-4 pb-[max(1.5rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] md:p-6">
            {section === 'decks' && deckId ? <DeckOptionsPanel deckId={deckId} /> : null}

            {section === 'decks' && !deckId ? (
              <>
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
                <DeckOptionsList />
              </>
            ) : null}

            {section === 'appearance' ? (
              <Group title="Aspetto">
                <Row label="Tema">
                  <SegmentedControl items={THEME_ITEMS} activeId={settings.theme} onChange={(theme) => update({ theme })} aria-label="Tema" />
                </Row>
                <Row label="Riduci animazioni" hint="Niente dissolvenze tra una carta e l’altra.">
                  <Switch checked={settings.reduceMotion} onCheckedChange={(reduceMotion) => update({ reduceMotion })} aria-label="Riduci animazioni" />
                </Row>
              </Group>
            ) : null}

            {section === 'sync' ? (
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
            ) : null}

            {section === 'agents' ? <AgentsSection /> : null}

            {section === 'account' ? (
              <Group title="Account">
                <Row label={user?.name || 'Account Authentik'} hint={user?.username ? `Accesso con Authentik come ${user.username}` : 'Accesso con Authentik'}>
                  <Button variant="destructive-outline" icon={<LogOut />} onClick={() => setConfirmLogout(true)} className="coarse:h-10">
                    Esci
                  </Button>
                </Row>
              </Group>
            ) : null}

            {section === 'shortcuts' ? (
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
            ) : null}

            {section === 'about' ? (
              <Group title="Informazioni">
                <div className="flex items-start gap-3 px-4 py-3">
                  <img src="/icon.svg" alt="" className="size-10 shrink-0 rounded-[10px] border" />
                  <div className="min-w-0">
                    <div className="text-sm font-medium">Anki Studio</div>
                    <div className="font-mono text-2xs text-muted-foreground">{__APP_VERSION__}</div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      Un’interfaccia minimale per studiare con Anki da iPad e telefono. Scheduling, carte e sync sono quelli di Anki.
                    </p>
                  </div>
                </div>
              </Group>
            ) : null}
          </div>
        </main>
      </div>

      <Modal
        isOpen={confirmLogout}
        onClose={() => setConfirmLogout(false)}
        title="Uscire da Anki Studio?"
        description="Esci anche da Authentik su questo dispositivo. La collezione resta sul server."
        size="sm"
        footer={
          <>
            <Button variant="secondary" onClick={() => setConfirmLogout(false)} className="coarse:h-10">
              Annulla
            </Button>
            <Button variant="destructive" loading={loggingOut} onClick={signOut} className="coarse:h-10">
              Esci
            </Button>
          </>
        }
      >
        {null}
      </Modal>
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

/** Tutti i mazzi, rientrati come nell'albero: un tocco apre le loro opzioni. */
function DeckOptionsList() {
  const [decks, setDecks] = useState<DeckNode[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .decks()
      .then((d) => setDecks(flattenDecks(d)))
      .catch((err) => setError(err instanceof Error ? err.message : 'Server non raggiungibile'));
  }, []);

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-col gap-0.5 px-1">
        <h2 className="text-2xs font-medium uppercase tracking-wide text-muted-foreground">Opzioni dei mazzi</h2>
        <p className="text-2xs text-muted-foreground">Nuove e ripassi al giorno, passi, seppellimento. Anche con il clic destro (o il tocco lungo) su un mazzo.</p>
      </div>
      {error ? <Banner variant="error">{error}</Banner> : null}
      {decks === null ? (
        error ? null : (
          <div className="flex justify-center p-6 text-muted-foreground">
            <Spinner />
          </div>
        )
      ) : (
        <ul className="divide-y overflow-hidden rounded-lg border bg-card">
          {decks.map((deck) => (
            <li key={deck.id}>
              <button
                type="button"
                onClick={() => navigate({ name: 'settings', section: 'decks', deckId: deck.id })}
                className="flex w-full items-center gap-3 py-3 pr-4 text-left hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring coarse:min-h-12"
                // `level` parte da 1 per i mazzi di primo livello
                style={{ paddingLeft: `${1 + Math.max(0, deck.level - 1)}rem` }}
              >
                <span className="min-w-0 flex-1 truncate text-sm">{deck.name}</span>
                <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

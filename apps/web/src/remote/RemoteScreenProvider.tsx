/*
 * La PWA come "schermo" del telecomando, in ogni schermata: pubblica cosa mostra e
 * riceve i tasti premuti sul telefono (backend/app/remote.py).
 *
 * Sull'elenco dei mazzi il telefono può aprirne uno; durante lo studio comanda la carta
 * (StudyScreen registra il proprio stato e i comandi con `useRemoteStudy`). Nelle altre
 * schermate (aggiungi, impostazioni) il telefono non cambia niente: si perderebbe la nota
 * che si sta scrivendo.
 *
 * Sull'elenco dei mazzi lo stato porta anche i mazzi (`decks`, da DecksScreen con
 * `useRemoteDecks`): il telefono li mostra così come li vede lo schermo. Serve soprattutto
 * all'app desktop, che ha una copia locale della collezione e arriva al telefono attraverso il
 * server (backend/app/remote_bridge.py): /api/decks del server può avere conteggi vecchi.
 *
 * Nessun abbinamento: basta avere l'app aperta con lo stesso account. Con più schermi
 * (computer e iPad) il telefono comanda quello in primo piano per ultimo: lo stato si
 * "rivendica" (`claim`) solo a pagina visibile, e di nuovo quando torna visibile o
 * riprende il focus. Il dispositivo che fa da telecomando (#/remote) non è uno schermo.
 */
import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { DeckNode, RemoteCommand, RemoteDeck, RemoteScreenState } from '../api/types';
import { desktop } from '../app/desktop';
import { navigate, type Route } from '../app/route';
import { useToast } from '../app/toasts';
import { useRemoteSocket } from './useRemoteSocket';

/** Lo stato di studio come lo pubblica StudyScreen (la vista la aggiunge il provider). */
export type RemoteStudyState = Omit<RemoteScreenState, 'view' | 'source' | 'decks'>;
type CommandHandler = (command: RemoteCommand) => void;

interface RemoteScreenContext {
  /** Telefoni collegati come telecomando. */
  remotes: number;
  setStudy: (state: RemoteStudyState | null) => void;
  setDecks: (decks: RemoteDeck[] | null) => void;
  handler: { current: CommandHandler | null };
}

const Context = createContext<RemoteScreenContext | null>(null);

function newScreenId(): string {
  // randomUUID solo nei contesti sicuri: in sviluppo via IP della LAN non c'è
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('');
}

const SOURCE: RemoteScreenState['source'] = desktop ? 'desktop' : 'browser';
/** Lo stesso tetto del backend (REMOTE_MAX_DECKS): oltre, il telefono usa /api/decks. */
const MAX_DECKS = 2000;

/** L'albero dei mazzi ridotto a ciò che serve al telefono; null se è troppo grande. */
export function compactDecks(nodes: DeckNode[]): RemoteDeck[] | null {
  let count = 0;
  const walk = (list: DeckNode[]): RemoteDeck[] =>
    list.map((n) => {
      count += 1;
      return { id: n.id, name: n.name, counts: n.counts, children: walk(n.children) };
    });
  const tree = walk(nodes);
  return count > MAX_DECKS ? null : tree;
}

const EMPTY: RemoteStudyState = {
  deck_id: null,
  deck_name: '',
  done: false,
  card_id: null,
  revealed: false,
  queue: null,
  counts: null,
  button_labels: [],
  has_audio: false,
  audio_blocked: false,
  flag: 0,
  can_undo: false,
  busy: false,
};

/** Una finestra (modifica nota, flag) o un menu aperti: i tasti del telefono aspettano. */
const dialogOpen = () => !!document.querySelector('[role="dialog"], [role="menu"]');

export function RemoteScreenProvider({ route, children }: { route: Route; children: ReactNode }) {
  const toast = useToast();
  const [remotes, setRemotes] = useState(0);
  const [study, setStudy] = useState<RemoteStudyState | null>(null);
  const [decks, setDecks] = useState<RemoteDeck[] | null>(null);
  const [screenId] = useState(newScreenId);
  const handler = useRef<CommandHandler | null>(null);
  const lastSent = useRef('');

  const state = useMemo<RemoteScreenState>(() => {
    if (route.name === 'study') {
      // passando da un mazzo all'altro, lo stato del mazzo vecchio non vale più
      const base = study && study.deck_id === route.deckId ? study : { ...EMPTY, deck_id: route.deckId };
      return { view: 'study', ...base, source: SOURCE };
    }
    if (route.name === 'decks') return { view: 'decks', ...EMPTY, source: SOURCE, decks };
    return { view: 'other', ...EMPTY, source: SOURCE };
  }, [route, study, decks]);

  const latest = useRef({ state, route });
  latest.current = { state, route };

  const onCommand = (command: RemoteCommand) => {
    const { route } = latest.current;
    if (dialogOpen()) {
      toast('info', 'Telecomando in pausa: chiudi la finestra aperta');
      return;
    }
    if (command.action === 'open_deck' && command.deck_id != null) {
      // dall'elenco o da un altro mazzo, mai da "aggiungi" o dalle impostazioni
      if (route.name === 'decks' || route.name === 'study') navigate({ name: 'study', deckId: command.deck_id });
    } else if (command.action === 'close') {
      if (route.name === 'study') navigate({ name: 'decks' });
    } else if (route.name === 'study') handler.current?.(command);
  };

  const { send } = useRemoteSocket(
    `role=screen&screen_id=${screenId}`,
    (message) => {
      if (message.type === 'remotes') setRemotes(message.count);
      else if (message.type === 'command') onCommand(message.command);
    },
    {
      enabled: route.name !== 'remote',
      // connessione nuova (anche dopo una caduta): il server non sa più niente di noi
      onOpen: () => {
        lastSent.current = '';
        publishRef.current(true);
      },
    },
  );

  function publish(force = false) {
    const current = latest.current.state;
    const body = JSON.stringify(current);
    if (!force && body === lastSent.current) return;
    if (send({ type: 'state', state: current, claim: document.visibilityState === 'visible' })) lastSent.current = body;
  }
  const publishRef = useRef(publish);
  publishRef.current = publish;

  useEffect(() => {
    publishRef.current();
  }, [state]);

  useEffect(() => {
    const claim = () => {
      if (document.visibilityState === 'visible') publishRef.current(true);
    };
    document.addEventListener('visibilitychange', claim);
    window.addEventListener('focus', claim);
    return () => {
      document.removeEventListener('visibilitychange', claim);
      window.removeEventListener('focus', claim);
    };
  }, []);

  // Un avviso alla prima connessione di un telefono, non a ogni riconnessione dopo lo standby.
  const announced = useRef(false);
  useEffect(() => {
    if (remotes > 0 && !announced.current) {
      announced.current = true;
      toast('success', 'Telecomando collegato');
    }
  }, [remotes, toast]);

  const value = useMemo(() => ({ remotes, setStudy, setDecks, handler }), [remotes]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/**
 * Per StudyScreen: pubblica lo stato dello studio e riceve i comandi della carta.
 * Restituisce quanti telefoni sono collegati.
 */
export function useRemoteStudy(state: RemoteStudyState | null, onCommand: CommandHandler): number {
  const ctx = useContext(Context);
  const setStudy = ctx?.setStudy;
  const handler = ctx?.handler;
  useEffect(() => {
    setStudy?.(state);
  }, [setStudy, state]);
  useEffect(() => () => setStudy?.(null), [setStudy]);
  useEffect(() => {
    if (!handler) return;
    handler.current = onCommand;
    return () => {
      if (handler.current === onCommand) handler.current = null;
    };
  }, [handler, onCommand]);
  return ctx?.remotes ?? 0;
}

/** Per DecksScreen: i mazzi mostrati, da mandare al telefono insieme allo stato. */
export function useRemoteDecks(decks: DeckNode[] | null) {
  const setDecks = useContext(Context)?.setDecks;
  useEffect(() => {
    setDecks?.(decks ? compactDecks(decks) : null);
  }, [setDecks, decks]);
}

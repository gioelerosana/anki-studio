/*
 * La carta, isolata in uno Shadow DOM.
 *
 * Perché Shadow DOM e non iframe: il contenuto deve ereditare le variabili del
 * tema (sfondo di ripiego, colore dei pulsanti audio) e misurarsi da solo
 * nello scroll della pagina; con un iframe servirebbero ridimensionamento e
 * messaggi per ogni tap. Il CSS del tipo di nota resta chiuso nello shadow root
 * e quello dell'app non entra (`:host { all: initial }`); gli script non girano
 * perché l'HTML passa da `sanitizeCardHtml`. Il riquadro contiene anche il disegno
 * (`contain: paint`): niente che esca o copra l'interfaccia.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { BASE_CARD_CSS, NIGHT_FALLBACK_CSS, prepareCardCss, sanitizeCardHtml } from './cardContent';

export interface CardViewProps {
  html: string;
  css: string;
  cardClass: string;
  dark: boolean;
  /** Tap su un'area della carta che non è un controllo (link, audio, campo). */
  onTap?: () => void;
  onPlay?: (side: 'q' | 'a', index: number) => void;
  className?: string;
}

const INTERACTIVE = new Set(['a', 'button', 'input', 'textarea', 'select', 'label', 'summary', 'video', 'audio', 'details']);
const FONT_STYLE_ID = 'anki-card-fonts';

let mathModule: Promise<typeof import('./math')> | null = null;
const loadMath = () => (mathModule ??= import('./math'));

const CONTAINED = { contain: 'paint', isolation: 'isolate' } as const;

export function CardView({ html, css, cardClass, dark, onTap, onPlay, className }: CardViewProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const handlers = useRef({ onTap, onPlay });
  handlers.current = { onTap, onPlay };

  const prepared = useMemo(() => prepareCardCss(css), [css]);

  // I @font-face vanno nel documento: è l'unica regola della carta che esce dallo shadow root.
  useEffect(() => {
    let style = document.getElementById(FONT_STYLE_ID) as HTMLStyleElement | null;
    if (!style) {
      style = document.createElement('style');
      style.id = FONT_STYLE_ID;
      document.head.appendChild(style);
    }
    if (style.textContent !== prepared.fontFaces) style.textContent = prepared.fontFaces;
  }, [prepared.fontFaces]);

  useLayoutEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const shadow = host.shadowRoot ?? host.attachShadow({ mode: 'open' });
    const night = dark ? ' nightMode night_mode' : '';

    const base = document.createElement('style');
    base.textContent = BASE_CARD_CSS;
    const own = document.createElement('style');
    own.textContent = prepared.css;
    const body = document.createElement('div');
    body.className = `anki-body ${cardClass}${night}`;
    const qa = document.createElement('div');
    qa.id = 'qa';
    qa.appendChild(sanitizeCardHtml(html));
    body.appendChild(qa);

    const nodes: Node[] = [base, own];
    if (dark && !prepared.hasNightBackground) {
      const fallback = document.createElement('style');
      fallback.textContent = NIGHT_FALLBACK_CSS;
      nodes.push(fallback);
    }
    nodes.push(body);
    shadow.replaceChildren(...nodes);

    // Formule: MathJax solo se la carta ne contiene (chunk separato, vedi math.ts).
    if (/\\[([]/.test(html)) {
      void loadMath().then((math) => {
        if (qa.isConnected) math.typesetMath(qa);
      });
    }
  }, [html, prepared, cardClass, dark]);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const onClick = (event: MouseEvent) => {
      for (const target of event.composedPath()) {
        if (target === host) break;
        if (!(target instanceof Element)) continue;
        if (target.classList.contains('anki-play')) {
          event.preventDefault();
          const side = target.getAttribute('data-side') === 'a' ? 'a' : 'q';
          const index = Number(target.getAttribute('data-index') ?? '0');
          handlers.current.onPlay?.(side, Number.isFinite(index) ? index : 0);
          return;
        }
        if (INTERACTIVE.has(target.localName)) return;
      }
      // Una selezione di testo con il dito non è un tap per girare la carta.
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;
      handlers.current.onTap?.();
    };
    host.addEventListener('click', onClick);
    return () => host.removeEventListener('click', onClick);
  }, []);

  // `contain: paint` + `isolation` in linea (e non nel CSS dello shadow root, che il tipo di nota
  // può sovrascrivere): un `position: fixed` o uno z-index enorme nella carta restano dentro il
  // suo riquadro, così un'anteprima nella libreria non può coprire i pulsanti della vista.
  return <div ref={hostRef} className={className} style={CONTAINED} />;
}

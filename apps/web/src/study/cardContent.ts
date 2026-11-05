/*
 * Prepara l'HTML e il CSS di una carta per lo Shadow DOM di `CardView`.
 *
 * Perché sanificare anche se il contenuto è dell'utente: i tipi di nota arrivano
 * da mazzi condivisi e possono contenere `<script>` o `onerror=` che, inseriti
 * nel documento dell'app, girerebbero con il suo token (AGENTS.md, regola 3).
 * Il parsing avviene in un `<template>`: lì niente viene eseguito né caricato.
 * La conseguenza voluta è che le carte con JavaScript (tipi di nota "interattivi")
 * mostrano solo la parte statica.
 */

const MEDIA_PREFIX = '/api/media/';

/** Elementi tolti con tutto il contenuto. */
const DROP = new Set(['script', 'iframe', 'frame', 'frameset', 'object', 'embed', 'base', 'meta', 'link', 'noscript']);
/** Attributi che contengono un URL: niente `javascript:` né documenti HTML in `data:`. */
const URL_ATTRS = new Set(['href', 'src', 'xlink:href', 'action', 'formaction', 'poster', 'background', 'srcset']);
const BAD_URL = /^\s*(?:javascript|vbscript|data:text\/html)/i;
const PLAY_ICON =
  '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86A1 1 0 0 0 8 5.14z"/></svg>';

/** `url(foto.png)` relativi nel CSS puntano ai media della collezione, come fa Anki. */
export function rewriteCssUrls(css: string): string {
  return css.replace(/url\(\s*(['"]?)([^'")]+)\1\s*\)/gi, (match, _q: string, raw: string) => {
    const url = raw.trim();
    if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(url)) return match;
    return `url("${MEDIA_PREFIX}${encodeURIComponent(url)}")`;
  });
}

export function sanitizeCardHtml(html: string): DocumentFragment {
  const template = document.createElement('template');
  template.innerHTML = html;
  const root = template.content;

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  const toRemove: Element[] = [];
  const toUnwrap: Element[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const el = node as Element;
    const tag = el.localName;
    if (DROP.has(tag)) {
      toRemove.push(el);
      continue;
    }
    // Un <form> invierebbe la pagina dell'app: si tiene il contenuto, non il modulo.
    if (tag === 'form') toUnwrap.push(el);
    // SVG animato che riscrive un href: stessa porta di un `javascript:`.
    if ((tag === 'set' || tag === 'animate') && /href/i.test(el.getAttribute('attributeName') ?? '')) {
      toRemove.push(el);
      continue;
    }
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      if (name.startsWith('on')) el.removeAttribute(attr.name);
      else if (URL_ATTRS.has(name) && BAD_URL.test(attr.value)) el.removeAttribute(attr.name);
      else if (name === 'style') el.setAttribute('style', rewriteCssUrls(attr.value));
    }
    if (tag === 'a' && el.hasAttribute('href')) {
      el.setAttribute('target', '_blank');
      el.setAttribute('rel', 'noopener noreferrer');
    }
    if (tag === 'img') {
      // I media arrivano con il cookie di sessione: niente referrer verso domini esterni.
      el.setAttribute('referrerpolicy', 'no-referrer');
      if (!el.hasAttribute('loading')) el.setAttribute('decoding', 'async');
    }
    if (el.classList.contains('anki-play')) el.innerHTML = PLAY_ICON;
  }
  toRemove.forEach((el) => el.remove());
  toUnwrap.forEach((el) => el.replaceWith(...Array.from(el.childNodes)));
  return root;
}

/** Regole @font-face: nello Shadow DOM Chrome le ignora, vanno nel documento. */
export interface PreparedCss {
  css: string;
  fontFaces: string;
  /** Il tipo di nota definisce già uno sfondo per la modalità notte. */
  hasNightBackground: boolean;
}

/**
 * Nello Shadow DOM non ci sono `html` e `body`: i selettori che li nominano
 * puntano all'elemento che fa da body (`.anki-body`, che porta anche `.card`
 * come in Anki desktop). Si passa dal CSSOM per non riscrivere per sbaglio
 * valori o stringhe; se il browser non ha i fogli costruibili, il CSS resta com'è.
 */
export function prepareCardCss(rawCss: string): PreparedCss {
  const css = rewriteCssUrls(rawCss);
  const hasNightBackground = /night[_-]?mode[^{]*\{[^}]*background/i.test(css);
  let sheet: CSSStyleSheet;
  try {
    sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
  } catch {
    return { css, fontFaces: '', hasNightBackground };
  }
  // `replaceSync` scarta gli @import (es. Google Fonts): li rimettiamo in testa a mano.
  const imports = (css.match(/@import[^;]+;/gi) ?? []).join('\n');
  const fontFaces: string[] = [];
  const out: string[] = [];
  const rewrite = (rules: CSSRuleList, sink: string[]) => {
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSFontFaceRule) {
        fontFaces.push(rule.cssText);
      } else if (rule instanceof CSSStyleRule) {
        rule.selectorText = rule.selectorText
          .split(',')
          .map((sel) =>
            sel
              .replace(/(^|[\s>+~])html(?=$|[\s.#:[>+~])/gi, '$1:host')
              .replace(/(^|[\s>+~(])body(?=$|[\s.#:[>+~)])/gi, '$1.anki-body'),
          )
          .join(',');
        sink.push(rule.cssText);
      } else {
        sink.push(rule.cssText);
      }
    }
  };
  rewrite(sheet.cssRules, out);
  return { css: `${imports}\n${out.join('\n')}`, fontFaces: fontFaces.join('\n'), hasNightBackground };
}

/**
 * Stile di base, prima del CSS del tipo di nota (che quindi vince): le carte senza
 * colori propri prendono quelli dell'app, le immagini non escono dallo schermo.
 */
export const BASE_CARD_CSS = `
:host { all: initial; display: flex; flex-direction: column; -webkit-text-size-adjust: 100%; }
.anki-body {
  box-sizing: border-box;
  flex: 1 0 auto;
  margin: 0;
  padding: 24px max(20px, env(safe-area-inset-right)) 32px max(20px, env(safe-area-inset-left));
  background-color: var(--card);
  color: var(--card-foreground);
  font-family: var(--font-sans);
  font-size: 20px;
  line-height: 1.5;
  text-align: center;
  overflow-wrap: anywhere;
  -webkit-user-select: text;
  user-select: text;
}
.anki-body *, .anki-body *::before, .anki-body *::after { box-sizing: border-box; }
#qa { max-width: 46rem; margin: 0 auto; }
img, video { max-width: 100%; height: auto; }
img { max-height: 70vh; object-fit: contain; }
mjx-container { display: inline-block; }
mjx-container[display="true"] { display: block; margin: 0.6em 0; text-align: center; overflow-x: auto; overflow-y: hidden; }
mjx-container svg { overflow: visible; vertical-align: middle; }
hr#answer { border: 0; border-top: 1px solid var(--border); margin: 20px 0; }
a { color: var(--primary); }
.anki-play {
  display: inline-flex; align-items: center; justify-content: center;
  width: 40px; height: 40px; margin: 4px; padding: 0 0 0 2px; vertical-align: middle;
  border-radius: 999px; border: 1px solid var(--input); background: var(--popover);
  color: var(--muted-foreground); cursor: pointer; font: inherit;
  -webkit-tap-highlight-color: transparent;
}
.anki-play:active { transform: scale(0.94); }
.anki-play:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
`;

/** In scuro, se il tipo di nota non pensa alla modalità notte, sfondo e testo li dà l'app. */
export const NIGHT_FALLBACK_CSS = `
.anki-body.nightMode { background-color: var(--card) !important; color: var(--card-foreground) !important; }
`;

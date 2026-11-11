/*
 * Formule delle carte: `\( … \)` in linea e `\[ … \]` a blocco, come MathJax in Anki.
 *
 * Perché MathJax con uscita SVG (lo stesso motore di XMap Studio): l'SVG porta
 * i glifi con sé, quindi funziona dentro lo Shadow DOM, dove i @font-face di
 * KaTeX o di MathJax CHTML non arrivano. Il modulo è un chunk separato, caricato
 * solo alla prima carta con una formula; il service worker lo mette comunque in
 * cache, quindi funziona anche offline.
 */
import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
// Pacchetti uno per uno, non `AllPackages`: i testi delle carte ora li scrivono anche gli agenti
// e `html` (`\href`, `\class`, `\style`, `\cssId`), `action`, `bbox`, `setoptions` e `unicode`
// darebbero a una formula link, stili e attributi arbitrari. Qui restano quelli che servono
// a scrivere matematica e chimica; le macro e le formule non valide non producono link.
import 'mathjax-full/js/input/tex/base/BaseConfiguration.js';
import 'mathjax-full/js/input/tex/ams/AmsConfiguration.js';
import 'mathjax-full/js/input/tex/amscd/AmsCdConfiguration.js';
import 'mathjax-full/js/input/tex/boldsymbol/BoldsymbolConfiguration.js';
import 'mathjax-full/js/input/tex/braket/BraketConfiguration.js';
import 'mathjax-full/js/input/tex/cancel/CancelConfiguration.js';
import 'mathjax-full/js/input/tex/cases/CasesConfiguration.js';
import 'mathjax-full/js/input/tex/centernot/CenternotConfiguration.js';
import 'mathjax-full/js/input/tex/color/ColorConfiguration.js';
import 'mathjax-full/js/input/tex/enclose/EncloseConfiguration.js';
import 'mathjax-full/js/input/tex/extpfeil/ExtpfeilConfiguration.js';
import 'mathjax-full/js/input/tex/gensymb/GensymbConfiguration.js';
import 'mathjax-full/js/input/tex/mathtools/MathtoolsConfiguration.js';
import 'mathjax-full/js/input/tex/mhchem/MhchemConfiguration.js';
import 'mathjax-full/js/input/tex/newcommand/NewcommandConfiguration.js';
import 'mathjax-full/js/input/tex/noerrors/NoErrorsConfiguration.js';
import 'mathjax-full/js/input/tex/noundefined/NoUndefinedConfiguration.js';
import 'mathjax-full/js/input/tex/physics/PhysicsConfiguration.js';
import 'mathjax-full/js/input/tex/textcomp/TextcompConfiguration.js';
import 'mathjax-full/js/input/tex/upgreek/UpgreekConfiguration.js';
import 'mathjax-full/js/input/tex/verb/VerbConfiguration.js';

const PACKAGES = [
  'base', 'ams', 'amscd', 'boldsymbol', 'braket', 'cancel', 'cases', 'centernot', 'color', 'enclose',
  'extpfeil', 'gensymb', 'mathtools', 'mhchem', 'newcommand', 'noerrors', 'noundefined', 'physics',
  'textcomp', 'upgreek', 'verb',
];

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const doc = mathjax.document('', {
  InputJax: new TeX({ packages: PACKAGES }),
  OutputJax: new SVG({ fontCache: 'local' }),
});

/**
 * L'SVG di MathJax è l'unica cosa che entra nella carta senza passare da `sanitizeCardHtml`,
 * e `\mmlToken{mi}[href=…]` (o `\csname mmlToken\endcsname`) può ancora farsi un link: qui si
 * tolgono link, HTML incorporato, gestori ed ogni stile che non sia una misura di MathJax.
 */
const SAFE_STYLE = /^(?:vertical-align|min-width|width|height|margin-left|margin-right|margin-top|margin-bottom)\s*:\s*-?[\d.]+(?:ex|em|px|%)?$/i;

export function cleanMathSvg(root: ParentNode): void {
  root.querySelectorAll('script, foreignObject, style, iframe, object, embed').forEach((el) => el.remove());
  root.querySelectorAll('a').forEach((el) => el.replaceWith(...Array.from(el.childNodes)));
  for (const el of Array.from(root.querySelectorAll('*'))) {
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      if (name.startsWith('on')) el.removeAttribute(attr.name);
      // i glifi sono `<use href="#MJX-…">`: solo frammenti della pagina stessa
      else if ((name === 'href' || name === 'xlink:href') && !attr.value.startsWith('#')) el.removeAttribute(attr.name);
      else if (name === 'style') {
        const kept = attr.value.split(';').map((d) => d.trim()).filter((d) => d && SAFE_STYLE.test(d));
        if (kept.length > 0) el.setAttribute('style', kept.join('; '));
        else el.removeAttribute('style');
      }
    }
  }
}

const MATH = /\\\(([\s\S]+?)\\\)|\\\[([\s\S]+?)\\\]/g;
const cache = new Map<string, string>();

function toSvg(tex: string, display: boolean): string {
  const key = `${display ? 'D' : 'I'}${tex}`;
  let html = cache.get(key);
  if (html === undefined) {
    try {
      html = adaptor.outerHTML(doc.convert(tex, { display, em: 16, ex: 8, containerWidth: 1200 }));
    } catch {
      html = '';
    }
    if (cache.size > 500) cache.clear();
    cache.set(key, html);
  }
  return html;
}

/** Sostituisce le formule nei nodi di testo di `root` (lo `#qa` della carta). */
export function typesetMath(root: Element): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement?.closest('script, style, textarea, code, pre') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes: Text[] = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (/\\[([]/.test(n.nodeValue ?? '')) nodes.push(n as Text);
  }
  for (const node of nodes) {
    const text = node.nodeValue ?? '';
    const frag = document.createDocumentFragment();
    let last = 0;
    for (const m of text.matchAll(MATH)) {
      const index = m.index ?? 0;
      if (index > last) frag.append(text.slice(last, index));
      const display = m[2] !== undefined;
      const svg = toSvg(display ? m[2] : m[1], display);
      if (svg) {
        const template = document.createElement('template');
        template.innerHTML = svg;
        cleanMathSvg(template.content);
        frag.append(template.content);
      } else {
        // Formula non valida: si lascia il sorgente, come fa Anki.
        frag.append(m[0]);
      }
      last = index + m[0].length;
    }
    if (last === 0) continue;
    if (last < text.length) frag.append(text.slice(last));
    node.replaceWith(frag);
  }
}

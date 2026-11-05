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
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js';

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const doc = mathjax.document('', {
  InputJax: new TeX({ packages: AllPackages }),
  OutputJax: new SVG({ fontCache: 'local' }),
});

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

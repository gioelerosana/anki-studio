/*
 * Piccole utilità sul testo condivise da libreria e impostazioni.
 */

/**
 * Testo semplice di un campo di nota (che in Anki è HTML). Il parsing avviene in un
 * documento inerte (DOMParser): niente script, niente immagini caricate.
 */
export function htmlToText(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html');
  // <br> e blocchi diventano spazi, altrimenti "riga1<br>riga2" si incolla in "riga1riga2"
  doc.querySelectorAll('br, p, div, li').forEach((el) => el.append(' '));
  return (doc.body.textContent ?? '')
    .replace(/\[sound:[^\]]*\]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/**
 * Copia negli appunti. `navigator.clipboard` esiste solo nei contesti sicuri (https o
 * localhost): in sviluppo via IP della LAN si ripiega su `execCommand`. Restituisce falso
 * se non è riuscito, così chi chiama può dire di selezionare a mano.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // permesso negato o pagina senza focus: si prova il ripiego
  }
  const area = document.createElement('textarea');
  area.value = text;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  } finally {
    area.remove();
  }
}

/**
 * Un termine di ricerca Anki tra virgolette (`"deck:Lingue::Spagnolo"`), con gli escape che
 * servono perché nomi con spazi, `*` o `_` non vengano letti come sintassi o jolly.
 */
export function searchTerm(key: string, value: string): string {
  const escaped = value.replace(/[\\"*_]/g, (c) => `\\${c}`);
  return `"${key}:${escaped}"`;
}

/** Titolo di una riga: il campo di ordinamento arriva senza HTML ma con i `[sound:…]`. */
export const plainTitle = (text: string) => text.replace(/\[sound:[^\]]*\]/g, '').replace(/\s+/g, ' ').trim();

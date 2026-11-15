/*
 * Passi di (ri)apprendimento come li scrive Anki desktop: "1m 10m 1h 1d".
 *
 * Il backend li vuole in minuti (come la collezione). Qui solo la conversione del testo:
 * gli intervalli veri li calcola lo scheduler di Anki.
 */

const UNIT_MINUTES: Record<string, number> = { s: 1 / 60, m: 1, h: 60, d: 1440 };
// Lo stesso tetto del backend (un anno, 20 passi).
const MAX_MINUTES = 525_600;
const MAX_STEPS = 20;

/** "1m 10m 1,5h" → [1, 10, 90]; `null` se un pezzo non si capisce o è fuori dai limiti. */
export function parseSteps(text: string): number[] | null {
  // Prima la virgola decimale italiana ("1,5h"), poi la virgola come separatore ("1m, 10m"):
  // tra due passi c'è sempre uno spazio, tra le cifre di un decimale no.
  const parts = text.trim().replace(/(\d),(\d)/g, '$1.$2').split(/[\s,;]+/).filter(Boolean);
  if (parts.length > MAX_STEPS) return null;
  const out: number[] = [];
  for (const part of parts) {
    const m = /^(\d+(?:[.]\d+)?)([smhd]?)$/i.exec(part);
    if (!m) return null;
    const minutes = Number(m[1]) * UNIT_MINUTES[(m[2] || 'm').toLowerCase()];
    if (!(minutes > 0) || minutes > MAX_MINUTES) return null;
    out.push(Math.round(minutes * 10_000) / 10_000);
  }
  return out;
}

/** [1, 10, 1440] → "1m 10m 1d": l'unità più grande che dà un numero intero. */
export function formatSteps(minutes: number[]): string {
  return minutes.map(formatStep).join(' ');
}

function formatStep(minutes: number): string {
  if (minutes >= 1440 && Number.isInteger(minutes / 1440)) return `${minutes / 1440}d`;
  if (minutes >= 60 && Number.isInteger(minutes / 60)) return `${minutes / 60}h`;
  if (Number.isInteger(minutes)) return `${minutes}m`;
  const seconds = Math.round(minutes * 60);
  return Math.abs(seconds - minutes * 60) < 0.01 ? `${seconds}s` : `${minutes}m`;
}

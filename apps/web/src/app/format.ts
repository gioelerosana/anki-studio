const relative = new Intl.RelativeTimeFormat('it', { numeric: 'auto' });

/** "2 minuti fa", "ieri". `epochSeconds` come lo manda il backend. */
export function formatRelative(epochSeconds: number, now = Date.now()): string {
  const diff = Math.round(epochSeconds - now / 1000);
  const abs = Math.abs(diff);
  if (abs < 45) return 'adesso';
  if (abs < 3600) return relative.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return relative.format(Math.round(diff / 3600), 'hour');
  return relative.format(Math.round(diff / 86400), 'day');
}

/** "12 min", "1 h 5 min", "40 s". */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m ? `${h} h ${m} min` : `${h} h`;
}

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

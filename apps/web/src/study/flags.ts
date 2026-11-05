/* Flag delle carte: numero di Anki (1-7) → nome e token di colore (theme.css). */
export const FLAGS: { value: number; label: string }[] = [
  { value: 1, label: 'Rosso' },
  { value: 2, label: 'Arancione' },
  { value: 3, label: 'Verde' },
  { value: 4, label: 'Blu' },
  { value: 5, label: 'Rosa' },
  { value: 6, label: 'Turchese' },
  { value: 7, label: 'Viola' },
];

export const flagColor = (flag: number) => `var(--flag-${flag})`;
export const flagLabel = (flag: number) => FLAGS.find((f) => f.value === flag)?.label ?? 'Nessuno';

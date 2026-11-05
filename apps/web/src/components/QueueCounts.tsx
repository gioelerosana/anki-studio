import { cn } from '@anki-studio/ui-kit';
import type { Counts, StudyCard } from '../api/types';

const ITEMS = [
  { key: 'new', label: 'Nuove', tone: 'text-info-foreground' },
  { key: 'learning', label: 'In apprendimento', tone: 'text-error-foreground' },
  { key: 'review', label: 'Da ripassare', tone: 'text-success-foreground' },
] as const;

/** Nuove / in apprendimento / da ripassare. `current` sottolinea la coda della carta mostrata, come Anki. */
export function QueueCounts({
  counts,
  current,
  className,
  cellClassName,
}: {
  counts: Counts;
  current?: StudyCard['queue'];
  className?: string;
  cellClassName?: string;
}) {
  return (
    <span className={cn('flex gap-3 font-mono text-xs tabular-nums', className)}>
      {ITEMS.map(({ key, label, tone }) => (
        <span
          key={key}
          title={label}
          aria-label={`${label}: ${counts[key]}`}
          className={cn(
            'text-right underline-offset-4',
            counts[key] === 0 ? 'text-muted-foreground/50' : tone,
            current === key && 'underline decoration-2',
            cellClassName,
          )}
        >
          {counts[key]}
        </span>
      ))}
    </span>
  );
}

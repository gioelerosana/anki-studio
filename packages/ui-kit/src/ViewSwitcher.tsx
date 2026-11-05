/*
 * Controllo segmentato (cambio vista Mappa / Outliner e simili).
 *
 * Perché un radiogroup con frecce: è una scelta esclusiva tra poche opzioni,
 * quindi tastiera e screen reader devono comportarsi come con i radio nativi
 * (una sola tappa di Tab, frecce per spostarsi). `ViewSwitcher` resta come
 * alias per il codice che lo importa con il nome storico.
 */
import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cn } from './utils.js';

export interface SegmentedControlItem<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
}

export interface SegmentedControlProps<T extends string> {
  items: SegmentedControlItem<T>[];
  activeId: T;
  onChange: (id: T) => void;
  /** `sm` 28px · `default` 32px. */
  size?: 'sm' | 'default';
  className?: string;
  'aria-label'?: string;
}

const TRACK: Record<NonNullable<SegmentedControlProps<string>['size']>, string> = {
  sm: 'h-7',
  default: 'h-8',
};

const SEGMENT: Record<NonNullable<SegmentedControlProps<string>['size']>, string> = {
  sm: 'px-2 text-xs',
  default: 'px-2.5 text-sm',
};

export function SegmentedControl<T extends string>({
  items,
  activeId,
  onChange,
  size = 'default',
  className,
  'aria-label': ariaLabel,
}: SegmentedControlProps<T>) {
  const groupRef = useRef<HTMLDivElement>(null);
  // Nessuna voce attiva (es. un valore fuori elenco): la prima resta la tappa di Tab.
  const tabStopId = items.some((item) => item.id === activeId) ? activeId : items.find((item) => !item.disabled)?.id;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step =
      event.key === 'ArrowRight' || event.key === 'ArrowDown'
        ? 1
        : event.key === 'ArrowLeft' || event.key === 'ArrowUp'
          ? -1
          : 0;
    if (step === 0) return;
    const enabled = items.filter((item) => !item.disabled);
    const index = enabled.findIndex((item) => item.id === activeId);
    const next = enabled[(index + step + enabled.length) % enabled.length];
    if (!next) return;
    event.preventDefault();
    onChange(next.id);
    // Il focus segue la selezione, come nei radio nativi.
    groupRef.current
      ?.querySelector<HTMLElement>(`[data-id="${CSS.escape(next.id)}"]`)
      ?.focus();
  };

  return (
    <div
      ref={groupRef}
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={cn(
        'inline-flex select-none items-stretch gap-0.5 rounded-lg border bg-muted p-0.5',
        TRACK[size],
        className,
      )}
    >
      {items.map((item) => {
        const active = item.id === activeId;
        return (
          <button
            key={item.id}
            type="button"
            role="radio"
            aria-checked={active}
            data-id={item.id}
            tabIndex={item.id === tabStopId ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent font-medium transition-[background-color,color,box-shadow]',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
              'disabled:pointer-events-none disabled:opacity-disabled',
              '[&_svg]:shrink-0 [&_svg:not([class*=size-]):not([class*=w-])]:size-3.5',
              SEGMENT[size],
              active
                ? 'border-border bg-popover text-foreground shadow-control'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            {item.icon}
            <span>{item.label}</span>
          </button>
        );
      })}
    </div>
  );
}

/** Alias storico di `SegmentedControl`. */
export const ViewSwitcher = SegmentedControl;
export type ViewSwitcherItem<T extends string> = SegmentedControlItem<T>;
export type ViewSwitcherProps<T extends string> = SegmentedControlProps<T>;

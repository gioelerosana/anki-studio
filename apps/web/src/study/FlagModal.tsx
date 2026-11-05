import { Check, FlagOff } from 'lucide-react';
import { Modal, cn } from '@anki-studio/ui-kit';
import { FLAGS, flagColor } from './flags';

export function FlagModal({
  isOpen,
  current,
  onClose,
  onSelect,
}: {
  isOpen: boolean;
  current: number;
  onClose: () => void;
  onSelect: (flag: number) => void;
}) {
  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Flag" size="sm">
      <div role="radiogroup" aria-label="Colore del flag" className="grid grid-cols-4 gap-2">
        {FLAGS.map((f) => (
          <FlagOption key={f.value} label={f.label} checked={current === f.value} onClick={() => onSelect(f.value)}>
            <span className="size-5 rounded-full" style={{ backgroundColor: flagColor(f.value) }} />
          </FlagOption>
        ))}
        <FlagOption label="Nessuno" checked={current === 0} onClick={() => onSelect(0)}>
          <FlagOff className="size-5 text-muted-foreground" />
        </FlagOption>
      </div>
    </Modal>
  );
}

function FlagOption({
  label,
  checked,
  onClick,
  children,
}: {
  label: string;
  checked: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      onClick={onClick}
      className={cn(
        'relative flex h-16 flex-col items-center justify-center gap-1.5 rounded-lg border text-2xs text-muted-foreground hover:bg-accent',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
        checked && 'border-ring text-foreground',
      )}
    >
      {children}
      {label}
      {checked ? <Check className="absolute right-1.5 top-1.5 size-3.5 text-foreground" /> : null}
    </button>
  );
}

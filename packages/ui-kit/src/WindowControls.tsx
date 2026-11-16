/*
 * Minimizza / massimizza / chiudi per la barra del titolo disegnata dall'app
 * (Electron senza cornice di sistema).
 *
 * Copiato da XMap Studio, come il resto del kit. Perché ghost 28px e non i pulsanti
 * tondi GNOME: l'interfaccia segue T3 Code,
 * dove i controlli finestra sono bottoni discreti che si accendono solo
 * all'hover; la chiusura vira al rosso pieno per segnalare l'azione.
 */
import { Copy, Minus, Square, X } from 'lucide-react';
import { cn } from './utils.js';
import { Button } from './Button.js';

export interface WindowControlsProps {
  onMinimize?: () => void;
  onMaximize?: () => void;
  onClose?: () => void;
  isMaximized?: boolean;
  className?: string;
}

export function WindowControls({
  onMinimize,
  onMaximize,
  onClose,
  isMaximized = false,
  className,
}: WindowControlsProps) {
  const maximizeLabel = isMaximized ? 'Ripristina' : 'Massimizza';
  return (
    <div className={cn('app-no-drag flex items-center gap-1 pl-2', className)}>
      <Button
        variant="ghost-muted"
        size="icon-sm"
        title="Riduci a icona"
        aria-label="Riduci a icona"
        onClick={onMinimize}
      >
        <Minus className="size-3.5" />
      </Button>
      <Button
        variant="ghost-muted"
        size="icon-sm"
        title={maximizeLabel}
        aria-label={maximizeLabel}
        onClick={onMaximize}
      >
        {isMaximized ? <Copy className="size-3.5" /> : <Square className="size-3" />}
      </Button>
      <Button
        variant="ghost-muted"
        size="icon-sm"
        title="Chiudi"
        aria-label="Chiudi"
        className="hover:bg-error hover:text-primary-foreground"
        onClick={onClose}
      >
        <X className="size-3.5" />
      </Button>
    </div>
  );
}

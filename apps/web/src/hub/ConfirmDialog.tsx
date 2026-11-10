/*
 * Conferma esplicita prima di un gesto che non si annulla (cancellare, scartare, revocare).
 *
 * Come gli altri dialog dell'app: il focus iniziale va al dialog e non al bottone, per non
 * far scattare l'azione con un Invio distratto; Esc e «Annulla» chiudono senza fare niente.
 */
import type { ReactNode } from 'react';
import { Banner, Button, Modal } from '@anki-studio/ui-kit';
import { describeError } from './errors';

export function ConfirmDialog({
  isOpen,
  title,
  description,
  children,
  confirmLabel,
  tone = 'destructive',
  busy = false,
  error,
  onConfirm,
  onClose,
}: {
  isOpen: boolean;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  confirmLabel: string;
  /** `destructive` = rosso pieno (gesti irreversibili); `default` = azione normale. */
  tone?: 'destructive' | 'default';
  busy?: boolean;
  error?: unknown;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Modal
      isOpen={isOpen}
      onClose={busy ? () => {} : onClose}
      title={title}
      description={description}
      size="sm"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy} className="coarse:h-10">
            Annulla
          </Button>
          <Button variant={tone === 'destructive' ? 'destructive' : 'default'} loading={busy} onClick={onConfirm} className="coarse:h-10">
            {confirmLabel}
          </Button>
        </>
      }
    >
      {error ? (
        <Banner variant="error" className="mb-3">
          {describeError(error).message}
        </Banner>
      ) : null}
      {children ?? null}
    </Modal>
  );
}

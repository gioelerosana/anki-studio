/*
 * Conflitto di sync: AnkiWeb e il server sono divergenti e una delle due
 * collezioni va sostituita dall'altra.
 *
 * Perché due passaggi: è l'unica azione dell'app che può far perdere dati
 * (AGENTS.md, regola 1). Prima si sceglie la direzione leggendo cosa si perde,
 * poi la si conferma con un bottone distruttivo che dice esattamente cosa fa.
 * Nessuna opzione è preselezionata e Annulla non tocca niente.
 */
import { useEffect, useState } from 'react';
import { CloudDownload, CloudUpload } from 'lucide-react';
import { Banner, Button, Modal, cn } from '@anki-studio/ui-kit';

type Direction = 'download' | 'upload';

const OPTIONS: { id: Direction; title: string; icon: React.ReactNode; detail: string; confirm: string }[] = [
  {
    id: 'download',
    title: 'Tieni AnkiWeb',
    icon: <CloudDownload className="size-5" />,
    detail:
      'Scarica la collezione di AnkiWeb e sostituisce quella di questo server. Le revisioni e le carte fatte qui dopo l’ultima sync vanno perse.',
    confirm: 'Sostituisci la collezione del server',
  },
  {
    id: 'upload',
    title: 'Tieni questo server',
    icon: <CloudUpload className="size-5" />,
    detail:
      'Carica la collezione di questo server e sostituisce quella di AnkiWeb. Le modifiche fatte su Anki desktop o AnkiMobile e non sincronizzate vanno perse; quei dispositivi dovranno riscaricare tutto.',
    confirm: 'Sostituisci la collezione di AnkiWeb',
  },
];

export function FullSyncDialog({
  isOpen,
  running,
  onCancel,
  onConfirm,
}: {
  isOpen: boolean;
  running: boolean;
  onCancel: () => void;
  onConfirm: (direction: Direction) => void;
}) {
  const [choice, setChoice] = useState<Direction | null>(null);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setChoice(null);
      setConfirming(false);
    }
  }, [isOpen]);

  const selected = OPTIONS.find((o) => o.id === choice);
  const close = () => {
    if (!running) onCancel();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={close}
      title={confirming ? 'Confermi la sync completa?' : 'Serve una sync completa'}
      description={
        confirming
          ? undefined
          : 'Le collezioni di AnkiWeb e di questo server sono cambiate in modo incompatibile (per esempio un tipo di nota modificato su Anki desktop). Scegli quale tenere: l’altra verrà sostituita.'
      }
      footer={
        confirming && selected ? (
          <>
            <Button variant="secondary" onClick={() => setConfirming(false)} disabled={running} className="coarse:h-10">
              Indietro
            </Button>
            <Button variant="destructive" onClick={() => onConfirm(selected.id)} loading={running} className="coarse:h-10">
              {selected.confirm}
            </Button>
          </>
        ) : (
          <>
            <Button variant="secondary" onClick={close} className="coarse:h-10">
              Annulla
            </Button>
            <Button variant="outline" onClick={() => setConfirming(true)} disabled={!choice} className="coarse:h-10">
              Continua
            </Button>
          </>
        )
      }
    >
      {confirming && selected ? (
        <Banner variant="warning" title={selected.title}>
          {selected.detail} Non si può annullare.
        </Banner>
      ) : (
        <div role="radiogroup" aria-label="Collezione da tenere" className="flex flex-col gap-2">
          {OPTIONS.map((o) => (
            <button
              key={o.id}
              type="button"
              role="radio"
              aria-checked={choice === o.id}
              onClick={() => setChoice(o.id)}
              className={cn(
                'flex items-start gap-3 rounded-lg border p-3 text-left hover:bg-accent/50',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                choice === o.id && 'border-ring bg-accent/50',
              )}
            >
              <span className="mt-0.5 text-muted-foreground">{o.icon}</span>
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{o.title}</span>
                <span className="text-xs text-muted-foreground">{o.detail}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </Modal>
  );
}

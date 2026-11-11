/*
 * Anteprima di una carta fuori dallo studio (libreria).
 *
 * Usa `GET /cards/{id}/preview`, che risponde anche per le carte sospese. La carta è isolata nello
 * Shadow DOM di `CardView` come nello studio: il CSS del tipo di nota non tocca l'app. Qui nessun scheduler: solo domanda e risposta, con il tap
 * sulla carta per girarla e i pulsanti audio già gestiti da `study/audio.ts`.
 */
import { useEffect, useState } from 'react';
import { Volume2 } from 'lucide-react';
import { Badge, IconButton, SegmentedControl, Spinner, cn } from '@anki-studio/ui-kit';
import { api } from '../api/client';
import type { CardPreview } from '../api/types';
import { useSettings } from '../settings';
import { CardView } from '../study/CardView';
import { playAv, primeAudio, stopAv } from '../study/audio';
import { ErrorBanner } from './errors';

type Side = 'q' | 'a';

const SIDES: { id: Side; label: string }[] = [
  { id: 'q', label: 'Domanda' },
  { id: 'a', label: 'Risposta' },
];

export function CardPreviewPane({
  cardId,
  reloadKey = 0,
  className,
}: {
  cardId: number;
  /** Cambia dopo una modifica della nota: l'anteprima si ricarica. */
  reloadKey?: number;
  className?: string;
}) {
  const { darkMode } = useSettings();
  const [preview, setPreview] = useState<CardPreview | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [side, setSide] = useState<Side>('q');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .cardPreview(cardId)
      .then((p) => !cancelled && setPreview(p))
      .catch((err: unknown) => !cancelled && setError(err));
    return () => {
      cancelled = true;
    };
  }, [cardId, reloadKey, attempt]);

  // Cambiando carta si riparte dalla domanda, senza il vecchio contenuto sotto lo spinner.
  useEffect(() => {
    setSide('q');
    setPreview(null);
  }, [cardId]);

  // Niente audio che continua a suonare dopo aver cambiato carta o lato, o chiuso il pannello.
  useEffect(() => stopAv, []);
  useEffect(() => stopAv(), [cardId, side]);

  const hasAudio = !!preview && preview.question_av.length + preview.answer_av.length > 0;

  function replay() {
    if (!preview) return;
    primeAudio();
    playAv(side === 'a' ? [...preview.question_av, ...preview.answer_av] : preview.question_av);
  }

  function onPlay(playSide: 'q' | 'a', index: number) {
    if (!preview) return;
    primeAudio();
    const item = (playSide === 'a' ? preview.answer_av : preview.question_av)[index];
    if (item) playAv([item]);
  }

  return (
    <div className={cn('flex flex-col gap-2', className)}>
      <div className="flex items-center justify-between gap-2">
        <SegmentedControl items={SIDES} activeId={side} onChange={setSide} size="sm" aria-label="Lato della carta" />
        <div className="flex items-center gap-1.5">
          {preview?.suspended ? <Badge variant="warning">Sospesa</Badge> : null}
          {hasAudio ? (
            <IconButton label="Riproduci audio" size="sm" onClick={replay} className="coarse:size-9">
              <Volume2 />
            </IconButton>
          ) : null}
        </div>
      </div>

      {error ? (
        <ErrorBanner error={error} onRetry={() => setAttempt((n) => n + 1)} />
      ) : !preview ? (
        <div className="flex min-h-40 items-center justify-center rounded-lg border bg-card text-muted-foreground">
          <Spinner />
        </div>
      ) : (
        <div className="max-h-[min(60dvh,34rem)] overflow-y-auto overscroll-contain rounded-lg border">
          {/* key: ogni carta e ogni lato ripartono da uno Shadow DOM pulito, come nello studio. */}
          <CardView
            key={`${preview.card_id}-${side}`}
            html={side === 'a' ? preview.answer_html : preview.question_html}
            css={preview.css}
            cardClass={preview.card_class}
            dark={darkMode}
            onTap={side === 'q' ? () => setSide('a') : undefined}
            onPlay={onPlay}
            className={cn('flex animate-fade-in flex-col', side === 'q' && 'cursor-pointer')}
          />
        </div>
      )}
    </div>
  );
}

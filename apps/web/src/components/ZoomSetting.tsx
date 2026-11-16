/*
 * Zoom della finestra nell'app desktop (Impostazioni → Aspetto). Nel browser non serve: c'è
 * lo zoom di sistema. Lo applica e lo salva il processo Electron; qui si sceglie un gradino
 * classico o si scrive un valore libero, in percentuale (133) o come moltiplicatore (1,33).
 */
import { useEffect, useState } from 'react';
import { Input, Select } from '@anki-studio/ui-kit';
import type { DesktopInfo } from '../app/desktop';
import { Row } from './SettingsParts';

const PRESETS = [0.67, 0.75, 0.8, 0.9, 1, 1.1, 1.25, 1.33, 1.5, 1.75, 2];
const MIN = 0.5;
const MAX = 3;
const CUSTOM = 'custom';

const percent = (factor: number) => `${Math.round(factor * 100)}`;

/**
 * «133», «133%», «1,33», «1.33», «x1.33» → 1.33. Fino a 5 è un moltiplicatore (nessuno
 * vuole il 5%), oltre è una percentuale. Fuori dai limiti o illeggibile: null.
 */
export function parseZoom(text: string): number | null {
  const cleaned = text.trim().replace(/^[x×]\s*/i, '').replace(/\s*%$/, '').replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(cleaned)) return null;
  const n = Number(cleaned);
  const factor = n <= 5 ? n : n / 100;
  return factor >= MIN && factor <= MAX ? Math.round(factor * 100) / 100 : null;
}

export function ZoomSetting({ desktop }: { desktop: DesktopInfo }) {
  const [zoom, setZoom] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    let alive = true;
    const show = (factor: number) => {
      if (!alive) return;
      setZoom(factor);
      setDraft(percent(factor));
      setInvalid(false);
    };
    void desktop.getZoom().then(show);
    const stop = desktop.onZoomChange(show);
    return () => {
      alive = false;
      stop();
    };
  }, [desktop]);

  // Il valore torna dal processo principale (anche via onZoomChange): è lui la fonte.
  const apply = (factor: number) => {
    void desktop.setZoom(factor).then((applied) => {
      setZoom(applied);
      setDraft(percent(applied));
      setInvalid(false);
    });
  };

  const commitDraft = () => {
    const factor = parseZoom(draft);
    if (factor === null) {
      setInvalid(true);
      return;
    }
    if (factor !== zoom) apply(factor);
    else setDraft(percent(factor));
    setInvalid(false);
  };

  const preset = zoom !== null && PRESETS.includes(zoom) ? String(zoom) : CUSTOM;

  return (
    <Row label="Zoom" hint="Un gradino o un valore libero tra 50 e 300%. Anche con Ctrl +, Ctrl − e Ctrl 0.">
      <div className="flex items-center gap-2">
        <Select
          aria-label="Zoom"
          value={preset}
          disabled={zoom === null}
          onChange={(e) => {
            if (e.target.value !== CUSTOM) apply(Number(e.target.value));
          }}
          className="w-28"
          options={[
            ...PRESETS.map((p) => ({ value: String(p), label: `${percent(p)}%` })),
            { value: CUSTOM, label: 'Personalizzato', disabled: true },
          ]}
        />
        <Input
          aria-label="Zoom personalizzato"
          inputMode="decimal"
          value={draft}
          invalid={invalid}
          disabled={zoom === null}
          onChange={(e) => {
            setDraft(e.target.value);
            setInvalid(false);
          }}
          onBlur={commitDraft}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commitDraft();
            } else if (e.key === 'Escape' && zoom !== null) {
              e.stopPropagation();
              setDraft(percent(zoom));
              setInvalid(false);
            }
          }}
          trailing={<span className="text-xs text-muted-foreground">%</span>}
          title="Percentuale (133) o moltiplicatore (1,33)"
          className="w-20"
          inputClassName="tabular-nums"
        />
      </div>
    </Row>
  );
}

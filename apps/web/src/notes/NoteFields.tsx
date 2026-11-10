/*
 * Campi di una nota, usati da «Aggiungi carta» e «Modifica nota».
 *
 * Perché HTML grezzo in una textarea: è ciò che Anki salva davvero nel campo,
 * quindi niente si perde passando da un editor all'altro (formattazione,
 * `[sound:…]`, `<img>`), e su iPad la tastiera di sistema funziona senza
 * sorprese. Il pulsante «Cloze» sostituisce la scorciatoia Ctrl+Shift+C di Anki.
 */
import { useRef } from 'react';
import { Brackets, Lock } from 'lucide-react';
import { Badge, Button, Field, Input, Textarea } from '@anki-studio/ui-kit';
import type { NotetypeField } from '../api/types';

export function nextClozeNumber(values: Record<string, string>): number {
  let max = 0;
  for (const v of Object.values(values)) {
    for (const m of v.matchAll(/\{\{c(\d+)::/g)) max = Math.max(max, Number(m[1]));
  }
  return max + 1;
}

export function NoteFields({
  fields,
  values,
  onChange,
  isCloze,
  autoFocus,
}: {
  fields: NotetypeField[];
  values: Record<string, string>;
  onChange: (name: string, value: string) => void;
  isCloze: boolean;
  autoFocus?: boolean;
}) {
  const refs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const lastFocused = useRef<string | null>(null);

  function insertCloze() {
    const name = lastFocused.current ?? fields[0]?.name;
    const el = name ? refs.current[name] : null;
    if (!name || !el) return;
    const value = values[name] ?? '';
    const start = el.selectionStart ?? value.length;
    const end = el.selectionEnd ?? value.length;
    const n = nextClozeNumber(values);
    const open = `{{c${n}::`;
    const next = `${value.slice(0, start)}${open}${value.slice(start, end)}}}${value.slice(end)}`;
    onChange(name, next);
    // Senza selezione il cursore va dentro la cloze (si scrive subito il testo nascosto),
    // altrimenti dopo le graffe di chiusura.
    const caret = start === end ? start + open.length : end + open.length + 2;
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(caret, caret);
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {fields.map((f, i) => (
        <Field key={f.name} label={f.name}>
          <Textarea
            ref={(el) => {
              refs.current[f.name] = el;
            }}
            autoResize
            rows={i === 0 ? 3 : 2}
            autoFocus={autoFocus && i === 0}
            value={values[f.name] ?? ''}
            onFocus={() => {
              lastFocused.current = f.name;
            }}
            onChange={(e) => onChange(f.name, e.target.value)}
            autoCapitalize="sentences"
            className="coarse:text-base"
          />
        </Field>
      ))}
      {isCloze ? (
        <div>
          <Button
            variant="outline"
            size="sm"
            icon={<Brackets />}
            // mousedown: il tap non deve togliere il focus (e la selezione) dalla textarea.
            onMouseDown={(e) => e.preventDefault()}
            onClick={insertCloze}
            className="coarse:h-10"
          >
            Cloze
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Tag modificabili in un campo di testo; quelli riservati dell'hub (`hub::bozza`, `agent::…`,
 * `ext::…`) stanno sotto come etichette bloccate, senza «x», e non si possono digitare.
 */
export function TagsInput({
  value,
  onChange,
  reserved = [],
  typedReserved = [],
}: {
  value: string;
  onChange: (value: string) => void;
  reserved?: string[];
  typedReserved?: string[];
}) {
  return (
    <div className="flex flex-col gap-2">
      <Field
        label="Tag"
        hint="Separati da spazi"
        error={typedReserved.length > 0 ? `${typedReserved.join(', ')}: i tag agent::, ext:: e hub:: li gestisce l’app e non si possono aggiungere.` : undefined}
      >
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          size="lg"
        />
      </Field>
      {reserved.length > 0 ? (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Tag riservati, non modificabili">
          {reserved.map((t) => (
            <Badge key={t} variant="secondary" icon={<Lock />} title="Tag gestito dall’app: non si può togliere da qui">
              {t}
            </Badge>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export const parseTags = (value: string) => value.split(/\s+/).filter(Boolean);

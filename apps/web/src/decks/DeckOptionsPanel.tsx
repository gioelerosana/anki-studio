/*
 * Opzioni di un mazzo, come la schermata di Anki desktop ridotta a ciò che serve davvero:
 * preset, limiti giornalieri (preset · questo mazzo · solo oggi), passi, seppellimento, timer.
 *
 * Perché un modulo con «Salva» e non salvataggi a ogni tocco: in Anki le opzioni si salvano
 * insieme e il salvataggio è un'operazione annullabile; salvare a ogni cifra digitata
 * riempirebbe lo stack di «Annulla» e la sync. I valori li applica lo scheduler di Anki:
 * qui si scrivono e basta.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { ChevronLeft } from 'lucide-react';
import { Banner, Button, Input, SegmentedControl, Select, Spinner, Switch, cn } from '@anki-studio/ui-kit';
import { api, ApiError } from '../api/client';
import type { DeckOptions, DeckOptionsInput, DeckPreset } from '../api/types';
import { plural } from '../app/format';
import { navigate } from '../app/route';
import { useToast } from '../app/toasts';
import { Group, Row } from '../components/SettingsParts';
import { formatSteps, parseSteps } from './steps';

type LimitScope = 'preset' | 'deck' | 'today';

const SCOPE_ITEMS: { id: LimitScope; label: string }[] = [
  { id: 'preset', label: 'Preset' },
  { id: 'deck', label: 'Questo mazzo' },
  { id: 'today', label: 'Solo oggi' },
];

const SCOPE_HINT: Record<LimitScope, string> = {
  preset: 'Valgono per tutti i mazzi con questo preset.',
  deck: 'Solo per questo mazzo, al posto di quelli del preset. Vuoto = come il preset.',
  today: 'Solo per oggi: domani si torna ai limiti di prima. Vuoto = nessun cambio.',
};

/** Il modulo tiene stringhe: un campo vuoto o a metà non deve diventare 0 mentre si scrive. */
interface Draft {
  presetId: number;
  newPerDay: string;
  reviewsPerDay: string;
  deckNew: string;
  deckReview: string;
  todayNew: string;
  todayReview: string;
  learnSteps: string;
  relearnSteps: string;
  maxAnswer: string;
  buryNew: boolean;
  buryReview: boolean;
  ignoreReviewLimit: boolean;
  parentLimits: boolean;
  /** In percento ("90"), come la mostra Anki. */
  retention: string;
}

const str = (n: number | null | undefined) => (n === null || n === undefined ? '' : String(n));

function presetFields(p: DeckPreset): Pick<Draft, 'newPerDay' | 'reviewsPerDay' | 'learnSteps' | 'relearnSteps' | 'maxAnswer' | 'buryNew' | 'buryReview' | 'retention'> {
  return {
    newPerDay: String(p.new_per_day),
    reviewsPerDay: String(p.reviews_per_day),
    learnSteps: formatSteps(p.learn_steps_min),
    relearnSteps: formatSteps(p.relearn_steps_min),
    maxAnswer: String(p.max_answer_seconds),
    buryNew: p.bury_new_siblings,
    buryReview: p.bury_review_siblings,
    retention: String(Math.round(p.desired_retention * 100)),
  };
}

function toDraft(o: DeckOptions): Draft {
  const preset = o.presets.find((p) => p.id === o.preset_id);
  return {
    presetId: o.preset_id ?? 0,
    ...(preset
      ? presetFields(preset)
      : {
          newPerDay: str(o.new_per_day),
          reviewsPerDay: str(o.reviews_per_day),
          learnSteps: formatSteps(o.learn_steps_min),
          relearnSteps: formatSteps(o.relearn_steps_min),
          maxAnswer: str(o.max_answer_seconds),
          buryNew: o.bury_new_siblings,
          buryReview: o.bury_review_siblings,
          retention: o.desired_retention ? String(Math.round(o.desired_retention * 100)) : '90',
        }),
    deckNew: str(o.deck_limits.new),
    deckReview: str(o.deck_limits.review),
    todayNew: str(o.deck_limits.new_today),
    todayReview: str(o.deck_limits.review_today),
    ignoreReviewLimit: o.new_cards_ignore_review_limit,
    parentLimits: o.apply_all_parent_limits,
  };
}

/** Intero 0–9999, oppure `null` per il vuoto se `optional`; `undefined` = non valido. */
function parseLimit(text: string, optional: boolean): number | null | undefined {
  const t = text.trim();
  if (t === '') return optional ? null : undefined;
  if (!/^\d+$/.test(t)) return undefined;
  const n = Number(t);
  return n <= 9999 ? n : undefined;
}

type Errors = Partial<Record<keyof Draft, string>>;

function validate(d: Draft, fsrs: boolean): { input: DeckOptionsInput | null; errors: Errors } {
  const errors: Errors = {};
  const limit = (key: keyof Draft, optional: boolean) => {
    const v = parseLimit(d[key] as string, optional);
    if (v === undefined) errors[key] = 'Un numero da 0 a 9999';
    return v ?? null;
  };
  const newPerDay = limit('newPerDay', false);
  const reviewsPerDay = limit('reviewsPerDay', false);
  const deckLimits = {
    new: limit('deckNew', true),
    review: limit('deckReview', true),
    new_today: limit('todayNew', true),
    review_today: limit('todayReview', true),
  };
  const learn = parseSteps(d.learnSteps);
  if (!learn) errors.learnSteps = 'Passi come «1m 10m 1h 1d»';
  const relearn = parseSteps(d.relearnSteps);
  if (!relearn) errors.relearnSteps = 'Passi come «10m 1d»';
  const maxAnswer = /^\d+$/.test(d.maxAnswer.trim()) ? Number(d.maxAnswer) : NaN;
  if (!(maxAnswer >= 1 && maxAnswer <= 7200)) errors.maxAnswer = 'Da 1 a 7200 secondi';
  let retention: number | null = null;
  if (fsrs) {
    const r = Number(d.retention.replace(',', '.'));
    if (!(r >= 70 && r <= 99)) errors.retention = 'Dal 70 al 99%';
    else retention = Math.round(r * 100) / 10_000;
  }
  if (Object.keys(errors).length > 0) return { input: null, errors };
  return {
    errors,
    input: {
      preset_id: d.presetId,
      new_per_day: newPerDay!,
      reviews_per_day: reviewsPerDay!,
      deck_limits: deckLimits,
      learn_steps_min: learn!,
      relearn_steps_min: relearn!,
      max_answer_seconds: maxAnswer,
      bury_new_siblings: d.buryNew,
      bury_review_siblings: d.buryReview,
      new_cards_ignore_review_limit: d.ignoreReviewLimit,
      apply_all_parent_limits: d.parentLimits,
      desired_retention: retention,
    },
  };
}

function sameDraft(a: Draft, b: Draft): boolean {
  return (Object.keys(a) as (keyof Draft)[]).every((k) => String(a[k]).trim() === String(b[k]).trim());
}

/** La scheda con cui aprire: quella di Anki, cioè il limite più specifico già attivo. */
function initialScope(o: DeckOptions): LimitScope {
  const l = o.deck_limits;
  if (l.new_today !== null || l.review_today !== null) return 'today';
  if (l.new !== null || l.review !== null) return 'deck';
  return 'preset';
}

export function DeckOptionsPanel({ deckId }: { deckId: number }) {
  const toast = useToast();
  const [options, setOptions] = useState<DeckOptions | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [scope, setScope] = useState<LimitScope>('preset');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [showErrors, setShowErrors] = useState(false);

  useEffect(() => {
    let alive = true;
    setOptions(null);
    setLoadError(null);
    api
      .deckOptions(deckId)
      .then((o) => {
        if (!alive) return;
        setOptions(o);
        setDraft(toDraft(o));
        setScope(initialScope(o));
      })
      .catch((err) => alive && setLoadError(err instanceof ApiError && err.status === 404 ? 'Mazzo non trovato' : err instanceof Error ? err.message : 'Errore'));
    return () => {
      alive = false;
    };
  }, [deckId]);

  const base = useMemo(() => (options ? toDraft(options) : null), [options]);
  const dirty = !!draft && !!base && !sameDraft(draft, base);
  const checked = draft && options ? validate(draft, options.fsrs) : null;
  const errors = showErrors && checked ? checked.errors : {};

  const back = (
    <Button variant="ghost" size="sm" icon={<ChevronLeft />} onClick={() => navigate({ name: 'settings', section: 'decks' })} className="-ml-1.5 self-start pl-1">
      Tutti i mazzi
    </Button>
  );

  if (loadError) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <Banner variant="error">{loadError}</Banner>
      </div>
    );
  }
  if (!options || !draft || !base) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <div className="flex justify-center p-8 text-muted-foreground">
          <Spinner />
        </div>
      </div>
    );
  }

  const title = options.deck_name.replaceAll('::', ' › ');
  if (options.filtered) {
    return (
      <div className="flex flex-col gap-4">
        {back}
        <h2 className="text-base font-semibold">{title}</h2>
        <Banner variant="info">È un mazzo filtrato: le sue opzioni si cambiano da Anki desktop.</Banner>
      </div>
    );
  }

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => (d ? { ...d, [key]: value } : d));
  const preset = options.presets.find((p) => p.id === draft.presetId);
  const sharedWith = preset ? preset.use_count - (draft.presetId === options.preset_id ? 1 : 0) : 0;

  function choosePreset(id: number) {
    const p = options!.presets.find((x) => x.id === id);
    if (p) setDraft((d) => (d ? { ...d, presetId: id, ...presetFields(p) } : d));
  }

  async function save() {
    if (!checked?.input) {
      setShowErrors(true);
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const o = await api.saveDeckOptions(deckId, checked.input);
      setOptions(o);
      setDraft(toDraft(o));
      setShowErrors(false);
      toast('success', 'Opzioni salvate');
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Salvataggio non riuscito');
    } finally {
      setSaving(false);
    }
  }

  // I due campi della scheda scelta: nel preset sono obbligatori, negli altri il vuoto vuol dire «come prima».
  const limitKeys: Record<LimitScope, [keyof Draft, keyof Draft]> = {
    preset: ['newPerDay', 'reviewsPerDay'],
    deck: ['deckNew', 'deckReview'],
    today: ['todayNew', 'todayReview'],
  };
  const [newKey, reviewKey] = limitKeys[scope];
  const fallback = (key: 'new' | 'review') =>
    scope === 'today' ? (key === 'new' ? draft.deckNew || draft.newPerDay : draft.deckReview || draft.reviewsPerDay) : key === 'new' ? draft.newPerDay : draft.reviewsPerDay;
  const scopeHasValue = (s: LimitScope) => s !== 'preset' && (draft[limitKeys[s][0]] !== '' || draft[limitKeys[s][1]] !== '');

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        {back}
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="text-2xs text-muted-foreground">I limiti e i passi li applica lo scheduler di Anki, come sul computer.</p>
      </div>

      <Group title="Preset">
        <Row label="Opzioni di" hint={preset && sharedWith > 0 ? `Condiviso con ${plural(sharedWith, 'altro mazzo', 'altri mazzi')}` : 'Usato solo da questo mazzo'}>
          <Select
            aria-label="Preset"
            value={String(draft.presetId)}
            onChange={(e) => choosePreset(Number(e.target.value))}
            options={options.presets.map((p) => ({ value: String(p.id), label: p.name }))}
            className="w-44 coarse:h-10"
          />
        </Row>
      </Group>

      <Group title="Limiti giornalieri">
        <div className="flex flex-col gap-2 border-b px-4 py-3">
          <SegmentedControl
            items={SCOPE_ITEMS.map((i) => ({ ...i, label: scopeHasValue(i.id) ? `${i.label} •` : i.label }))}
            activeId={scope}
            onChange={setScope}
            aria-label="A cosa si applicano i limiti"
            className="self-start max-sm:self-stretch"
          />
          <p className="text-2xs text-muted-foreground">
            {SCOPE_HINT[scope]}
            {scope === 'preset' && sharedWith > 0 ? ' Per cambiarli solo qui usa «Questo mazzo».' : ''}
          </p>
        </div>
        <Row label="Nuove carte al giorno">
          <NumberInput label="Nuove carte al giorno" value={draft[newKey] as string} placeholder={scope === 'preset' ? undefined : fallback('new')} error={errors[newKey]} onChange={(v) => set(newKey, v)} />
        </Row>
        <Row label="Ripassi al giorno">
          <NumberInput label="Ripassi al giorno" value={draft[reviewKey] as string} placeholder={scope === 'preset' ? undefined : fallback('review')} error={errors[reviewKey]} onChange={(v) => set(reviewKey, v)} />
        </Row>
        <Row label="Le nuove ignorano il limite dei ripassi" hint="Le nuove si mostrano anche se i ripassi hanno raggiunto il limite. Vale per tutti i mazzi.">
          <Switch checked={draft.ignoreReviewLimit} onCheckedChange={(v) => set('ignoreReviewLimit', v)} aria-label="Le nuove ignorano il limite dei ripassi" />
        </Row>
        <Row label="Rispetta i limiti dei mazzi padre" hint="Anche aprendo un sottomazzo. Vale per tutti i mazzi.">
          <Switch checked={draft.parentLimits} onCheckedChange={(v) => set('parentLimits', v)} aria-label="Rispetta i limiti dei mazzi padre" />
        </Row>
      </Group>

      <Group title="Apprendimento">
        <Row label="Passi delle nuove" hint="Es. «1m 10m»: s, m, h, d.">
          <StepsInput label="Passi delle nuove" value={draft.learnSteps} error={errors.learnSteps} onChange={(v) => set('learnSteps', v)} />
        </Row>
        <Row label="Passi delle dimenticate" hint="Dopo «Di nuovo» su una carta in ripasso.">
          <StepsInput label="Passi delle dimenticate" value={draft.relearnSteps} error={errors.relearnSteps} onChange={(v) => set('relearnSteps', v)} />
        </Row>
        {options.fsrs ? (
          <Row label="Ritenzione desiderata" hint="FSRS: più alta, più ripassi.">
            <NumberInput label="Ritenzione desiderata" value={draft.retention} error={errors.retention} unit="%" onChange={(v) => set('retention', v)} />
          </Row>
        ) : null}
      </Group>

      <Group title="Seppellisci">
        <Row label="Carte sorelle nuove" hint="Rimanda a domani le altre carte nuove della stessa nota.">
          <Switch checked={draft.buryNew} onCheckedChange={(v) => set('buryNew', v)} aria-label="Seppellisci le carte sorelle nuove" />
        </Row>
        <Row label="Carte sorelle in ripasso" hint="Rimanda a domani gli altri ripassi della stessa nota.">
          <Switch checked={draft.buryReview} onCheckedChange={(v) => set('buryReview', v)} aria-label="Seppellisci le carte sorelle in ripasso" />
        </Row>
      </Group>

      <Group title="Timer">
        <Row label="Tempo massimo di risposta" hint="Oltre, nelle statistiche conta come questo valore.">
          <NumberInput label="Tempo massimo di risposta" value={draft.maxAnswer} error={errors.maxAnswer} unit="s" onChange={(v) => set('maxAnswer', v)} />
        </Row>
      </Group>

      {saveError ? <Banner variant="error">{saveError}</Banner> : null}

      {/* In fondo e sempre a portata di pollice: la pagina scorre, la barra resta. */}
      <div className="sticky bottom-0 -mx-1 flex items-center justify-end gap-2 bg-background/90 px-1 py-3 backdrop-blur-sm pb-[max(0.75rem,env(safe-area-inset-bottom))]">
        {showErrors && checked && !checked.input ? <span className="mr-auto text-2xs text-error-foreground">Controlla i campi evidenziati</span> : null}
        <Button variant="secondary" disabled={!dirty || saving} onClick={() => { setDraft(base); setShowErrors(false); setSaveError(null); }} className="coarse:h-10">
          Annulla modifiche
        </Button>
        <Button disabled={!dirty} loading={saving} onClick={() => void save()} className="coarse:h-10">
          Salva
        </Button>
      </div>
    </div>
  );
}

function FieldError({ children }: { children?: ReactNode }) {
  return children ? <span className="mt-1 block text-right text-2xs text-error-foreground">{children}</span> : null;
}

function NumberInput({
  label,
  value,
  placeholder,
  unit,
  error,
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  unit?: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col items-end">
      <Input
        aria-label={label}
        inputMode="numeric"
        // text e non number: niente frecce che scattano con la rotella e il vuoto resta vuoto
        type="text"
        value={value}
        placeholder={placeholder}
        invalid={!!error}
        onChange={(e) => onChange(e.target.value)}
        trailing={unit ? <span className="text-muted-foreground">{unit}</span> : undefined}
        className="w-24 coarse:h-10"
        inputClassName="text-right tabular-nums"
      />
      <FieldError>{error}</FieldError>
    </div>
  );
}

function StepsInput({ label, value, error, onChange }: { label: string; value: string; error?: string; onChange: (value: string) => void }) {
  return (
    <div className="flex flex-col items-end">
      <Input
        aria-label={label}
        mono
        value={value}
        invalid={!!error}
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        className={cn('w-40 coarse:h-10 max-sm:w-32')}
      />
      <FieldError>{error}</FieldError>
    </div>
  );
}

import { describe, expect, it } from 'vitest';
import { canUndo, statusLabel, summarizeUndo, undoExplanation, undoLabel } from './operations';

describe('stato dell’operazione', () => {
  it('applicata e parziale si possono (ri)provare, annullata no', () => {
    expect(canUndo({ status: 'applied' })).toBe(true);
    expect(canUndo({ status: 'partial' })).toBe(true);
    expect(canUndo({ status: 'undone' })).toBe(false);
    expect(undoLabel({ status: 'applied' })).toBe('Annulla');
    expect(undoLabel({ status: 'partial' })).toBe('Riprova');
  });

  it('nessun badge per le applicate', () => {
    expect(statusLabel('applied')).toBeNull();
    expect(statusLabel('partial')).toBe('Parziale');
    expect(statusLabel('undone')).toBe('Annullata');
  });
});

describe('undoExplanation', () => {
  it('dice cosa succede alle note toccate nel frattempo', () => {
    for (const kind of ['add_notes', 'update_note', 'create_deck'] as const) {
      const lines = undoExplanation(kind);
      expect(lines).toHaveLength(2);
      expect(lines[1]).toMatch(/modificato o studiato/);
    }
    expect(undoExplanation('add_notes')[0]).toMatch(/cancellate/);
    expect(undoExplanation('update_note')[0]).toMatch(/torna com’era/);
  });
});

describe('summarizeUndo', () => {
  it('esito completo: singolari e plurali, nessuna riga di saltate', () => {
    const r = summarizeUndo({ operation_id: 'a', status: 'undone', restored: 1, deleted: 3, skipped: [] });
    expect(r.tone).toBe('success');
    expect(r.title).toBe('Operazione annullata');
    expect(r.lines).toEqual(['1 nota ripristinata.', '3 note cancellate.']);
    expect(r.short).toBe('Annullata: 1 ripristinata, 3 cancellate');
  });

  it('esito parziale: i motivi uguali si raggruppano', () => {
    const r = summarizeUndo({
      operation_id: 'a',
      status: 'partial',
      restored: 0,
      deleted: 2,
      skipped: [
        { note_id: 1, reason: 'studiata dopo la creazione' },
        { note_id: 2, reason: 'modificata dopo la creazione' },
        { note_id: 3, reason: 'studiata dopo la creazione' },
      ],
    });
    expect(r.tone).toBe('warning');
    expect(r.title).toBe('Annullata in parte');
    expect(r.lines).toEqual(['2 note cancellate.', 'Saltate 2: studiata dopo la creazione', 'Saltata: modificata dopo la creazione']);
    expect(r.short).toBe('Annullata in parte: 2 cancellate, 3 saltate');
  });

  it('esito senza modifiche', () => {
    const r = summarizeUndo({ operation_id: 'a', status: 'partial', restored: 0, deleted: 0, skipped: [{ note_id: null, reason: 'mazzo non vuoto' }] });
    expect(r.lines).toEqual(['Nessuna nota è cambiata.', 'Saltata: mazzo non vuoto']);
    expect(r.short).toBe('Annullata in parte: 1 saltata');
    expect(summarizeUndo({ operation_id: 'a', status: 'undone', restored: 0, deleted: 0, skipped: [] }).short).toBe('Annullata: nessuna nota cambiata');
  });
});

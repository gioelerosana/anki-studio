import { describe, expect, it } from 'vitest';
import { formatSteps, parseSteps } from './steps';

describe('parseSteps', () => {
  it('capisce le unità di Anki, senza unità sono minuti', () => {
    expect(parseSteps('1m 10m 1h 1d')).toEqual([1, 10, 60, 1440]);
    expect(parseSteps('10 30s')).toEqual([10, 0.5]);
    expect(parseSteps('1,5h')).toEqual([90]);
    expect(parseSteps('1m, 10m')).toEqual([1, 10]);
  });

  it('vuoto = nessun passo', () => {
    expect(parseSteps('  ')).toEqual([]);
  });

  it('rifiuta testo, zero e passi oltre un anno', () => {
    expect(parseSteps('dieci')).toBeNull();
    expect(parseSteps('0m')).toBeNull();
    expect(parseSteps('400d')).toBeNull();
  });
});

describe('formatSteps', () => {
  it('sceglie l’unità più grande intera', () => {
    expect(formatSteps([1, 10, 60, 90, 1440, 0.5])).toBe('1m 10m 1h 90m 1d 30s');
  });

  it('andata e ritorno', () => {
    expect(parseSteps(formatSteps([1, 10, 2880]))).toEqual([1, 10, 2880]);
  });
});

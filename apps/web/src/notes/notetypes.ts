/*
 * Tipi di nota in memoria per qualche minuto.
 *
 * Perché: la libreria apre l'editor di una nota a ogni selezione, e l'elenco dei
 * tipi (con i campi in ordine) cambia di rado. Una richiesta per tocco sarebbe sprecata.
 */
import { api } from '../api/client';
import type { Notetype } from '../api/types';

const TTL_MS = 5 * 60 * 1000;
let cached: { at: number; promise: Promise<Notetype[]> } | null = null;

export function getNotetypes(): Promise<Notetype[]> {
  if (cached && Date.now() - cached.at < TTL_MS) return cached.promise;
  const promise = api.notetypes();
  cached = { at: Date.now(), promise };
  // un errore non resta in cache: il prossimo tentativo rifà la richiesta
  promise.catch(() => {
    if (cached?.promise === promise) cached = null;
  });
  return promise;
}

/*
 * Riproduzione di `[sound:…]` e `{{tts …}}` delle carte.
 *
 * Perché un solo <audio> riusato e `primeAudio()`: iPadOS lascia partire
 * l'audio senza un gesto solo su un elemento che ha già suonato dentro un
 * gesto. Il tap sul mazzo (o sulla carta) "sblocca" l'elemento e la sintesi
 * vocale, così l'autoplay delle carte successive funziona anche nella PWA.
 *
 * Con il telecomando la pagina del computer può non aver mai ricevuto un gesto (ricaricata,
 * poi mazzo aperto dal telefono): il browser blocca audio e sintesi vocale e non c'è modo di
 * sbloccarli da remoto. `useAudioUnlocked()` lo dice, così la PWA chiede un clic sulla
 * pagina; il primo clic o tasto ovunque sblocca (listener globale qui sotto).
 */
import { useSyncExternalStore } from 'react';
import type { AvItem } from '../api/types';

// WAV di 1 campione di silenzio: basta a sbloccare l'elemento.
const SILENCE =
  'data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAIlYAAESsAAACABAAZGF0YQIAAAAAAA==';

let element: HTMLAudioElement | null = null;
let queue: AvItem[] = [];
let generation = 0;
let primed = false;

function audio(): HTMLAudioElement {
  if (!element) {
    element = new Audio();
    element.preload = 'auto';
  }
  return element;
}

const speech = (): SpeechSynthesis | null => ('speechSynthesis' in window ? window.speechSynthesis : null);

/** Da chiamare dentro un gesto dell'utente (tap, clic, tasto). Idempotente. */
export function primeAudio(): void {
  if (primed) return;
  primed = true;
  const el = audio();
  el.src = SILENCE;
  el.play().catch(() => {
    primed = false;
  });
  const synth = speech();
  if (synth) {
    const u = new SpeechSynthesisUtterance('');
    u.volume = 0;
    synth.speak(u);
  }
}

/*
 * Audio sbloccato? `navigator.userActivation.hasBeenActive` è il criterio del browser
 * (Chrome, Safari 16.4+, Firefox 120+): vero dopo il primo gesto sulla pagina. Dove
 * manca l'API si assume sbloccato, per non chiedere un clic che non serve.
 */
const unlockListeners = new Set<() => void>();
let unlocked = (() => {
  const activation = (navigator as Navigator & { userActivation?: { hasBeenActive: boolean } }).userActivation;
  return activation ? activation.hasBeenActive : true;
})();

function onGesture() {
  primeAudio();
  if (unlocked) return;
  unlocked = true;
  unlockListeners.forEach((l) => l());
}
// in cattura: anche un clic che un componente ferma con stopPropagation conta come gesto
// (sul touch il gesto che vale per il browser è il click, non il pointerdown)
window.addEventListener('pointerdown', onGesture, true);
window.addEventListener('click', onGesture, true);
window.addEventListener('keydown', onGesture, true);

/** Falso finché la pagina non ha ricevuto un gesto: il browser blocca audio e voce. */
export function useAudioUnlocked(): boolean {
  return useSyncExternalStore(
    (listener) => {
      unlockListeners.add(listener);
      return () => unlockListeners.delete(listener);
    },
    () => unlocked,
  );
}

function pickVoice(lang: string | null | undefined): SpeechSynthesisVoice | undefined {
  const synth = speech();
  if (!synth || !lang) return undefined;
  const wanted = lang.replace('_', '-').toLowerCase();
  const voices = synth.getVoices();
  return (
    voices.find((v) => v.lang.toLowerCase() === wanted) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(wanted.split('-')[0]))
  );
}

function playNext(gen: number): void {
  if (gen !== generation) return;
  const item = queue.shift();
  if (!item) return;
  if (item.type === 'sound' && item.url) {
    const el = audio();
    el.onended = () => playNext(gen);
    el.onerror = () => playNext(gen);
    el.src = item.url;
    el.play().catch(() => playNext(gen));
  } else if (item.type === 'tts' && item.text) {
    const synth = speech();
    if (!synth) return playNext(gen);
    const u = new SpeechSynthesisUtterance(item.text);
    if (item.lang) u.lang = item.lang.replace('_', '-');
    const voice = pickVoice(item.lang);
    if (voice) u.voice = voice;
    if (item.speed) u.rate = Math.min(Math.max(item.speed, 0.1), 4);
    u.onend = () => playNext(gen);
    u.onerror = () => playNext(gen);
    synth.speak(u);
  } else {
    playNext(gen);
  }
}

/** Interrompe ciò che sta suonando e riproduce `items` in sequenza. */
export function playAv(items: AvItem[]): void {
  stopAv();
  queue = [...items];
  playNext(generation);
}

export function stopAv(): void {
  generation += 1;
  queue = [];
  if (element) {
    element.onended = null;
    element.onerror = null;
    element.pause();
  }
  speech()?.cancel();
}

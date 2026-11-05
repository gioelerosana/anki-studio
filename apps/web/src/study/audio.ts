/*
 * Riproduzione di `[sound:…]` e `{{tts …}}` delle carte.
 *
 * Perché un solo <audio> riusato e `primeAudio()`: iPadOS lascia partire
 * l'audio senza un gesto solo su un elemento che ha già suonato dentro un
 * gesto. Il tap sul mazzo (o sulla carta) "sblocca" l'elemento e la sintesi
 * vocale, così l'autoplay delle carte successive funziona anche nella PWA.
 */
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

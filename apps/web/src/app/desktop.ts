/*
 * L'app desktop (apps/desktop, Electron) espone `window.ankiDesktop` dal suo preload. Lì il
 * backend gira sul computer con una copia locale della collezione e l'accesso è la chiave
 * dell'avvio, non Authentik: niente «Esci», e le informazioni dicono dove stanno i dati.
 */
export interface DesktopInfo {
  /** Build del pacchetto Arch: r<numero di commit>.g<hash> ("dev" fuori dal pacchetto). */
  version: string;
  revision: string;
  /** Cartella della collezione locale, es. ~/.local/share/anki-studio. */
  dataDir: string;
}

declare global {
  interface Window {
    ankiDesktop?: DesktopInfo;
  }
}

export const desktop: DesktopInfo | null = typeof window !== 'undefined' ? (window.ankiDesktop ?? null) : null;

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
  /** Comandi per la barra del titolo, che nel desktop disegna la PWA (AppHeaderBar). */
  minimize: () => void;
  maximize: () => void;
  close: () => void;
  isMaximized: () => Promise<boolean>;
  /** Restituisce la funzione per smettere di ascoltare. */
  onMaximizedChange: (callback: (maximized: boolean) => void) => () => void;
  /** Zoom della finestra (1 = 100%), salvato dal processo principale tra un avvio e l'altro. */
  getZoom: () => Promise<number>;
  /** Restituisce il valore applicato, già riportato nei limiti (50–300%). */
  setZoom: (factor: number) => Promise<number>;
  /** Anche le scorciatoie (Ctrl +/−/0, Ctrl + rotella) cambiano lo zoom. */
  onZoomChange: (callback: (factor: number) => void) => () => void;
}

declare global {
  interface Window {
    ankiDesktop?: DesktopInfo;
  }
}

export const desktop: DesktopInfo | null = typeof window !== 'undefined' ? (window.ankiDesktop ?? null) : null;

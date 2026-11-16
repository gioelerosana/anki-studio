/*
 * App desktop di Anki Studio (Linux, Electron di sistema).
 *
 * È la stessa PWA, ma con una copia locale della collezione: questo processo avvia il
 * backend FastAPI (con il motore ufficiale di Anki) su 127.0.0.1, con i dati in
 * ~/.local/share/anki-studio, e apre la finestra su di lui. Si studia anche offline; la
 * sync con AnkiWeb (all'avvio, ogni 10 minuti, alla chiusura e a richiesta) è quella che
 * tiene allineati questo computer, il server cloud e gli altri dispositivi. Una collezione
 * Anki si sincronizza con un solo server: il server cloud è a sua volta un client di
 * AnkiWeb, quindi l'incontro avviene lì.
 *
 * Al posto del login con Authentik c'è una chiave casuale nuova a ogni avvio: la riceve il
 * backend dall'ambiente e la aggiunge questo processo a ogni richiesta della finestra
 * (header X-Anki-Desktop-Key). Così una pagina qualunque del browser, che pure raggiunge
 * localhost, non può leggere né modificare la collezione.
 */
import { app, BrowserWindow, dialog, ipcMain, Menu, nativeTheme, session, shell } from 'electron';
import { spawn, type ChildProcess } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

const APP_ID = 'org.joel.anki_studio';
// Porta fissa e non casuale: l'origine (http://127.0.0.1:<porta>) è quella che conserva le
// preferenze della PWA (tema, ecc. in localStorage) e il service worker da un avvio all'altro.
const DEFAULT_PORT = 47613;
const HOST = '127.0.0.1';
const DESKTOP_HEADER = 'X-Anki-Desktop-Key';
const HEALTH_TIMEOUT_MS = 90_000;
// Allo spegnimento il backend aspetta la sync in corso e ne fa un'ultima (app/main.py): fino
// a ~75 s nel caso peggiore. Si aspetta con margine; il SIGKILL è l'ultima risorsa (SQLite
// resta integro, ma l'ultima sync salta e si recupera al prossimo avvio).
const SHUTDOWN_TIMEOUT_MS = 120_000;
const EXTERNAL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:']);
const DARK_BACKGROUND = '#0a0a0a';
const LIGHT_BACKGROUND = '#fcfcfc';

// Stessa struttura del repository, sia qui sia nel pacchetto (/usr/lib/anki-studio):
// apps/desktop/dist/main.js → backend/, backend/.venv, apps/web/dist.
const root = path.resolve(__dirname, '../../..');
const backendDir = process.env.ANKI_STUDIO_BACKEND_DIR ?? path.join(root, 'backend');
const python = process.env.ANKI_STUDIO_PYTHON ?? path.join(backendDir, '.venv/bin/python');
const webDir = process.env.ANKI_STUDIO_WEB_DIR ?? path.join(root, 'apps/web/dist');
const dataHome = process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local/share');
const dataDir = process.env.ANKI_DATA_DIR ?? path.join(dataHome, 'anki-studio');
const port = Number(process.env.ANKI_STUDIO_PORT ?? DEFAULT_PORT);
const origin = `http://${HOST}:${port}`;
const key = randomBytes(32).toString('base64url');

interface BuildInfo {
  /** r<numero di commit>.g<hash>, scritto dal PKGBUILD. */
  version: string;
  revision: string;
}

function readBuildInfo(): BuildInfo {
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(__dirname, '../version.json'), 'utf8')) as Partial<BuildInfo>;
    return { version: String(raw.version ?? 'dev'), revision: String(raw.revision ?? '') };
  } catch {
    return { version: 'dev', revision: '' };
  }
}

const build = readBuildInfo();
let backend: ChildProcess | null = null;
let backendExited = false;
let quitting = false;
let window: BrowserWindow | null = null;

app.setName('Anki Studio');
// WM_CLASS e app_id su Wayland: lo stesso nome del file .desktop, per l'icona giusta nel dock
app.commandLine.appendSwitch('class', APP_ID);
if (process.platform === 'linux') app.setDesktopName(`${APP_ID}.desktop`);

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });
  void start();
}

async function start(): Promise<void> {
  await app.whenReady();
  Menu.setApplicationMenu(null);
  ipcMain.on('desktop:info', (event) => {
    event.returnValue = { version: build.version, revision: build.revision, dataDir };
  });
  // Controlli della barra del titolo disegnata dall'app, sulla finestra che li manda
  const sender = (event: Electron.IpcMainEvent | Electron.IpcMainInvokeEvent) =>
    BrowserWindow.fromWebContents(event.sender);
  ipcMain.on('window:minimize', (event) => sender(event)?.minimize());
  ipcMain.on('window:maximize', (event) => {
    const w = sender(event);
    if (!w) return;
    if (w.isMaximized()) w.unmaximize();
    else w.maximize();
  });
  ipcMain.on('window:close', (event) => sender(event)?.close());
  ipcMain.handle('window:isMaximized', (event) => sender(event)?.isMaximized() ?? false);

  const logPath = path.join(dataDir, 'desktop.log');
  try {
    fs.mkdirSync(dataDir, { recursive: true, mode: 0o700 });
    startBackend(logPath);
    await waitHealthy();
  } catch (error: unknown) {
    const detail = error instanceof Error ? error.message : String(error);
    await dialog.showMessageBox({
      type: 'error',
      title: 'Anki Studio',
      message: 'Anki Studio non è riuscito ad aprire la collezione locale.',
      detail: `${detail}\n\nDettagli nel log: ${logPath}`,
    });
    quitting = true;
    await stopBackend();
    app.exit(1);
    return;
  }

  // La chiave va su ogni richiesta della finestra verso il backend, WebSocket del
  // telecomando compreso; verso altri siti mai.
  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: [`${origin}/*`, `ws://${HOST}:${port}/*`] },
    (details, callback) => {
      callback({ requestHeaders: { ...details.requestHeaders, [DESKTOP_HEADER]: key } });
    },
  );
  createWindow();
}

function startBackend(logPath: string): void {
  if (!fs.existsSync(python)) throw new Error(`Python del backend non trovato: ${python}`);
  if (!fs.existsSync(path.join(webDir, 'index.html'))) throw new Error(`Build della PWA non trovata: ${webDir}`);
  const log = fs.openSync(logPath, 'w', 0o600);
  backend = spawn(
    python,
    [
      '-m', 'uvicorn', 'app.main:create_app', '--factory',
      '--app-dir', backendDir,
      '--host', HOST,
      '--port', String(port),
      '--timeout-graceful-shutdown', '30',
      '--no-access-log',
    ],
    {
      cwd: dataDir,
      stdio: ['ignore', log, log],
      env: {
        // prima l'ambiente dell'utente (es. ANKI_AUTO_SYNC_MINUTES), poi ciò che il
        // desktop decide da sé e non va cambiato
        ...process.env,
        ANKI_DATA_DIR: dataDir,
        ANKI_WEB_DIR: webDir,
        ANKI_DESKTOP_KEY: key,
        // niente server MCP sul desktop: gli agenti parlano con il server cloud
        ANKI_MCP_ENABLED: 'false',
        ANKI_DEV_LOGIN: 'false',
        ANKI_OIDC_ISSUER: '',
        ANKI_API_TOKEN: '',
        ANKI_STUDIO_VERSION: build.version,
        ANKI_STUDIO_REVISION: build.revision,
        PYTHONDONTWRITEBYTECODE: '1',
      },
    },
  );
  fs.closeSync(log);
  backend.on('exit', (code, signal) => {
    backendExited = true;
    backend = null;
    // all'avvio (finestra non ancora aperta) l'errore lo mostra start()
    if (quitting || !window) return;
    // morto da solo mentre l'app era aperta: senza backend la finestra non serve a niente
    dialog.showErrorBox(
      'Anki Studio',
      `Il backend locale si è fermato (${signal ?? `codice ${code}`}). Dettagli nel log: ${logPath}`,
    );
    quitting = true;
    app.quit();
  });
}

async function waitHealthy(): Promise<void> {
  const deadline = Date.now() + HEALTH_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (backendExited) throw new Error('Il backend locale si è fermato all’avvio (porta occupata?).');
    try {
      const res = await fetch(`${origin}/api/health`);
      if (res.ok) return;
    } catch {
      // non ancora in ascolto
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('Il backend locale non ha risposto in tempo.');
}

/** SIGTERM e attesa: il backend fa l'ultima sync e chiude la collezione per bene. */
function stopBackend(): Promise<void> {
  const child = backend;
  if (!child || backendExited) return Promise.resolve();
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      resolve();
    }, SHUTDOWN_TIMEOUT_MS);
    child.once('exit', () => {
      clearTimeout(timer);
      resolve();
    });
    child.kill('SIGTERM');
  });
}

app.on('before-quit', (event) => {
  if (backendExited || !backend) return;
  event.preventDefault();
  if (quitting) return;
  quitting = true;
  // la finestra sparisce subito; la sync di chiusura continua dietro
  for (const w of BrowserWindow.getAllWindows()) w.hide();
  void stopBackend().then(() => app.exit(0));
});

app.on('window-all-closed', () => app.quit());

function isAppUrl(url: string): boolean {
  return URL.canParse(url) && new URL(url).origin === origin;
}

async function openExternalUrl(url: string): Promise<void> {
  if (!URL.canParse(url) || !EXTERNAL_PROTOCOLS.has(new URL(url).protocol)) return;
  try {
    await shell.openExternal(url);
  } catch (error: unknown) {
    console.warn('[anki-studio] apertura del link esterno non riuscita:', error);
  }
}

function createWindow(): void {
  window = new BrowserWindow({
    width: 1200,
    height: 820,
    minWidth: 420,
    minHeight: 520,
    title: 'Anki Studio',
    // Barra del titolo disegnata dalla PWA (HeaderBar + WindowControls), come XMap Studio:
    // quella di sistema su GNOME è in stile GTK3 e non c'entra con l'app.
    frame: false,
    backgroundColor: nativeTheme.shouldUseDarkColors ? DARK_BACKGROUND : LIGHT_BACKGROUND,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  window.once('ready-to-show', () => window?.show());
  window.on('closed', () => {
    window = null;
  });
  window.on('maximize', () => window?.webContents.send('window:maximizedChanged', true));
  window.on('unmaximize', () => window?.webContents.send('window:maximizedChanged', false));

  // I link delle carte e di AnkiWeb si aprono nel browser di sistema, mai qui dentro:
  // una pagina esterna in questa finestra non deve stare accanto alla chiave.
  window.webContents.setWindowOpenHandler(({ url }) => {
    void openExternalUrl(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (isAppUrl(url)) return;
    event.preventDefault();
    void openExternalUrl(url);
  });

  // Ricarica e strumenti di sviluppo senza menu: F5 / Ctrl+R, Ctrl+Shift+I
  window.webContents.on('before-input-event', (event, input) => {
    if (input.type !== 'keyDown') return;
    const ctrl = input.control || input.meta;
    if (input.key === 'F5' || (ctrl && !input.shift && input.key.toLowerCase() === 'r')) {
      event.preventDefault();
      window?.webContents.reload();
    } else if (ctrl && input.shift && input.key.toLowerCase() === 'i') {
      event.preventDefault();
      window?.webContents.toggleDevTools();
    }
  });

  void window.loadURL(`${origin}/`).catch((error: unknown) => {
    console.warn('[anki-studio] caricamento della UI non riuscito:', error);
    window?.show();
  });
}

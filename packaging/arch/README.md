# App desktop per Arch Linux

`anki-studio-git` è la variante desktop di Anki Studio: la stessa PWA in una finestra Electron
(l'`electron44` di sistema, come XMap Studio), con **una copia locale della collezione**.

```
anki-studio (Electron) ──▶ backend FastAPI su 127.0.0.1:47613 ──▶ ~/.local/share/anki-studio/collection.anki2
                                                                     ▲
                                                                     └─sync─▶ AnkiWeb ◀─sync─ server cloud (anki.jshep.xyz)
                                                                                        ◀─sync─ AnkiMobile, Anki desktop
```

- **Offline**: il motore di Anki gira sul computer (lo stesso pacchetto Python `anki` del
  server), quindi si studia, si aggiungono e si modificano carte anche senza rete. Gli
  intervalli li calcola sempre Anki, mai la PWA.
- **Sync**: la copia locale si sincronizza con AnkiWeb all'avvio, ogni 10 minuti, a richiesta
  e alla chiusura (la finestra sparisce subito, la sync finisce dietro). Il server cloud fa lo
  stesso, e così si allineano. Una collezione Anki può sincronizzarsi con un solo server e il
  server cloud è a sua volta un client di AnkiWeb: per questo il punto d'incontro è AnkiWeb e
  non il server. Alla prima apertura va fatto il login AnkiWeb (Impostazioni › Sync): con la
  collezione locale vuota la prima sync scarica tutto; se servisse una sync completa, l'app
  chiede quale collezione tenere, come sul server.
- **Accesso**: niente Authentik. A ogni avvio Electron genera una chiave casuale, la passa al
  backend nell'ambiente e la aggiunge a ogni richiesta della sua finestra
  (`X-Anki-Desktop-Key`): una pagina del browser che raggiunge `127.0.0.1:47613` riceve 401.
  Il backend rifiuta la chiave insieme a OIDC o al login di sviluppo.
- **Niente MCP né token** sul desktop: gli agenti lavorano con il server cloud, e quello che
  creano arriva qui con la sync.

## Installare e aggiornare

```bash
makepkg -si      # dalla root del repository, dove sta il PKGBUILD
```

Come per XMap Studio non clona né scarica il repository: usa quello in cui si trova il
`PKGBUILD`. A ogni build fa il fetch di `origin/main` e porta avanti `main` in fast-forward
(pull se sei su `main`, altrimenti sposta solo il ref), poi esporta quel commit in `src/` con
`git archive`. Modifiche non committate e altri branch non entrano nel pacchetto.

Per provare un branch prima del merge: `ANKI_STUDIO_REF=HEAD makepkg -si` (niente fetch, si
compila il commit indicato).

Servono `git`, `nodejs`, `pnpm` nel `PATH` e la rete (pnpm e pip scaricano le dipendenze).

## Versione

`r<numero di commit>.g<hash>` del commit compilato: `pacman -Q anki-studio-git`. La stessa
stringa compare in Impostazioni › Informazioni («Desktop r…») e in `/api/health`, con il commit
completo in `revision`. Si calcola quando makepkg legge il `PKGBUILD`, non con una funzione
`pkgver()`, così il file non viene riscritto e i `git pull` restano puliti.

## Cosa installa

| Percorso | Cosa |
|---|---|
| `/usr/bin/anki-studio` | launcher: `electron44 /usr/lib/anki-studio/apps/desktop` |
| `/usr/lib/anki-studio/apps/desktop` | processo principale Electron (`apps/desktop`) e `version.json` |
| `/usr/lib/anki-studio/apps/web/dist` | build della PWA, servita dal backend locale |
| `/usr/lib/anki-studio/backend` | `app/` e il virtualenv `.venv` con le dipendenze di `requirements.lock` |
| `/usr/share/applications/org.joel.anki_studio.desktop` | voce nel menu delle applicazioni |

Il virtualenv usa il Python di sistema e vale per una sola minor (`lib/python3.X`): il pacchetto
dipende da `python>=3.X` e `python<3.X+1`, così quando Arch passa alla minor successiva pacman
lo segnala e basta ricompilarlo con `makepkg -si`.

## Dati e configurazione

- Collezione, media, backup, chiave AnkiWeb: `~/.local/share/anki-studio`
  (`$XDG_DATA_HOME/anki-studio`; `ANKI_DATA_DIR` per cambiarla).
- Log del backend dell'ultima sessione: `~/.local/share/anki-studio/desktop.log`.
- Le variabili del backend (`ANKI_AUTO_SYNC_MINUTES`, `ANKI_SYNC_ON_STARTUP`, `ANKI_LANG`, …)
  valgono anche qui: nell'ambiente o in un `.env` nella cartella dei dati. Accesso, cartella
  della PWA e MCP li decide l'app.
- Porta: `47613` su `127.0.0.1` (`ANKI_STUDIO_PORT`). È fissa perché l'origine conserva le
  preferenze della PWA (tema) e il service worker tra un avvio e l'altro.

## Sviluppo

```bash
pnpm install && (cd backend && uv venv && uv pip install -r requirements.lock)
pnpm desktop      # build di PWA e desktop, poi electron44 apps/desktop
```

In sviluppo i percorsi sono quelli del repository (`backend/.venv`, `apps/web/dist`); per
non toccare la collezione vera usa `ANKI_DATA_DIR=/tmp/prova ANKI_STUDIO_PORT=47699`.
F5 o Ctrl+R ricaricano, Ctrl+Shift+I apre gli strumenti di sviluppo.

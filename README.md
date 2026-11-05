# Anki Studio

PWA per **iPad** per studiare le flashcard **Anki** con un'interfaccia minimale,
sincronizzata con **AnkiWeb**. È sorella di [XMap Studio](https://github.com/gioelerosana/xmap-studio):
stesso design system e stesso stack frontend.

```
iPad (PWA) ──HTTPS──▶ Traefik ──▶ web (nginx: PWA + /api proxy) ──▶ api (FastAPI + motore Anki)
                                                                      │
                                                     collection.anki2 ◀──sync──▶ AnkiWeb
```

| Cartella | Cosa c'è |
|---|---|
| `apps/web` | PWA React 19 + Vite + Tailwind 3 |
| `packages/ui-kit` | Design system condiviso con XMap Studio ([docs/DESIGN-SYSTEM.md](docs/DESIGN-SYSTEM.md)) |
| `backend` | API FastAPI sul pacchetto Python ufficiale `anki` ([backend/README.md](backend/README.md)) |

## Avvio con Docker (produzione)

```bash
cp .env.example .env     # imposta ANKI_API_TOKEN (python -c "import secrets; print(secrets.token_urlsafe(32))")
docker compose up -d --build
```

- La PWA risponde su `http://127.0.0.1:8080`. L'esposizione su internet in HTTPS passa dal Traefik dello stack principale, collegato al servizio `web` sulla porta 80.
- I dati (collezione, media, chiave AnkiWeb) stanno nel volume `anki-studio_anki-data`. Per fare un backup: `docker run --rm -v anki-studio_anki-data:/d -v $PWD:/b alpine tar czf /b/anki-data.tgz -C /d .`
- Collegamento ad AnkiWeb, la prima volta: `POST /api/sync/login`, poi `POST /api/sync` (vedi [backend/README.md](backend/README.md)).

## Sviluppo

```bash
pnpm install
cd backend && uv venv && uv pip install -e ".[dev]" && cd ..

# terminale 1: API su :8000 (dati in backend/data)
ANKI_API_TOKEN=dev-token-almeno-16-caratteri ANKI_DATA_DIR=./data pnpm dev:api
# terminale 2: PWA su :5173, con /api inoltrato a :8000
pnpm dev
```

Controlli: `pnpm typecheck`, `pnpm build`, `pnpm test:api`.

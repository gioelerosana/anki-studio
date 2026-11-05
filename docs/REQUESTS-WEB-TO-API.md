# Richieste della PWA al backend

Cose che alla PWA (`apps/web`) mancano o che oggi aggira lato client. Chi lavora sul
backend le prende da qui; quando una è fatta, va spuntata con il commit che la chiude
(e la PWA toglie l'aggiramento).

Priorità: **alta** = l'utente se ne accorge durante lo studio, **media** = migliora
un flusso esistente, **bassa** = rifinitura.

## Aperte

- [x] **Intervalli e testi in italiano** (alta). `button_labels` arriva in inglese
  (`"5d"`, `"<10m"`) e così `TodayStats.summary`. Basterebbe impostare la lingua di Anki
  (`anki.lang.set_lang("it")`, o la lingua da `ANKI_LANG`) all'avvio: Anki ha già le
  traduzioni (`"5g"`). La PWA mostra le etichette così come arrivano; toglie solo gli
  isolatori bidi U+2068/U+2069. Per lo stesso motivo `summary` non è usato: la PWA
  compone "Oggi 12 carte in 4 min" da `reviews` e `seconds`.
  → **Fatto**: `ANKI_LANG` (default `it`) all'avvio; `button_labels` e `summary` arrivano già senza isolatori bidi.
- [x] **Risposta scritta `{{type:Campo}}`** (media). Le carte "Basic (type in the answer)"
  mostrano il campo ma non c'è modo di confrontare la risposta. Proposta:
  `POST /api/cards/{id}/type-answer {"typed": "..."}` → `{ "answer_html": "..." }` con il
  confronto già colorato come fa Anki (`col.compare_answer`). Oggi il campo è inerte.
  → **Fatto**: `POST /api/cards/{id}/type-answer {typed}` → `{answer_html}` (`api.typeAnswer`). Gestisce `cloze:` e `nc:`.
- [x] **`collapsed` dei mazzi** (bassa). Con la collezione di prova `GET /api/decks` manda
  `collapsed: true` per tutti i mazzi, anche senza figli. La PWA lo ignora e tiene
  aperto/chiuso per dispositivo in localStorage; da verificare se il campo è quello del
  browser o della schermata principale.
  → **Chiarito**: è lo stato della schermata principale (`collapsed`, non `browserCollapsed`), lo stesso di Anki desktop. Il seed creava tutti i mazzi chiusi (i mazzi nuovi nascono così); ora li apre tutti tranne `Scienze`. Niente endpoint per cambiarlo: in Anki è un'operazione annullabile e finirebbe nello stack di «Annulla».
- [x] **Nome del mazzo in `StudyState`** (bassa). Lo studio oggi chiama anche `GET /api/decks`
  solo per il titolo. Un `deck_name` in `StudyState` toglierebbe la seconda richiesta.
  → **Fatto**: `StudyState.deck_name` (nome completo).
- [x] **Bury/suspend che restituiscono la carta successiva** (bassa). Come `answer`:
  `POST /cards/{id}/bury` → `StudyState` del mazzo (serve il `deck_id`, es. in query).
  Oggi la PWA fa una seconda richiesta `GET /study`.
  → **Fatto**: `?deck_id=` → 200 con lo `StudyState` (`api.buryAndNext`, `api.suspendAndNext`); senza query resta 204.
- [x] **Cosa annulla «Annulla»** (bassa). `col.undo_status().undo` (es. "Rispondi alla carta",
  "Seppellisci") in `StudyState` permetterebbe un toast "Annullato: …" e di disattivare
  il pulsante quando non c'è niente da annullare, invece di scoprirlo con un 409.
  → **Fatto**: `StudyState.undo_label`. Dopo un cambio di mazzo è `null` e `undo` risponde 409: la selezione del mazzo è un'operazione annullabile in Anki, e annullare una risposta di un altro mazzo confonde.
- [x] **`url()` nel CSS dei tipi di nota** (bassa). I font e gli sfondi del CSS (`url("_font.ttf")`)
  non sono riscritti in `/api/media/…` come gli `src` dell'HTML. La PWA li riscrive da sé
  (`rewriteCssUrls` in `apps/web/src/study/cardContent.ts`): se il backend lo fa, il client
  lo lascia fare (gli URL assoluti non vengono toccati).
  → **Fatto**: il backend riscrive gli `url()` relativi del CSS in `/api/media/…` (quelli assoluti e `data:` restano).

## Note sul contratto (nessuna azione richiesta)

- `SyncStatus` (`running`, `progress`, `full_sync_required`, `endpoint_mismatch`, …) e
  `SyncResult.error_kind`: in `apps/web/src/api/types.ts` sono opzionali, così la PWA
  funziona sia con il backend della v0.1 sia con quello consolidato. Su un 409 di
  `POST /api/sync` la PWA apre la scelta della sync completa solo se `full_sync_required`
  non è `false`; altrimenti mostra il messaggio (sync rifiutata per proteggere i dati).
- Il tipo di nota "Image Occlusion" compare in `GET /api/notetypes` ma non si può creare
  dalla PWA (serve l'editor delle maschere): «Aggiungi carta» lo elenca comunque.

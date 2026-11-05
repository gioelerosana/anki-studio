# Design system dell'interfaccia

L'interfaccia (`packages/ui-kit`, `apps/web`) segue il design system **T3 Code**,
lo stesso di XMap Studio (le due app devono sembrare sorelle): canvas quasi bianco o quasi nero, bordi hairline, un
solo colore d'azione blu, font di sistema, densità da strumento per sviluppatori.
I token vivono in [`packages/ui-kit/src/theme.css`](../packages/ui-kit/src/theme.css);
Tailwind ([`apps/web/tailwind.config.js`](../apps/web/tailwind.config.js)) li
espone come classi. Questa pagina è il contratto: chi tocca la UI la segue.

## Principi

1. **Chrome silenzioso, un solo colore d'azione.** Le superfici sono neutre.
   `primary` è l'unico colore saturo e significa "agisci ora": il bottone
   principale (uno per vista), switch, focus ring, pulsante «Bene» nello studio.
   Niente blu decorativo su icone e titoli; il contenuto delle carte (HTML/CSS dei
   tipi di nota) è contenuto, non chrome (vedi "Studio").
2. **Bordi, non riempimenti.** Si separa con `border` hairline. In dark le card
   stanno appena sopra lo sfondo; niente grigi lattiginosi.
3. **Denso.** Controlli desktop 32px (`h-8`, `text-sm`), compatti 28px (`h-7`),
   micro 24px (`h-6`, `text-xs`). Metadati `text-2xs` (11px) / `text-3xs` (10px).
4. **Lo stato si tinge, non si urla.** Badge e banner di stato: tinta della hue
   all'8% (chiaro) / 16% (scuro) dietro il testo `*-foreground`. Riempimento
   pieno solo per azioni distruttive (`Button variant="destructive"`).
5. **Sentence case, niente emoji.** "Nuovo mazzo", "Aggiungi carta". Verbi brevi.

## Classi Tailwind da usare

Mai colori letterali (`#3584e4`, `bg-white`, `text-gray-500`, `bg-black/5`,
`dark:...`): il tema scuro lo gestiscono i token. Unica eccezione: `text-white`
non serve, si usa `text-primary-foreground`.

| Ruolo | Classi |
|---|---|
| Sfondo app | `bg-background text-foreground` |
| Pannelli rialzati | `bg-card` (+ `border` hairline) |
| Menu, popover, controlli outline | `bg-popover` |
| Sidebar | `bg-sidebar`; campo cerca `bg-sidebar-control-surface`; riga attiva `bg-sidebar-row-active` (+ `shadow-control` in chiaro) |
| Testo secondario, icone mute | `text-muted-foreground` |
| Hover/pressed di righe e ghost button | `hover:bg-accent hover:text-accent-foreground` |
| Bordi | `border` (colore di default già `--border`), `border-input` per input/outline |
| Azione | `bg-primary text-primary-foreground`, `text-primary` solo per link/selezione |
| Tinte di stato | `bg-error/8 text-error-foreground` (in dark `dark:bg-error/16`) — idem `info`, `success`, `warning`. Preferisci il componente `Badge`/`Banner`. |
| Focus | `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring` (bottoni); input: lo gestisce `Input` |
| Disabilitato | `disabled:opacity-disabled disabled:pointer-events-none` |
| Raggi | bottoni `rounded-control` (8px), input/card `rounded-lg` (10px), badge `rounded-sm` (6px), dialog e toolbar flottanti `rounded-xl` (14px) |
| Ombre | rare: `shadow-composer` (toolbar flottanti, toast), `shadow-dialog` (dialog, menu), `shadow-control` (controlli outline) |
| Vetro | `surface-glass` per menu, tooltip e toolbar flottanti; i dialog sono opachi (`bg-popover`) |
| Codice, LaTeX, numeri | `font-mono` (cifre tabulari) |
| Animazioni | `animate-fade-in`, `animate-pop-in`, `animate-slide-in-right`; easing `ease-sheet` |
| Layout | barra superiore `h-topbar` (48px), sidebar `w-sidebar` (280px) |

Tipografia: titoli di vista `text-base font-semibold` (16px), titoli di sezione
`text-sm font-medium`, etichette di gruppo `text-2xs font-medium uppercase
tracking-wide text-muted-foreground` con parsimonia. Icone Lucide: 16px
(`size-4`) nei controlli, 14px (`size-3.5`) nelle righe dense; dentro bottoni
ghost/outline sono `text-muted-foreground`.

## API di `@anki-studio/ui-kit`

Tutti i componenti accettano `className` (fuso con `cn`) e inoltrano le prop
native. Le varianti sono quelle sotto: non esistono più `flat` né `suggested`.

### `Button`
```tsx
<Button variant="default" size="default" icon={<Save />}>Salva</Button>
```
- `variant`: `'default'` (primary pieno, uno per vista) · `'outline'` (azioni
  secondarie) · `'secondary'` (Annulla nei dialog) · `'ghost'` (toolbar) ·
  `'ghost-muted'` (ghost con testo `muted-foreground`) · `'destructive'` (pieno
  rosso) · `'destructive-outline'` · `'ghost-destructive'` · `'link'`.
  Default: `'default'`.
- `size`: `'xs'` (24px, text-xs) · `'sm'` (28px) · `'default'` (32px) ·
  `'lg'` (36px) · `'icon-xs'` (24²) · `'icon-sm'` (28²) · `'icon'` (32²) ·
  `'icon-lg'` (36²). Default `'default'`.
- `icon?: ReactNode` prima della label, `iconRight?: ReactNode` dopo.
- `loading?: boolean` mostra uno spinner e disabilita.
- `active?: boolean` (toggle in toolbar): `bg-accent text-foreground`.
- `forwardRef` su `<button>`, `type="button"` di default.

### `IconButton`
Scorciatoia per bottoni solo-icona. `aria-label` obbligatorio (prop `label:
string`, usata anche come `title`).
- `variant`: `'ghost'` (default) · `'outline'` · `'default'` · `'ghost-destructive'`.
- `size`: `'xs'` 24 · `'sm'` 28 · `'md'` 32 (default) · `'lg'` 36.
- `active?: boolean`.

### `Badge`
`variant`: `'default'` · `'secondary'` · `'outline'` · `'error'` · `'info'` ·
`'success'` · `'warning'`; `size`: `'sm'` 16px · `'default'` 18px · `'lg'` 22px.
`icon?: ReactNode` (12px).

### `Kbd`, `KbdGroup`
`<KbdGroup><Kbd>Ctrl</Kbd><Kbd>S</Kbd></KbdGroup>`. `formatShortcut('Ctrl+Shift+S')`
restituisce l'array di tasti e `<Shortcut keys="Ctrl+Shift+S" />` lo rende.

### `Input`, `Textarea`, `Select`
- `Input`: `size` `'sm'` (28) · `'default'` (32) · `'lg'` (36); `mono?`;
  `invalid?`; `leading?: ReactNode` (icona a sinistra, es. cerca);
  `trailing?: ReactNode`. `forwardRef` sull'`<input>`.
- `Textarea`: stesso stile, `mono?`, `invalid?`, `autoResize?`. `forwardRef`.
- `Select`: `<select>` nativo con lo stile di Input e chevron; `size`, `options?:
  {value,label}[]` oppure children.

### `Switch`, `Checkbox`
`Switch`: `checked`, `onCheckedChange(checked)`, `label?`, `disabled?`; traccia
`primary` quando attivo. `Checkbox`: idem, quadrato `rounded-sm`.

### `Field`, `Label`
`<Field label="Titolo" hint="…" error="…">{control}</Field>`: label `text-xs
font-medium`, hint `text-2xs text-muted-foreground`, errore `text-2xs
text-error-foreground`.

### `Separator`
`orientation`: `'horizontal'` (default) · `'vertical'`; hairline `bg-border`.

### `SegmentedControl` (alias `ViewSwitcher`)
Stessa API di prima (`items`, `activeId`, `onChange`, `size?: 'sm'|'default'`).
Traccia `bg-muted` con bordo, segmento attivo `bg-popover shadow-control
text-foreground`, inattivi `text-muted-foreground`.

### `Banner`
`variant`: `'info'|'success'|'warning'|'error'`, `title?`, `children`, `icon?`,
`action?: ReactNode`. Tinta di stato, `rounded-lg`, testo `*-foreground`.

### `Card`, `Section`
`Card`: `bg-card border rounded-lg`. `Section`: blocco di pannello con `title`,
`description?`, `actions?` (a destra del titolo), `children`.

### `EmptyHint`
Stato vuoto compatto: `icon`, `title`, `description?`, `action?`.

### `Modal`
Stessa API (`isOpen`, `onClose`, `title`, `description?`, `children`,
`footer?`, `maxWidth?`), più `size?: 'sm'|'md'|'lg'` (sostituisce `maxWidth`
quando presente). Dialog **opaco** `bg-popover rounded-xl shadow-dialog` (niente
vetro: il contenuto sotto non deve trasparire), backdrop
`bg-black/32` con fade, entrata `animate-pop-in`. Footer allineato a destra,
separato da `border-t`, nessun riempimento grigio. Chiusura con Esc e clic sul
backdrop; focus iniziale sul dialog.

### `Menu`
Stessa API (`items`, `trigger`, `align`, `widthClass`). Pannello in vetro
`rounded-lg shadow-dialog p-1`, righe `h-8 rounded-md px-2 text-sm`, hover
`bg-accent`, icone `text-muted-foreground`, scorciatoie con `Shortcut`,
separatori `Separator` con `my-1`. `danger` → `text-error-foreground`, hover
`bg-error/8`. Navigazione da tastiera ↑ ↓ Invio Esc.

### `Toast`, `ToastContainer`
Stessa API. Card `bg-popover border rounded-lg shadow-composer`, icona di stato
colorata `*-foreground`, testo `text-sm`, entrata `animate-pop-in`, in basso a
destra.

### `HeaderBar`
Altezza `h-topbar` (+ safe area iPad), `bg-background`, `border-b`, regione
trascinabile `app-drag-region`. Titolo centrato `text-sm font-medium`,
sottotitolo `text-2xs text-muted-foreground`.


### `Tooltip`
`<Tooltip content="Salva" shortcut="Ctrl+S">{trigger}</Tooltip>`: bolla in vetro
`text-xs`, ritardo 400ms, sopra o sotto (`side`).

### `Spinner`
Icona `Loader2` animata, `size-4`.

## Studio (specifico di Anki Studio)

- **La carta è contenuto.** L'HTML e il CSS dei tipi di nota arrivano da Anki e vanno
  isolati (Shadow DOM o iframe) dentro `<div class="{card_class}">`: il CSS delle carte
  non deve toccare l'interfaccia, e i token dell'app non devono rompere le carte.
  Il colore di sfondo della carta resta quello del tipo di nota, altrimenti `bg-card`.
- **Pulsanti di risposta**: quattro, grandi (≥ 56px su iPad, `coarse:`), in basso,
  raggiungibili coi pollici. «Bene» è l'unico `primary`; «Di nuovo» usa la tinta
  `error`, «Difficile» e «Facile» sono `outline`. Sotto l'etichetta, l'intervallo
  (`button_labels`) in `text-2xs font-mono text-muted-foreground`.
- **Contatori nuove / in apprendimento / da ripassare**: `info` / `error` / `success`
  `-foreground`, cifre `font-mono`; a zero `text-muted-foreground/50`.
- **Tocco**: tap sulla carta = mostra risposta; scorciatoie da tastiera (Spazio, 1–4)
  per la Magic Keyboard. Nessuna animazione oltre `fade-in`/`pop-in`; rispetta
  «Riduci animazioni».

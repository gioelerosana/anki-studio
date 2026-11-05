"""Crea una collezione Anki di prova per lo sviluppo della PWA.

    cd backend
    .venv/bin/python scripts/seed_dev.py            # crea data/collection.anki2
    .venv/bin/python scripts/seed_dev.py --force    # la ricrea (la vecchia va in backup)

Contiene quello che la PWA deve saper mostrare:

- mazzi annidati (Lingue::Spagnolo::Verbi, Lingue::Inglese, Scienze::Chimica, …)
- Basic, Basic con inversa, Basic con inversa facoltativa, risposta da digitare, Cloze
- un tipo di nota "Vocabolo" con CSS personalizzato (font, colori, .nightMode),
  TTS nel template ({{tts it_IT:...}}) e audio [sound:] nei campi
- immagini PNG e SVG, audio WAV (generati qui, niente file binari nel repo)
- MathJax, tag gerarchici, flag
- carte in tutte le code: nuove, in apprendimento, in riapprendimento,
  da ripassare oggi, in ritardo, future, sospese e seppellite

Lo script NON tocca una collezione esistente senza --force, e anche con --force
non cancella niente: sposta la vecchia collezione (media e collegamento AnkiWeb
compresi) in data/backup-seed-<data>/, perché potrebbe essere quella vera. Ferma l'API prima
di lanciarlo (la collezione va aperta da un solo processo).
"""

from __future__ import annotations

import argparse
import math
import struct
import sys
import wave
import zlib
from pathlib import Path

from anki.collection import Collection

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ---- media generati ------------------------------------------------------


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    """PNG a tinta unita con una banda diagonale, senza dipendenze."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filtro "none"
        for x in range(width):
            on_band = abs(x - y * width // height) < width // 8
            rows += bytes(255 - c // 2 for c in rgb) if on_band else bytes(rgb)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )


def _wav(path: Path, freq: float, seconds: float = 0.6) -> None:
    rate = 22050
    frames = bytearray()
    n = int(rate * seconds)
    for i in range(n):
        fade = min(1.0, i / 800, (n - i) / 800)
        frames += struct.pack("<h", int(12000 * fade * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 80" width="240" height="160">
  <rect width="120" height="80" rx="8" fill="#e8f0fe"/>
  <circle cx="40" cy="40" r="18" fill="#c62828"/>
  <circle cx="80" cy="40" r="12" fill="#1565c0"/>
  <line x1="58" y1="40" x2="68" y2="40" stroke="#333" stroke-width="3"/>
  <text x="60" y="74" font-size="9" text-anchor="middle" font-family="sans-serif">H–O</text>
</svg>
"""


def _write_media(col: Collection) -> None:
    media = Path(col.media.dir())
    (media / "sole.png").write_bytes(_png(160, 100, (255, 193, 7)))
    (media / "mare.png").write_bytes(_png(160, 100, (3, 155, 229)))
    (media / "bosco.png").write_bytes(_png(160, 100, (67, 160, 71)))
    (media / "molecola.svg").write_text(_SVG)
    # nome con spazio e accento: la PWA deve gestire l'URL-encoding
    (media / "città notte.png").write_bytes(_png(120, 80, (40, 53, 147)))
    _wav(media / "hablar.wav", 440)
    _wav(media / "comer.wav", 523.25)
    _wav(media / "vivir.wav", 659.25)
    _wav(media / "ding.wav", 880, 0.25)


# ---- tipo di nota personalizzato ----------------------------------------

VOCABOLO_CSS = """\
.card {
  font-family: "Iowan Old Style", Georgia, serif;
  font-size: 26px;
  text-align: center;
  color: #1d1b16;
  background: #fbf8f1;
  line-height: 1.4;
}
.parola { font-size: 2em; font-weight: 600; letter-spacing: .01em; }
.esempio { font-style: italic; color: #6b6355; font-size: .8em; margin-top: .6em; }
.genere { display: inline-block; padding: 0 .5em; border-radius: 1em;
          background: #e7dcc4; font-size: .6em; vertical-align: middle; }
img { max-width: 100%; border-radius: 8px; }
.nightMode .card, .card.nightMode { color: #ece6d9; background: #1f1d19; }
.nightMode .esempio { color: #b3a993; }
.nightMode .genere { background: #4a4337; }
"""

VOCABOLO_FRONT = """\
<div class="parola">{{Parola}}</div>
{{#Genere}}<span class="genere">{{Genere}}</span>{{/Genere}}
{{tts es_ES:Parola}}
"""

VOCABOLO_BACK = """\
{{FrontSide}}
<hr id="answer">
<div>{{Traduzione}}</div>
{{#Esempio}}<div class="esempio">{{Esempio}}</div>{{/Esempio}}
{{Immagine}}
{{Audio}}
"""


def _vocabolo_notetype(col: Collection) -> dict:
    mm = col.models
    nt = mm.new("Vocabolo")
    for name in ("Parola", "Traduzione", "Genere", "Esempio", "Immagine", "Audio"):
        mm.add_field(nt, mm.new_field(name))
    t = mm.new_template("Riconoscimento")
    t["qfmt"] = VOCABOLO_FRONT
    t["afmt"] = VOCABOLO_BACK
    mm.add_template(nt, t)
    # seconda carta solo se c'è un'immagine: copre il caso "template condizionale"
    t2 = mm.new_template("Da immagine")
    t2["qfmt"] = "{{#Immagine}}{{Immagine}}<div>Che cos'è?</div>{{/Immagine}}"
    t2["afmt"] = "{{FrontSide}}<hr id=answer><div class=parola>{{Parola}}</div>{{Audio}}"
    mm.add_template(nt, t2)
    nt["css"] = VOCABOLO_CSS
    mm.add(nt)
    return mm.by_name("Vocabolo")


# ---- contenuto -----------------------------------------------------------


def _add(col: Collection, notetype: str | dict, deck: str, fields: dict[str, str], tags=()):
    nt = col.models.by_name(notetype) if isinstance(notetype, str) else notetype
    note = col.new_note(nt)
    for k, v in fields.items():
        note[k] = v
    note.tags = list(tags)
    col.add_note(note, col.decks.id(deck))
    return note


def _seed(col: Collection) -> dict[str, list[int]]:
    _write_media(col)
    voc = _vocabolo_notetype(col)

    # Spagnolo: tipo di nota personalizzato, audio, immagini, TTS
    verbi = [
        ("hablar", "parlare", "Hablo español con mis amigos.", "hablar.wav", ""),
        ("comer", "mangiare", "Comemos a las dos.", "comer.wav", ""),
        ("vivir", "vivere", "Vivo en Milán.", "vivir.wav", ""),
        ("tener", "avere", "Tengo dos hermanos.", "", ""),
        ("ser", "essere", "Soy estudiante.", "", ""),
        ("ir", "andare", "Voy al mercado.", "", ""),
        ("hacer", "fare", "¿Qué haces?", "", ""),
        ("poder", "potere", "No puedo venir.", "", ""),
    ]
    for parola, trad, es, audio, _ in verbi:
        _add(
            col,
            voc,
            "Lingue::Spagnolo::Verbi",
            {
                "Parola": parola,
                "Traduzione": trad,
                "Esempio": es,
                "Audio": f"[sound:{audio}]" if audio else "",
            },
            ["spagnolo::verbi", "A1"],
        )
    nomi = [
        ("el sol", "il sole", "m", "sole.png"),
        ("el mar", "il mare", "m", "mare.png"),
        ("el bosque", "il bosco", "m", "bosco.png"),
        ("la ciudad", "la città", "f", "città notte.png"),
        ("la casa", "la casa", "f", ""),
        ("el libro", "il libro", "m", ""),
    ]
    for parola, trad, gen, img in nomi:
        _add(
            col,
            voc,
            "Lingue::Spagnolo::Nomi",
            {
                "Parola": parola,
                "Traduzione": trad,
                "Genere": gen,
                "Immagine": f'<img src="{img}">' if img else "",
                "Audio": "[sound:ding.wav]" if img else "",
            },
            ["spagnolo::nomi"],
        )

    # Inglese: Basic con inversa e risposta da digitare
    for en, it in [
        ("to take off", "decollare / togliersi"),
        ("to give up", "arrendersi, rinunciare"),
        ("to look forward to", "non vedere l'ora di"),
        ("to run out of", "rimanere senza"),
        ("to put up with", "sopportare"),
    ]:
        _add(
            col,
            "Basic (and reversed card)",
            "Lingue::Inglese::Phrasal verbs",
            {"Front": en, "Back": it},
            ["inglese"],
        )
    for en, it in [("cat", "gatto"), ("dog", "cane"), ("bird", "uccello")]:
        _add(
            col,
            "Basic (type in the answer)",
            "Lingue::Inglese",
            {"Front": f"Traduci in inglese: <b>{it}</b>", "Back": en},
            ["inglese", "digitare"],
        )
    _add(
        col,
        "Basic (optional reversed card)",
        "Lingue::Inglese",
        {
            "Front": "[anki:tts lang=en_US]Good morning[/anki:tts]",
            "Back": "Buongiorno",
            "Add Reverse": "y",
        },
        ["inglese", "tts"],
    )

    # Scienze: Cloze, MathJax, SVG
    cloze = [
        "L'acqua è formata da {{c1::due}} atomi di {{c2::idrogeno}} e uno di {{c3::ossigeno}}.",
        "Il simbolo del sodio è {{c1::Na}}, quello del potassio è {{c2::K}}.",
        "Il pH di una soluzione neutra a 25 °C è {{c1::7}}.",
        "La costante di Avogadro vale circa {{c1::\\(6{,}022 \\times 10^{23}\\)::numero}} mol⁻¹.",
    ]
    for text in cloze:
        _add(col, "Cloze", "Scienze::Chimica", {"Text": text, "Back Extra": ""}, ["chimica"])
    _add(
        col,
        "Basic",
        "Scienze::Chimica",
        {"Front": 'Che molecola è questa?<br><img src="molecola.svg">', "Back": "Monossido di… (H–O)"},
        ["chimica", "immagini"],
    )
    for q, a in [
        ("Derivata di \\(\\sin x\\)", "\\(\\cos x\\)"),
        ("\\[\\int_0^1 x^2\\,dx\\]", "\\(\\tfrac13\\)"),
        ("Limite notevole \\(\\lim_{x\\to0} \\frac{\\sin x}{x}\\)", "\\(1\\)"),
        ("Formula di Eulero", "\\(e^{i\\pi} + 1 = 0\\)"),
    ]:
        _add(col, "Basic", "Scienze::Matematica", {"Front": q, "Back": a}, ["matematica", "mathjax"])

    # Mazzo "Default" con due carte, così anche quello compare con dei numeri
    _add(col, "Basic", "Default", {"Front": "Capitale del Portogallo", "Back": "Lisbona"}, ["geografia"])
    _add(col, "Basic", "Default", {"Front": "Capitale della Norvegia", "Back": "Oslo"}, ["geografia"])

    # mazzo vuoto: la PWA deve mostrare "niente da studiare"
    col.decks.id("Archivio")

    # i mazzi nuovi nascono chiusi nella schermata principale: apriamo tutto
    # tranne "Scienze", così la PWA vede entrambi i casi
    for d in col.decks.all_names_and_ids():
        deck = col.decks.get(d.id)
        deck["collapsed"] = d.name == "Scienze"
        col.decks.save(deck)

    return _distribute_queues(col)


def _again(col: Collection, cid: int) -> None:
    """Risponde "Di nuovo" come farebbe la PWA (start_timer serve a time_taken)."""
    card = col.get_card(cid)
    card.start_timer()
    col.sched.answerCard(card, 1)


def _cids(col: Collection, search: str) -> list[int]:
    return list(col.find_cards(search, order="c.id"))


def _distribute_queues(col: Collection) -> dict[str, list[int]]:
    """Porta alcune carte in ogni coda usando lo scheduler di Anki (niente SQL a mano,
    salvo spostare indietro la scadenza per avere carte in ritardo)."""
    sched = col.sched
    out: dict[str, list[int]] = {}

    # Verbi: 2 nuove, 2 in apprendimento, 2 da ripassare oggi, 1 in ritardo, 1 futura
    verbi = _cids(col, '"deck:Lingue::Spagnolo::Verbi" card:Riconoscimento')
    out["learning"] = verbi[2:4]
    for cid in out["learning"]:
        _again(col, cid)  # "Di nuovo" su una nuova -> apprendimento
    out["review_today"] = verbi[4:6]
    sched.set_due_date(out["review_today"], "0")
    out["overdue"] = verbi[6:7]
    sched.set_due_date(out["overdue"], "0")
    col.db.execute(
        "update cards set due = due - 5, ivl = 6 where id in "
        + _ids_sql(out["overdue"])
    )
    out["future"] = verbi[7:8]
    sched.set_due_date(out["future"], "7-14")

    # Phrasal verbs: un ripasso dimenticato oggi -> riapprendimento
    pv = _cids(col, '"deck:Lingue::Inglese::Phrasal verbs" card:1')
    sched.set_due_date(pv[:3], "0")
    out["relearning"] = pv[:1]
    _again(col, pv[0])
    out["review_today"] += pv[1:3]

    # Chimica: una sospesa, una seppellita, un paio da ripassare
    chem = _cids(col, '"deck:Scienze::Chimica"')
    out["suspended"] = chem[:1]
    sched.suspend_cards(out["suspended"])
    out["buried"] = chem[1:2]
    sched.bury_cards(out["buried"])
    sched.set_due_date(chem[2:4], "0")
    out["review_today"] += chem[2:4]

    # Matematica: tutte da ripassare, con un flag
    math_cards = _cids(col, '"deck:Scienze::Matematica"')
    sched.set_due_date(math_cards[:3], "0")
    sched.set_due_date(math_cards[3:], "2")
    out["review_today"] += math_cards[:3]
    out["future"] += math_cards[3:]
    col.set_user_flag_for_cards(1, math_cards[:1])
    col.set_user_flag_for_cards(4, math_cards[1:2])

    return out


def _ids_sql(ids: list[int]) -> str:
    return "(" + ",".join(str(int(i)) for i in ids) + ")"


def _summary(col: Collection) -> str:
    lines = []
    for d in col.sched.deck_due_tree().children:
        lines.extend(_tree_lines(d, 0))
    notes = col.note_count()
    cards = col.card_count()
    models = [m.name for m in col.models.all_names_and_ids()]
    return (
        f"{notes} note, {cards} carte, tipi di nota: {', '.join(models)}\n"
        + "\n".join(lines)
    )


def _tree_lines(node, depth: int) -> list[str]:
    line = f"  {'  ' * depth}{node.name:<24} nuove {node.new_count:>2}  appr. {node.learn_count:>2}  ripasso {node.review_count:>2}"
    out = [line]
    for c in node.children:
        out.extend(_tree_lines(c, depth + 1))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--data-dir",
        type=Path,
        default=BACKEND_DIR / "data",
        help="cartella dati del backend (default: backend/data)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="ricrea la collezione, spostando quella esistente in data/backup-seed-*",
    )
    args = p.parse_args(argv)

    data_dir: Path = args.data_dir
    col_path = data_dir / "collection.anki2"
    if col_path.exists():
        if not args.force:
            print(
                f"{col_path} esiste già: non lo tocco. Usa --force per ricrearlo "
                "(quella attuale, media e collegamento AnkiWeb compresi, finisce in "
                "una cartella backup-seed-*).",
                file=sys.stderr,
            )
            return 1
        print(f"Collezione precedente spostata in {_move_aside(data_dir)}")

    data_dir.mkdir(parents=True, exist_ok=True)
    col = Collection(str(col_path))
    try:
        if any(m.name == "Vocabolo" for m in col.models.all_names_and_ids()):
            raise SystemExit("la collezione contiene già i dati di prova")
        queues = _seed(col)
        print(f"Collezione di prova creata in {col_path}\n")
        print(_summary(col))
        print("\nCode:", {k: len(v) for k, v in queues.items()})
    finally:
        col.close()
    return 0


_COLLECTION_FILES = (
    "collection.anki2",
    "collection.anki2-wal",
    "collection.anki2-shm",
    "collection.media",
    "collection.media.db2",
    # anche il collegamento AnkiWeb: la collezione di prova non deve MAI
    # finire su un account vero alla prossima sync
    "sync_auth.json",
)


def _move_aside(data_dir: Path) -> Path:
    """Sposta la collezione esistente in una cartella di backup invece di cancellarla."""
    import time

    dest = data_dir / f"backup-seed-{time.strftime('%Y%m%d-%H%M%S')}"
    dest.mkdir()
    for name in _COLLECTION_FILES:
        src = data_dir / name
        if src.exists():
            src.rename(dest / name)
    return dest


if __name__ == "__main__":
    raise SystemExit(main())

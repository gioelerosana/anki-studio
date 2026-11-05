"""Trasforma una carta Anki in HTML pronto per la PWA.

- i riferimenti ai media (img/audio/video src="file.jpg") diventano URL dell'API
- i marcatori audio [anki:play:q:0] diventano <button class="anki-play">
  e la lista dei suoni/TTS viene restituita a parte, così il frontend
  decide come riprodurli
"""

from __future__ import annotations

import re
from urllib.parse import quote

from anki.cards import Card
from anki.sound import AV_REF_RE, AVTag, SoundOrVideoTag, TTSTag

MEDIA_PREFIX = "/api/media/"

_SRC_RE = re.compile(
    r"""(?P<pre><(?:img|audio|video|source)\b[^>]*?\bsrc\s*=\s*)(?P<q>["']?)(?P<src>[^"'\s>]+)(?P=q)""",
    re.IGNORECASE,
)
_EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|/|#)", re.IGNORECASE)


def _rewrite_media(html: str) -> str:
    def sub(m: re.Match[str]) -> str:
        src = m.group("src")
        if _EXTERNAL.match(src):
            return m.group(0)
        q = m.group("q") or '"'
        return f"{m.group('pre')}{q}{MEDIA_PREFIX}{quote(src)}{q}"

    return _SRC_RE.sub(sub, html)


def _replace_av_refs(html: str) -> str:
    def sub(m: re.Match[str]) -> str:
        side, idx = m.group(2), m.group(3)
        return (
            f'<button type="button" class="anki-play" data-side="{side}" '
            f'data-index="{idx}" aria-label="Riproduci audio">▶</button>'
        )

    return AV_REF_RE.sub(sub, html)


def _av_to_json(tags: list[AVTag]) -> list[dict]:
    out: list[dict] = []
    for t in tags:
        if isinstance(t, SoundOrVideoTag):
            out.append({"type": "sound", "url": MEDIA_PREFIX + quote(t.filename)})
        elif isinstance(t, TTSTag):
            out.append(
                {"type": "tts", "text": t.field_text, "lang": t.lang, "speed": t.speed}
            )
    return out


def _clean(html: str) -> str:
    return _replace_av_refs(_rewrite_media(html))


def render_card(card: Card) -> dict:
    out = card.render_output(reload=True)
    return {
        "question_html": _clean(out.question_text),
        "answer_html": _clean(out.answer_text),
        "css": out.css,
        # Anki avvolge la carta in <div class="card cardN"> per i selettori CSS
        "card_class": f"card card{card.ord + 1}",
        "question_av": _av_to_json(out.question_av_tags),
        "answer_av": _av_to_json(out.answer_av_tags),
        "autoplay": card.autoplay(),
    }

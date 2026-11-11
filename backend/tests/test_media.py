"""POST /api/media: tetto, formati, estensione e contenuto coerenti, nomi sanificati, permessi."""

import base64
from pathlib import Path

import pytest

from app import hub

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"\x00" * 32
OGG = b"OggS" + b"\x00" * 32
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 24
M4A = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 32
AAC = b"\xff\xf1" + b"\x00" * 32
FLAC = b"fLaC" + b"\x00" * 32
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 32
SVG = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>'


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def upload(client, filename, data, headers=None, *, raw=None):
    body = {"filename": filename, "data_base64": raw if raw is not None else b64(data)}
    return client.post("/api/media", json=body, headers=headers)


def media_dir(client) -> Path:
    with client.app.state.manager.use() as col:
        return Path(col.media.dir())


@pytest.mark.parametrize(
    "name,data",
    [
        ("gatto.png", PNG), ("foto.jpg", JPG), ("foto.jpeg", JPG), ("anim.gif", GIF),
        ("img.webp", WEBP), ("voce.mp3", MP3), ("voce.ogg", OGG),
        ("voce.wav", WAV), ("voce.m4a", M4A), ("voce.aac", AAC), ("voce.flac", FLAC),
        ("clip.mp4", MP4), ("clip.webm", WEBM),
    ],
)
def test_valid_files_are_written(client, name, data):
    r = upload(client, name, data)
    assert r.status_code == 201, r.text
    final = r.json()["filename"]
    assert final == name
    assert (media_dir(client) / final).read_bytes() == data


def test_uppercase_extension_is_accepted(client):
    # il nome definitivo lo decide Anki (qui lo porta in minuscolo)
    r = upload(client, "MAIUSCOLO.PNG", PNG)
    assert r.status_code == 201 and r.json()["filename"].lower() == "maiuscolo.png"


def test_same_content_same_name_is_idempotent_and_a_different_file_gets_another_name(client):
    first = upload(client, "gatto.png", PNG).json()["filename"]
    again = upload(client, "gatto.png", PNG).json()["filename"]
    assert again == first
    other = upload(client, "gatto.png", PNG + b"altro").json()["filename"]
    assert other != first and other.endswith(".png")
    assert (media_dir(client) / first).read_bytes() == PNG  # l'originale non è stato toccato


def test_the_returned_media_is_served_with_a_sandboxing_csp(client):
    """I media sono contenuto dell'utente (anche un `.svg` o `.html` arrivato con la sync):
    escono con `sandbox` e senza `script-src`, quindi aprirli direttamente non esegue niente
    sulla nostra origine."""
    name = upload(client, "gatto.png", PNG).json()["filename"]
    r = client.get(f"/api/media/{name}")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "sandbox" in csp and "default-src 'none'" in csp and "script-src" not in csp
    assert r.headers["x-content-type-options"] == "nosniff"


def test_too_large(client):
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * hub.MAX_MEDIA_BYTES  # 10 MB + 8 byte
    r = upload(client, "grosso.png", big)
    assert r.status_code == 413 and "10 MB" in r.json()["detail"]
    assert not (media_dir(client) / "grosso.png").exists()
    # il tetto è sui byte decodificati: esattamente 10 MB passa
    ok = b"\x89PNG\r\n\x1a\n" + b"\x00" * (hub.MAX_MEDIA_BYTES - 8)
    assert upload(client, "limite.png", ok).status_code == 201
    # e una stringa base64 smisurata non si decodifica nemmeno
    assert upload(client, "enorme.png", b"", raw="A" * (hub._MAX_MEDIA_B64 + 1)).status_code == 413


@pytest.mark.parametrize(
    "name,data",
    [
        ("finto.png", b"MZ\x90\x00 non sono un'immagine"),  # eseguibile con estensione png
        ("pagina.png", b"<html><script>alert(1)</script></html>"),
        ("voce.mp3", PNG),  # immagine con estensione audio
        ("foto.jpg", PNG),
        ("clip.mp4", WEBM),
        ("vuoto.png", b""),
    ],
)
def test_extension_and_content_must_match(client, name, data):
    r = upload(client, name, data)
    assert r.status_code == 422, r.text
    assert not (media_dir(client) / name).exists()


@pytest.mark.parametrize("name", ["pagina.html", "script.js", "app.exe", "senzaestensione", "x.png.exe", "archivio.zip", "doc.pdf"])
def test_extension_not_allowed(client, name):
    r = upload(client, name, PNG)
    assert r.status_code == 422 and "non ammessa" in r.json()["detail"]


@pytest.mark.parametrize(
    "svg",
    [
        SVG,  # anche uno innocuo: non si ammettono SVG
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        # le forme che un filtro a espressioni regolari non vede
        b'<svg/onload=alert(1)>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a xlink:href="https://evil.test/x"><rect/></a></svg>',
        b'<!DOCTYPE svg [<!ENTITY x "&#x3c;script&#x3e;">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
        PNG,
    ],
)
@pytest.mark.parametrize("name", ["x.svg", "X.SVG", "y.SvG"])
def test_svg_is_never_accepted(client, svg, name):
    r = upload(client, name, svg)
    assert r.status_code == 422, r.text
    assert "SVG" in r.json()["detail"] and "PNG" in r.json()["detail"]
    assert not any(p.suffix.lower() == ".svg" for p in media_dir(client).iterdir())


@pytest.mark.parametrize(
    "raw",
    ["non è base64!", "data:image/png;base64," + b64(PNG), b64(PNG)[:-1], "="],
)
def test_invalid_base64(client, raw):
    assert upload(client, "gatto.png", b"", raw=raw).status_code == 422


def test_base64_with_line_breaks_is_fine(client):
    wrapped = "\n".join(b64(PNG)[i : i + 20] for i in range(0, len(b64(PNG)), 20))
    assert upload(client, "gatto.png", b"", raw=wrapped).status_code == 201


@pytest.mark.parametrize(
    "bad,expected",
    [
        ("../../etc/gatto.png", "gatto.png"),
        ("..\\..\\windows\\gatto.png", "gatto.png"),
        ("/assoluto/gatto.png", "gatto.png"),
        (".nascosto.png", "nascosto.png"),
        ("...png.png", "png.png"),
        ("gatto..png", "gatto.png"),
        ("il gatto [1].png", "il_gatto_1.png"),
        ("gatto\x00\x1f\n.png", "gatto.png"),
        ("<img src=x onerror=1>.png", "img_src_x_onerror_1.png"),
        ("perché è così.png", "perché_è_così.png"),
        ("a" * 150 + ".png", "a" * 96 + ".png"),
    ],
)
def test_malicious_names_are_sanitised(client, bad, expected):
    r = upload(client, bad, PNG)
    assert r.status_code == 201, (bad, r.text)
    final = r.json()["filename"]
    assert final == expected
    directory = media_dir(client)
    assert (directory / final).is_file()
    # niente è finito fuori dalla cartella media
    assert not any(p.name == "gatto.png" for p in directory.parent.parent.iterdir() if p.is_file())


@pytest.mark.parametrize("bad", ["..", ".", "/", "...png", "....", ".png", "   .png"])
def test_names_without_a_real_name_are_rejected(client, bad):
    assert upload(client, bad, PNG).status_code == 422


def test_media_permissions(client, make_token):
    write, _ = make_token("scrittore", scope="write")
    read, _ = make_token("lettore", scope="read")
    assert upload(client, "w.png", PNG, write).status_code == 201
    r = upload(client, "r.png", PNG, read)
    assert r.status_code == 403
    assert not (media_dir(client) / "r.png").exists()
    assert upload(client, "a.png", PNG, {"Authorization": ""}).status_code == 401
    # il vecchio token amministratore (il client di default) può
    assert upload(client, "adm.png", PNG).status_code == 201
    # un token con scope non può leggere i file, solo caricarli
    assert client.get("/api/media/w.png", headers=write).status_code == 403


def test_media_write_requests_a_sync(client, monkeypatch):
    calls = []
    monkeypatch.setattr(client.app.state.sync, "request_soon", lambda: calls.append(1))
    upload(client, "s.png", PNG)
    upload(client, "finto.png", b"MZ")  # rifiutato: niente sync
    assert calls == [1]

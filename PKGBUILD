# Pacchetto Arch Linux di Anki Studio per il desktop (VCS: git).
# Costruito dall'ultimo commit di `main`, dal repository che contiene questo file.
#
#   makepkg -si      (dalla root del repository, dove sta questo file)
#
# L'app è la stessa PWA in una finestra Electron (l'electron44 di sistema), con il backend
# FastAPI e il motore di Anki che girano sul computer su una copia locale della collezione
# (~/.local/share/anki-studio). La sync con AnkiWeb la tiene allineata al server cloud e agli
# altri dispositivi. Dettagli in packaging/arch/README.md.
#
# Come per XMap Studio: niente clone né download del repository. A ogni build si aggiorna
# `main` del clone locale da origin (fetch + fast-forward, senza cambiare il branch in cui
# sei) e si esporta quel commit in src/ con `git archive`. Modifiche non committate e altri
# branch non entrano nel pacchetto. Per provare un altro commit (es. il branch su cui stai
# lavorando): ANKI_STUDIO_REF=HEAD makepkg -si (niente fetch, si compila quel commit).
#
# Versione: r<numero di commit>.g<hash> del commit compilato (pacman -Q anki-studio-git
# dice quale commit è installato; la stessa stringa compare nelle Informazioni dell'app e in
# /api/health). Si calcola qui sotto quando makepkg legge il file, non con una funzione
# pkgver(): così makepkg non riscrive il PKGBUILD e il clone resta pulito per i git pull.

_pkgname=anki-studio
pkgname=$_pkgname-git
url='https://github.com/gioelerosana/anki-studio'

# makepkg rilegge il PKGBUILD più volte (anche dentro fakeroot): `main` si aggiorna e il
# commit si fissa alla prima lettura, poi passa alle successive via ambiente.
if [[ -z ${_ANKI_GIT_COMMIT:-} ]]; then
  _ANKI_GIT_REPO=$(git -C "$startdir" rev-parse --show-toplevel) || exit 1
  if [[ -n ${ANKI_STUDIO_REF:-} ]]; then
    _ANKI_GIT_REF=$ANKI_STUDIO_REF
  else
    _ANKI_GIT_REF=refs/heads/main
    if git -C "$_ANKI_GIT_REPO" fetch --quiet origin main; then
      if [[ $(git -C "$_ANKI_GIT_REPO" branch --show-current) == main ]]; then
        # Sei su main: pull in fast-forward (si ferma se ci sono conflitti).
        git -C "$_ANKI_GIT_REPO" merge --ff-only --quiet FETCH_HEAD \
          || echo "==> ATTENZIONE: main non aggiornato (non in fast-forward o modifiche locali in conflitto)" >&2
      else
        # Altro branch: si sposta solo il ref di main, il working tree non cambia. Fallisce
        # (con l'avviso) se main è aperto in un altro worktree: lì serve un git pull.
        git -C "$_ANKI_GIT_REPO" fetch --quiet origin main:main \
          || echo "==> ATTENZIONE: main locale non aggiornato (non in fast-forward con origin/main, o aperto in un altro worktree)" >&2
      fi
    else
      echo "==> ATTENZIONE: fetch di origin/main fallito, uso il main locale" >&2
    fi
  fi
  _ANKI_GIT_COMMIT=$(git -C "$_ANKI_GIT_REPO" rev-parse --verify --quiet "$_ANKI_GIT_REF^{commit}") || {
    echo "==> ERRORE: $_ANKI_GIT_REF non trovato in $_ANKI_GIT_REPO" >&2
    exit 1
  }
  _ANKI_GIT_PKGVER="r$(git -C "$_ANKI_GIT_REPO" rev-list --count "$_ANKI_GIT_COMMIT").g${_ANKI_GIT_COMMIT:0:7}"
  # Il virtualenv del backend vale per una sola minor di Python (lib/python3.X): il
  # pacchetto lo dichiara, così pacman avvisa quando Arch passa alla successiva e va ricompilato.
  _ANKI_PY=$(python -c 'import sys; print("%d.%d" % sys.version_info[:2])') || exit 1
  export _ANKI_GIT_REPO _ANKI_GIT_COMMIT _ANKI_GIT_PKGVER _ANKI_PY
fi

pkgver=$_ANKI_GIT_PKGVER
pkgrel=1
pkgdesc='Interfaccia minimale ad Anki, con una copia locale della collezione sincronizzata con AnkiWeb (development build)'
arch=('x86_64')
license=('unknown')
provides=("$_pkgname")
conflicts=("$_pkgname")
_electron=electron44
depends=("$_electron" "python>=$_ANKI_PY" "python<${_ANKI_PY%.*}.$(( ${_ANKI_PY#*.} + 1 ))")
# pnpm serve nel PATH (anche installato fuori da pacman).
makedepends=('git' 'nodejs')
options=('!strip' '!debug')
# Nessun `source`: launcher e .desktop (in packaging/arch/) si leggono dal commit esportato.

_lib=/usr/lib/$_pkgname

prepare() {
  # Copia esatta del commit, senza la cartella .git.
  rm -rf "$srcdir/$_pkgname"
  mkdir -p "$srcdir/$_pkgname"
  git -C "$_ANKI_GIT_REPO" archive --format=tar "$_ANKI_GIT_COMMIT" \
    | bsdtar -xf - -C "$srcdir/$_pkgname"
}

build() {
  cd "$_pkgname"
  # Electron arriva dal pacchetto di sistema: niente download del binario npm.
  export ELECTRON_SKIP_BINARY_DOWNLOAD=1
  pnpm install --frozen-lockfile --prefer-offline
  APP_VERSION="$pkgver" pnpm --filter @anki-studio/web build
  pnpm --filter @anki-studio/desktop build

  # Backend: dipendenze con gli hash del lock, solo wheel (niente compilazioni), nel Python
  # di sistema. Il lock è lo stesso dell'immagine Docker.
  rm -rf backend/.venv
  python -m venv backend/.venv
  # --no-compile: i .pyc si generano in package(), con i percorsi finali (vedi lì)
  backend/.venv/bin/python -m pip install --quiet --disable-pip-version-check --no-input \
    --no-compile --require-hashes --only-binary=:all: -r backend/requirements.lock
}

package() {
  cd "$_pkgname"
  local app="$pkgdir$_lib"

  # Stessa struttura del repository: apps/desktop/dist/main.js cerca backend/ e apps/web/dist
  # tre livelli sopra di sé.
  install -d "$app/apps/desktop" "$app/apps/web" "$app/backend"
  cp -a apps/desktop/dist apps/desktop/package.json "$app/apps/desktop/"
  printf '{"version":"%s","revision":"%s"}\n' "$pkgver" "$_ANKI_GIT_COMMIT" \
    > "$app/apps/desktop/version.json"
  cp -a apps/web/dist "$app/apps/web/dist"
  cp -a backend/app "$app/backend/app"
  cp -a backend/.venv "$app/backend/.venv"
  # Il venv è stato creato in src/: gli script in bin/ puntano lì. L'app usa solo
  # `python -m uvicorn`, ma gli shebang restano giusti per chi apre il venv a mano.
  grep -rlI "^#!$srcdir" "$app/backend/.venv/bin" | while read -r f; do
    sed -i "1s|^#!.*/bin/python|#!$_lib/backend/.venv/bin/python|" "$f"
  done
  sed -i "s|$srcdir/$_pkgname|$_lib|g" "$app/backend/.venv/pyvenv.cfg" \
    "$app/backend/.venv/bin/activate"* 2>/dev/null || true
  # il venv di Python 3.14 crea anche bin/𝜋thon → python: bsdtar non sa archiviare il nome
  find "$app/backend/.venv/bin" -maxdepth 1 -type l ! -name 'python*' -delete
  find "$app/backend/app" -name __pycache__ -prune -exec rm -rf {} +
  # bytecode compilato qui, con i percorsi di /usr e non di src/: in /usr il backend non può
  # scriverlo da sé, e senza partirebbe più lento a ogni avvio
  python -m compileall -q -j0 -s "$pkgdir" -p / "$app/backend/app" "$app/backend/.venv/lib"

  sed "s/@ELECTRON@/$_electron/" packaging/arch/anki-studio.sh > anki-studio.launcher
  install -Dm755 anki-studio.launcher "$pkgdir/usr/bin/$_pkgname"
  install -Dm644 packaging/arch/org.joel.anki_studio.desktop \
    "$pkgdir/usr/share/applications/org.joel.anki_studio.desktop"
  install -Dm644 apps/web/public/icon.svg \
    "$pkgdir/usr/share/icons/hicolor/scalable/apps/org.joel.anki_studio.svg"
  install -Dm644 apps/web/public/icon-256.png \
    "$pkgdir/usr/share/icons/hicolor/256x256/apps/org.joel.anki_studio.png"
  install -Dm644 apps/web/public/icon-512.png \
    "$pkgdir/usr/share/icons/hicolor/512x512/apps/org.joel.anki_studio.png"
}

#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" || "$ROOT" != "/Users/mehran.shabanii/OpenMontage" ]]; then
  echo "Run this from /Users/mehran.shabanii/OpenMontage." >&2
  exit 2
fi
cd "$ROOT"

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Refusing: current branch is not main." >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
  echo "Refusing: the worktree has tracked or untracked changes. Commit/stash them first." >&2
  git status --short
  exit 2
fi
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing executable .venv/bin/python." >&2
  exit 2
fi

# Pull the registered migration and record the exact rollback point.
git pull --ff-only origin main
START="$(git rev-parse HEAD)"
FINISHED=0

rollback() {
  status=$?
  if [[ "$FINISHED" -eq 0 ]]; then
    echo "Film Type 2.12 did not pass every gate; restoring $START." >&2
    git reset --hard "$START" >/dev/null
    git clean -fd >/dev/null
  fi
  exit "$status"
}
trap rollback ERR INT TERM

PY="$ROOT/.venv/bin/python"

# The migration asserts every source anchor and the immutable 2.11 canonical hash
# before writing. It computes the 2.12 canonical hash from the resulting JSON.
"$PY" tools/dev/apply_film_type_212.py

# Validate the complete implementation before committing anything.
"$PY" -m pytest tests/lib/ -q
npm ci --prefix remotion-composer
(
  cd remotion-composer
  ./node_modules/.bin/tsc --noEmit
)
OPENMONTAGE_BROWSER_TESTS=1 "$PY" -m unittest tests.lib.test_persian_ranked_browser -q

# Temporary execution files must not survive the verified source commit.
rm -f \
  tools/dev/apply_film_type_212.py \
  tools/dev/finish_film_type_212.sh \
  .github/workflows/apply-film-type-212.yml

git add -A
if git diff --cached --quiet; then
  echo "Refusing: migration produced no source changes." >&2
  exit 3
fi

git commit -m "fix: enforce Film Type subject and brand separation"
git push origin main
FINISHED=1
trap - ERR INT TERM

echo
printf 'Film Type 2.12 is committed and pushed at %s\n' "$(git rev-parse HEAD)"
printf '2.12 profile: '
"$PY" - <<'PY'
import hashlib, json
from pathlib import Path
p = json.loads(Path('styles/persian-footage/film-type.json').read_text(encoding='utf-8'))
raw = json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
print(f"{p['profileVersion']} / layout {p['layoutVersion']} / {hashlib.sha256(raw).hexdigest()}")
PY

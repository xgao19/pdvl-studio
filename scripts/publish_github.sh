#!/usr/bin/env bash
set -euo pipefail
# Run only after inspecting files and signing in via `gh auth login`.
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if ! command -v gh >/dev/null; then
  echo "Install GitHub CLI: https://cli.github.com/" >&2
  exit 1
fi
if [[ -z "${1:-}" ]]; then echo "Usage: $0 OWNER/pdvl-studio [--public]" >&2; exit 1; fi
VISIBILITY="${2:---private}"
if [[ "$VISIBILITY" != "--private" && "$VISIBILITY" != "--public" ]]; then
  echo "Visibility must be --private or --public" >&2;exit 1
fi
git init
# Do not stage untracked secrets even if .gitignore was changed.
git add .gitignore LICENSE README.md pyproject.toml AGENTS.md .env.example configs docs pdvl web worker scripts tests .github
git commit -m "Initialize PDVL Studio" || true
gh repo create "$1" "$VISIBILITY" --source=. --remote=origin --push

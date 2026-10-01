#!/usr/bin/env bash
# Assemble locale packs GO_Mac_Locale_<Language>/ from the Steam depots in depots/.
# Thin wrapper: the pack layout lives in assemble_locales.py.
#
#   ./assemble_locales.sh                  # every language
#   ./assemble_locales.sh german french    # selected languages
#   ./assemble_locales.sh --dry-run        # report only, write nothing
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$ROOT/assemble_locales.py" "$@"

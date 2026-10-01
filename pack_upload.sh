#!/bin/bash
# Pack assembled locale trees into release zips, upload them to GitHub and write the site catalog.
#
# Trees: GO_Mac_Locale_<Language>/ from ./assemble_locales.sh.
# Catalog: ../general_online_zh/public/api/locales.json — the site itself is deployed separately.
#
# Usage:
#   ./pack_upload.sh                    # every built pack: zip + upload + catalog
#   ./pack_upload.sh --no-upload        # zip + catalog, nothing leaves the machine
#   ./pack_upload.sh German French      # selected packs
set -euo pipefail

cd "$(dirname "$0")"

REPO="${REPO:-Okladnoj/GeneralsOnline-MacLocales}"
TAG="${TAG:-v1.0}"
MAX_BYTES=$((2 * 1024 * 1024 * 1024))
UPLOAD=1
TARGETS=()

for arg in "$@"; do
    case "$arg" in
        --no-upload) UPLOAD=0 ;;
        --upload) UPLOAD=1 ;;
        -*)
            echo "unknown option: $arg" >&2
            exit 1
            ;;
        *) TARGETS+=("$arg") ;;
    esac
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
    for tree in GO_Mac_Locale_*/; do
        [[ -d "$tree" ]] || continue
        tree="${tree%/}"
        TARGETS+=("${tree#GO_Mac_Locale_}")
    done
fi

if [[ ${#TARGETS[@]} -eq 0 ]]; then
    echo "no GO_Mac_Locale_*/ trees — run ./assemble_locales.sh first" >&2
    exit 1
fi

human_size() {
    awk -v bytes="$1" 'BEGIN {
        split("B KB MB GB", units)
        unit = 1
        while (bytes >= 1024 && unit < 4) { bytes /= 1024; unit++ }
        printf (unit == 1 ? "%d %s" : "%.1f %s"), bytes, units[unit]
    }'
}

ensure_release() {
    if gh release view "$TAG" --repo "$REPO" > /dev/null; then
        return
    fi

    echo "🏷  Creating release $TAG in $REPO ..."
    gh release create "$TAG" --repo "$REPO" --latest \
        --title "Locale packs $TAG" \
        --notes "Voice, movie and texture packs per language, installed by the Generals Online macOS launcher."
}

pack() {
    local language="$1"
    local tree="GO_Mac_Locale_$language"
    local zip="$tree.zip"

    if [[ ! -f "$tree/locale.json" ]]; then
        echo "missing $tree/locale.json — run ./assemble_locales.sh first" >&2
        exit 1
    fi

    echo "📦 Packing $tree → $zip ..."
    rm -f "$zip"
    (cd "$tree" && zip -qr "../$zip" . -x "*.DS_Store")

    local size
    size=$(stat -f%z "$zip")
    echo "   size: $(human_size "$size")"
    if (( size >= MAX_BYTES )); then
        echo "❌ $zip is >= 2 GiB" >&2
        exit 1
    fi

    if (( UPLOAD )); then
        echo "📤 Uploading $zip → $REPO@$TAG ..."
        gh release upload "$TAG" "$zip" --repo "$REPO" --clobber
    fi
}

if (( UPLOAD )); then
    ensure_release
fi

for language in "${TARGETS[@]}"; do
    pack "$language"
done

python3 ./assemble_locales.py --catalog

if (( UPLOAD )); then
    echo "✅ Done! Packed, uploaded and catalogued. Deploy the site to publish locales.json."
else
    echo "✅ Done! Packed and catalogued (no upload)."
fi

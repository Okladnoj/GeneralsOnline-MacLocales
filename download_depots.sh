#!/bin/bash
# Download the Steam language depots of Zero Hour (app 2732960) into depots/<language>/.
# Raw original game data: never committed, input of assemble_locales.sh.
#
# Usage:
#   ./download_depots.sh                  # every language, already downloaded ones are skipped
#   ./download_depots.sh english german
#   STEAM_LOGIN=<login> ./download_depots.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
APP_ID="2732960"
STEAMCMD_DIR="$HOME/Library/Application Support/Generals Online/steamcmd"
STEAM_CLIENT_DIR="$HOME/Library/Application Support/Steam"
OUT_DIR="${OUT_DIR:-$ROOT/depots}"
ALL_LANGUAGES="english german french spanish italian koreana tchinese polish brazilian"

fail() {
    echo "[✗] $*" >&2
    exit 1
}

depot_of() {
    case "$1" in
        english) echo 2732962 ;;
        german) echo 2732963 ;;
        french) echo 2732964 ;;
        tchinese) echo 2732965 ;;
        koreana) echo 2732966 ;;
        italian) echo 2732967 ;;
        polish) echo 2732968 ;;
        brazilian) echo 2732969 ;;
        spanish) echo 2748391 ;;
        *) return 1 ;;
    esac
}

requested_languages() {
    if [ "$#" -eq 0 ]; then
        echo "$ALL_LANGUAGES"
        return
    fi

    echo "$*"
}

pending_languages() {
    local pending=""
    for language in $LANGUAGES; do
        depot_of "$language" > /dev/null || fail "Unknown language: $language (known: $ALL_LANGUAGES)"

        if [ -d "$OUT_DIR/$language" ]; then
            echo "[=] $language already in $OUT_DIR/$language, skipped" >&2
            continue
        fi

        pending="$pending $language"
    done

    echo "$pending"
}

search_roots() {
    for root in "$STEAMCMD_DIR" "$STEAM_CLIENT_DIR"; do
        if [ -d "$root" ]; then
            echo "$root"
        fi
    done
}

find_depot_dir() {
    local depot="$1"
    local roots=()
    while IFS= read -r root; do
        roots+=("$root")
    done < <(search_roots)

    find "${roots[@]}" -type d -name "depot_$depot" -path "*app_$APP_ID*" | head -1
}

collect_depot() {
    local language="$1"
    local depot
    depot="$(depot_of "$language")"

    local source
    source="$(find_depot_dir "$depot")"
    if [ -z "$source" ]; then
        echo "[✗] $language: depot_$depot not found after download" >&2
        return
    fi

    mv "$source" "$OUT_DIR/$language"
    echo "[✓] $language: $(du -sh "$OUT_DIR/$language" | cut -f1) → $OUT_DIR/$language"
}

[ -x "$STEAMCMD_DIR/steamcmd" ] || fail "steamcmd not found in $STEAMCMD_DIR — install the game through the launcher first"

LANGUAGES="$(requested_languages "$@")"
PENDING="$(pending_languages)"
[ -n "${PENDING// /}" ] || { echo "[=] Nothing to download"; exit 0; }

STEAM_LOGIN="${STEAM_LOGIN:-}"
if [ -z "$STEAM_LOGIN" ]; then
    read -r -p "Steam login: " STEAM_LOGIN
fi
[ -n "$STEAM_LOGIN" ] || fail "Steam login is empty"

mkdir -p "$OUT_DIR"

DOWNLOAD_ARGS=()
for language in $PENDING; do
    DOWNLOAD_ARGS+=(+download_depot "$APP_ID" "$(depot_of "$language")")
done

echo "[*] Downloading:$PENDING"
echo "[*] steamcmd will ask for the password and Steam Guard code"

cd "$STEAMCMD_DIR"
./steamcmd \
    +@ShutdownOnFailedCommand 0 \
    +@sSteamCmdForcePlatformType windows \
    +login "$STEAM_LOGIN" \
    "${DOWNLOAD_ARGS[@]}" \
    +quit

for language in $PENDING; do
    collect_depot "$language"
done

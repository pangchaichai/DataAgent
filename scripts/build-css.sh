#!/bin/bash
# Build Tailwind CSS from source
# Usage: ./scripts/build-css.sh [--watch]
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TAILWIND="$PROJECT_DIR/tools/bin/tailwindcss"
INPUT="$PROJECT_DIR/ui/src/input.css"
OUTPUT="$PROJECT_DIR/ui/dist/styles.css"

if [ ! -f "$TAILWIND" ]; then
    echo "Tailwind CLI not found. Downloading..."
    mkdir -p "$(dirname "$TAILWIND")"
    curl -sL https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-x64 -o "$TAILWIND"
    chmod +x "$TAILWIND"
fi

mkdir -p "$(dirname "$OUTPUT")"

if [ "$1" = "--watch" ]; then
    echo "Watching for changes..."
    "$TAILWIND" -i "$INPUT" -o "$OUTPUT" --watch
else
    echo "Building CSS..."
    "$TAILWIND" -i "$INPUT" -o "$OUTPUT" --minify
    echo "Done: $OUTPUT ($(wc -c < "$OUTPUT") bytes)"
fi

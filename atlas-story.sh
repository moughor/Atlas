#!/bin/bash
# Atlas Agent Context Generator
# Usage: ./atlas-story.sh SYGMA-12345 /path/to/story.txt
#
# Generates Atlas context package for a Jira story, ready to give to Kiro/Codex.
# Requires: Atlas .venv with atlas CLI installed, snapshot at .atlas/ass/latest.ass in target repo.

set -e

if [ $# -lt 2 ]; then
    echo "Usage: $0 <STORY-ID> <STORY-FILE>"
    echo "Example: $0 SYGMA-64432 /home/meskeda/Documents/AtlasContexts/sygma-64432-story.txt"
    exit 1
fi

STORY_ID=$1
STORY_FILE=$2
SYGMA_REPO=/home/meskeda/git/sygma/sygma
OUTPUT_DIR=/home/meskeda/Documents/AtlasContexts/$STORY_ID
ATLAS_BIN=/home/meskeda/Documents/myAI/Atlas-main/.venv/bin/atlas

if [ ! -f "$STORY_FILE" ]; then
    echo "ERROR: Story file not found: $STORY_FILE"
    exit 1
fi

if [ ! -f "$ATLAS_BIN" ]; then
    echo "ERROR: Atlas binary not found: $ATLAS_BIN"
    exit 1
fi

echo "=== Atlas Agent Context ==="
echo "Story:   $STORY_ID"
echo "File:    $STORY_FILE"
echo "Repo:    $SYGMA_REPO"
echo "Output:  $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

echo "Running atlas agent context..."
$ATLAS_BIN agent context \
    "$SYGMA_REPO" \
    --story-file "$STORY_FILE" \
    --output "$OUTPUT_DIR"

echo ""
echo "=== Done ==="
echo "Output directory: $OUTPUT_DIR"
echo ""
echo "Files generated:"
ls -la "$OUTPUT_DIR"
echo ""
echo "┌─────────────────────────────────────────────────────┐"
echo "│ Give to Kiro:                                       │"
echo "│   1. Original story file: $STORY_FILE"
echo "│   2. $OUTPUT_DIR/context.md"
echo "│   3. $OUTPUT_DIR/graph.json"
echo "└─────────────────────────────────────────────────────┘"

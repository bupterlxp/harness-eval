#!/bin/bash

# Research Agent Harness
# A general-purpose deep research harness

# Usage:
# ./run.sh -p "Your research question"
# ./run.sh --prompt "Your research question" --output-dir ./output

set -e

# Default parameters
PROMPT=""
OUTPUT_DIR="./output"
MIN_SOURCES=10
MAX_WORDS=4000
MAX_HOPS=3

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case "$1" in
        -p|--prompt)
            PROMPT="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --min-sources)
            MIN_SOURCES="$2"
            shift 2
            ;;
        --max-words)
            MAX_WORDS="$2"
            shift 2
            ;;
        --max-hops)
            MAX_HOPS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check if prompt is provided
if [[ -z "$PROMPT" ]]; then
    echo "Usage: $0 -p 'research question' [options]"
    echo "Options:"
    echo "  --output-dir DIR      Output directory (default: ./output)"
    echo "  --min-sources NUM     Minimum sources required (default: 10)"
    echo "  --max-words NUM       Maximum report words (default: 4000)"
    echo "  --max-hops NUM        Maximum research hops (default: 3)"
    exit 1
fi

# Activate virtual environment if exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Run the harness
python -m harness \
    -p "$PROMPT" \
    --output-dir "$OUTPUT_DIR" \
    --min-sources "$MIN_SOURCES" \
    --max-words "$MAX_WORDS" \
    --max-hops "$MAX_HOPS"

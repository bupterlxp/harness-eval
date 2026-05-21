#!/bin/bash
"""Wrapper script for the creative writing harness"""

set -e

# Change to the directory where this script is located
cd "$(dirname "${BASH_SOURCE[0]}")"

# Run the harness with Python 3
exec python3 -m harness "$@"
#!/usr/bin/env python3
"""Simple command-line interface for the data analysis harness"""

import sys
from pathlib import Path

# Add the current directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from harness.__main__ import main

if __name__ == "__main__":
    main()
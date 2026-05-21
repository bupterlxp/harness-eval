#!/usr/bin/env python3
"""Simple test harness runner"""

import sys
import os
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from harness.__main__ import main

if __name__ == "__main__":
    # Override sys.argv to test with our data
    import sys
sys.argv = [
        "harness.py",
        "-p", "Analyze sales trends",
        "--output-dir", "./test_run",
        "--max-steps", "5"
    ]
    main()
"""
Pytest configuration and test path setup.
"""

import os
import sys

# Ensure src/ is on sys.path
src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

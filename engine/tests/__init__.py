"""Tests for the engine. Importing this package puts the engine folder on the import path, so
`python3 -m unittest engine.tests.test_setup` works from the repository root."""
import os
import sys

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

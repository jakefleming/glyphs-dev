"""Run Curse's synthetic regression tests outside Glyphs."""
from pathlib import Path
import unittest

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parents[1] / "Plugins/Curse"), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(not result.wasSuccessful())

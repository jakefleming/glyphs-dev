"""Run Curse's synthetic regression tests outside Glyphs."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "Plugins/Curse/test_curse.py"), run_name="__main__")

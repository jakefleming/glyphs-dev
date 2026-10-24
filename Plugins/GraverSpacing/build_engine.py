"""Build the vendored, validated engine sources; does not modify Graver's checkout."""
from pathlib import Path
import argparse, subprocess
root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, help='Optional test output; defaults to the sibling plugin bundle')
args = parser.parse_args()
binary = args.output or root.parent / 'GraverSpacing.glyphsPlugin/Contents/Resources/graver-spacing-engine'
binary.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(['swiftc', '-O', '-swift-version', '5', '-module-cache-path', str(root / 'module-cache'), *map(str, sorted((root / 'engine').glob('*.swift'))), '-o', str(binary)], check=True)
print(binary)

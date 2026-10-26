"""Copied to the bundled application's source root by the build script."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdvl.desktop import main

main()

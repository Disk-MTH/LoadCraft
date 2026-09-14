"""Packaging entry point: delegates to the package's own main().

PyInstaller cannot freeze `loadcraft/__main__.py` directly (its relative
imports need a package context), so the freeze entry is this top-level
module, which imports the package normally.
"""

from loadcraft.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())

"""Backward-compat wrapper — the implementation moved into scqo v0.4.0 (scqo.cli).

Equivalent (works from any directory in the right venv):  scqo devices ...
"""

from scqo.cli.devices import main

if __name__ == "__main__":
    raise SystemExit(main())

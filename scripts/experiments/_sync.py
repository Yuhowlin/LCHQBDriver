"""Regenerate the launcher stubs (engine: `scqo sync-launchers`).

    python scripts/experiments/_sync.py

Run after promoting/registering a new experiment (requires this repo's venv, so the
catalog fills via the scqo.experiments entry point). Stubs are AUTO-GENERATED.
"""

import sys
from pathlib import Path

from scqo.cli.sync_launchers import main

if __name__ == "__main__":
    sys.exit(main(["--dir", str(Path(__file__).resolve().parent)]))

"""Run any cataloged experiment by name — the one script a student needs.

    python scripts/run_experiment.py                                # list the catalog
    python scripts/run_experiment.py qubit_ramsey --qubits q1
    python scripts/run_experiment.py resonator_spectroscopy --qubits q0 q1 \
        --set frequency_span_hz=15e6 --tag cooldown7 --note "after wiring fix"
    python scripts/run_experiment.py qubit_power_rabi --params my_params.json

Prefer a per-experiment command? Every cataloged experiment also has its own
launcher under scripts/experiments/ (same flags; --help shows its parameters).

Where data goes, which device this is, and which backend runs are read from
``~/.scqo/config.toml`` (see scqo.labconfig) — never edited here. Every run is saved
under the lab's data_root and searchable with ``scripts/find_runs.py``.
"""

from __future__ import annotations

import sys

from _cli import run_experiment_cli

if __name__ == "__main__":
    sys.exit(run_experiment_cli(None, doc=__doc__))

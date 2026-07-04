"""Shared helper for the student scripts: build a Session from the lab config.

Reads ``~/.scqo/config.toml`` (or ``$SCQO_CONFIG`` / ``--config PATH``) so scripts run
without editing any repo code. With no config file everything still works: simulated
backend, demo qubits, nothing persisted.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make `import lchqb` work when the repo is not pip-installed: running
# `python scripts/<name>.py` puts scripts/ on sys.path, not the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scqo import LabConfig, Session, load_lab_config, make_session
from scqo.testing import InMemoryDevice, SimulatedBackend

import lchqb.experiments  # noqa: F401  registers the Qblox experiments into the catalog

#: Demo device used when the lab config selects the simulated backend (or is absent).
DEMO_QUBITS = {
    "q0": {"readout_freq": 5.95e9, "drive_freq": 3.87e9, "pi_amp": 0.20},
    "q1": {"readout_freq": 6.05e9, "drive_freq": 4.01e9, "pi_amp": 0.18},
}


def build_session(config_path: str | None = None) -> tuple[Session, LabConfig]:
    """Load the lab config and return a wired Session (datastore, state file, tags)."""
    cfg = load_lab_config(config_path)
    if cfg.backend == "qblox":
        from lchqb.backend import QbloxBackend

        qblox = cfg.extras.get("qblox", {})
        backend = QbloxBackend.load(
            config_dir=qblox.get("config_dir", "./qblox_state"),
            output_dir=qblox.get("output_dir"),
        )
    elif cfg.backend == "simulated":
        backend = SimulatedBackend(InMemoryDevice(DEMO_QUBITS))
    else:
        raise SystemExit(
            f"unsupported backend {cfg.backend!r} in {cfg.source or 'defaults'} "
            "(this repo drives 'qblox' or 'simulated'; 'qm' scripts live in LCHQMDriver)"
        )
    return make_session(backend, cfg), cfg

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


def default_qubits(sess: Session) -> list[str]:
    """Measurable qubits for 'run on everything' defaults.

    The device tree also contains couplers (lab convention: ``c*``, e.g. ``c12``)
    modeled as transmon elements without a usable readout port — measuring one
    fails on hardware (``c12:res_unused was not found in the connectivity``).
    Only ``q*`` elements are measurement targets by default; pass --qubits to
    override explicitly.
    """
    return [q for q in sess.device_state() if q.startswith("q")]


def _qblox_config_dir(cfg: LabConfig, *needed: str) -> Path:
    """Resolve [qblox] config_dir and check the required files exist (clear errors)."""
    config_dir = Path(cfg.extras.get("qblox", {}).get("config_dir", "./qblox_state"))
    missing = [n for n in needed if not (config_dir / n).is_file()]
    if missing:
        raise SystemExit(
            f"backend {cfg.backend!r}: {', '.join(missing)} not found in {config_dir.resolve()}\n"
            "Point [qblox] config_dir in the lab config at a folder holding your device\n"
            "config (copy your dut_config_*.json there as dut_config.json" +
            (" and hw_config_*.json as hw_config.json" if "hw_config.json" in needed else "") + ")."
        )
    return config_dir


def build_session(config_path: str | None = None) -> tuple[Session, LabConfig]:
    """Load the lab config and return a wired Session (datastore, state file, tags).

    Backends: ``simulated`` (demo qubits, synthetic data) · ``qblox_sim`` (your REAL
    device config as a virtual twin: real qubits/values, synthetic data, writebacks
    persisted to the working dut_config.json) · ``qblox`` (real cluster).
    """
    cfg = load_lab_config(config_path)
    if cfg.backend == "qblox":
        from lchqb.backend import QbloxBackend

        config_dir = _qblox_config_dir(cfg, "dut_config.json", "hw_config.json")
        backend = QbloxBackend.load(
            config_dir=str(config_dir),
            output_dir=cfg.extras.get("qblox", {}).get("output_dir"),
        )
    elif cfg.backend == "qblox_sim":
        # Virtual twin: load the lab's REAL device tree, acquire simulated data.
        import lchqb.elements  # noqa: F401  register custom element types
        from qblox_scheduler import QuantumDevice

        from lchqb.backend.qblox_backend import QbloxDeviceModel

        dut = _qblox_config_dir(cfg, "dut_config.json") / "dut_config.json"
        device = QbloxDeviceModel(QuantumDevice.from_json_file(str(dut)), config_file=str(dut))
        backend = SimulatedBackend(device)
    elif cfg.backend == "simulated":
        backend = SimulatedBackend(InMemoryDevice(DEMO_QUBITS))
    else:
        raise SystemExit(
            f"unsupported backend {cfg.backend!r} in {cfg.source or 'defaults'} "
            "(this repo drives 'qblox', 'qblox_sim' or 'simulated'; 'qm' scripts live in LCHQMDriver)"
        )
    return make_session(backend, cfg), cfg

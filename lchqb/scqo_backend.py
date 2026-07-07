"""Qblox backend factory for the scqo CLI (entry-point group ``scqo.backends``, name ``qblox``).

Serves both modes of the family: ``qblox`` (real cluster) and ``qblox_sim`` (the
virtual twin: your REAL device tree, synthetic data, writebacks persisted to the
working dut_config.json). Vendor imports stay INSIDE the branches so loading this
module is cheap and vendor-free.
"""

from __future__ import annotations

from pathlib import Path

from scqo import LabConfig
from scqo.backend import Backend


def _config_dir(cfg: LabConfig, *needed: str) -> Path:
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


def build_backend(cfg: LabConfig) -> Backend:
    if cfg.backend == "qblox":
        from lchqb.backend import QbloxBackend

        config_dir = _config_dir(cfg, "dut_config.json", "hw_config.json")
        return QbloxBackend.load(
            config_dir=str(config_dir),
            output_dir=cfg.extras.get("qblox", {}).get("output_dir"),
        )
    if cfg.backend == "qblox_sim":
        # Virtual twin: load the lab's REAL device tree, acquire simulated data.
        import lchqb.elements  # noqa: F401  register custom element types
        from qblox_scheduler import QuantumDevice

        from lchqb.backend.qblox_backend import QbloxDeviceModel
        from scqo.testing import SimulatedBackend

        dut = _config_dir(cfg, "dut_config.json") / "dut_config.json"
        return SimulatedBackend(QbloxDeviceModel(QuantumDevice.from_json_file(str(dut)), config_file=str(dut)))
    raise SystemExit(f"the qblox driver builds 'qblox' or 'qblox_sim', got {cfg.backend!r}")

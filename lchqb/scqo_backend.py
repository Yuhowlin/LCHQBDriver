"""Qblox backend factory for the scqo CLI (entry-point group ``scqo.backends``, name ``qblox``).

The factory receives the device's SELECTED named setup record from its cooldown
registry (``[<cycle>.setup.<name>]`` — backend + note; since scqo v0.9 the vendor
folder is DERIVED from the keys and injected by ``load_cooldowns``):
``setup["instrument_config"]`` is the folder holding the vendor config files
under canonical names — ``dut_config.json`` + ``hw_config.json``. Vendor imports stay
INSIDE the function so loading this module is cheap and vendor-free. (The
virtual-twin ``qblox_sim`` mode was retired with v0.5.0; ``simulated`` — built into
scqo — is the practice mode.)
"""

from __future__ import annotations

from pathlib import Path

from scqo import LabConfig
from scqo.backend import Backend


def build_backend(cfg: LabConfig, setup: dict) -> Backend:
    if setup.get("backend") != "qblox":
        raise SystemExit(f"the qblox driver serves backend 'qblox', got {setup.get('backend')!r}")
    folder = Path(setup["instrument_config"])
    missing = [n for n in ("dut_config.json", "hw_config.json") if not (folder / n).is_file()]
    if missing:
        raise SystemExit(
            f"qblox setup: {', '.join(missing)} not found in {folder}\n"
            "Copy the vendor files there under canonical names "
            "(dut_config_*.json -> dut_config.json, hw_config_*.json -> hw_config.json)."
        )
    from lchqb.backend import QbloxBackend

    return QbloxBackend.load(config_dir=str(folder))

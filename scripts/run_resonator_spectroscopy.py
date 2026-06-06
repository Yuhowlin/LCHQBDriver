"""Manual end-to-end run of resonator spectroscopy.

Defaults to scqo's SimulatedBackend so it runs with no Qblox hardware. To run on a real
cluster, swap in QbloxBackend (see the commented lines) — nothing else changes.

    python scripts/run_resonator_spectroscopy.py
"""

from __future__ import annotations

import json

from scqo import Session
from scqo.testing import InMemoryDevice, SimulatedBackend

import lchqb.experiments  # noqa: F401  registers QbloxResonatorSpectroscopy into the catalog


def main() -> None:
    device = InMemoryDevice(
        {
            "q0": {"readout_freq": 5.95e9, "drive_freq": 3.87e9, "pi_amp": 0.20},
            "q1": {"readout_freq": 6.05e9, "drive_freq": 4.01e9, "pi_amp": 0.18},
        }
    )
    backend = SimulatedBackend(device)
    # Real hardware instead:
    # from lchqb.backend import QbloxBackend
    # backend = QbloxBackend.load(config_dir="./qblox_state", output_dir="./data")

    sess = Session(backend)

    print("readout_freq before:", {q: s["readout_freq"] for q, s in sess.device_state().items()})
    result = sess.run(
        "resonator_spectroscopy",
        {"qubits": ["q0", "q1"], "frequency_span_hz": 15e6, "num_points": 201},
    )
    print("result:", json.dumps(result, indent=2))
    print("readout_freq after: ", {q: s["readout_freq"] for q, s in sess.device_state().items()})


if __name__ == "__main__":
    main()

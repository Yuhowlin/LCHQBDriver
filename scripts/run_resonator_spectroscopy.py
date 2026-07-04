"""Manual end-to-end run of resonator spectroscopy (worked example).

Backend, data location and device name come from the lab config
(``~/.scqo/config.toml``) — with no config it runs on the SimulatedBackend and saves
nothing. For anything beyond this one experiment use ``scripts/run_experiment.py``.

    python scripts/run_resonator_spectroscopy.py [--qubits q0 q1] [--tag mytag]
"""

from __future__ import annotations

import argparse
import json

from _lab import build_session


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qubits", nargs="+", help="qubits to measure (default: all)")
    parser.add_argument("--span", type=float, default=15e6, help="frequency span in Hz")
    parser.add_argument("--points", type=int, default=201, help="number of sweep points")
    parser.add_argument("--tag", action="append", default=[], dest="tags")
    parser.add_argument("--config", help="lab config path")
    args = parser.parse_args()

    sess, _ = build_session(args.config)
    qubits = args.qubits or list(sess.device_state())

    print("readout_freq before:", {q: s["readout_freq"] for q, s in sess.device_state().items()})
    result = sess.run(
        "resonator_spectroscopy",
        {"qubits": qubits, "frequency_span_hz": args.span, "num_points": args.points},
        tags=args.tags,
    )
    print("result:", json.dumps(result, indent=2))
    print("readout_freq after: ", {q: s["readout_freq"] for q, s in sess.device_state().items()})


if __name__ == "__main__":
    main()

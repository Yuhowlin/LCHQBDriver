"""Run any cataloged experiment by name — the one script a student needs.

    python scripts/run_experiment.py                                # list the catalog
    python scripts/run_experiment.py qubit_ramsey --qubits q1
    python scripts/run_experiment.py resonator_spectroscopy --qubits q0 q1 \
        --set frequency_span_hz=15e6 --tag cooldown7 --note "after wiring fix"
    python scripts/run_experiment.py qubit_power_rabi --params my_params.json

Where data goes, which device this is, and which backend runs are read from
``~/.scqo/config.toml`` (see scqo.labconfig) — never edited here. Every run is saved
under the lab's data_root and searchable with ``scripts/find_runs.py``.
"""

from __future__ import annotations

import argparse
import json
import os

from _lab import build_session


def _parse_value(text: str):
    """Parse a --set value: JSON if it looks like it, bare string otherwise."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("experiment", nargs="?", help="experiment name; omit to list the catalog")
    parser.add_argument("--params", help="parameters as a JSON file path or an inline JSON string")
    parser.add_argument("--qubits", nargs="+", help="qubits to measure (default: all in the device)")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="override one parameter (repeatable), e.g. --set num_points=201")
    parser.add_argument("--tag", action="append", default=[], dest="tags",
                        help="searchable tag for this run (repeatable)")
    parser.add_argument("--note", default="", help="free-text note stored with the run")
    parser.add_argument("--no-update", action="store_true",
                        help="analyze only; do not write fitted values back to the device")
    parser.add_argument("--config", help="lab config path (default: $SCQO_CONFIG or ~/.scqo/config.toml)")
    args = parser.parse_args()

    sess, cfg = build_session(args.config)

    if not args.experiment:
        print(f"# lab config: {cfg.source or 'built-in defaults (simulated, nothing saved)'}")
        for entry in sess.catalog():
            print(f"{entry['name']:32s} {entry['description']}")
        return

    params: dict = {}
    if args.params:
        if os.path.isfile(args.params):
            with open(args.params, encoding="utf-8") as f:
                params.update(json.load(f))
        else:
            params.update(json.loads(args.params))
    if args.qubits:
        params["qubits"] = args.qubits
    for item in args.set:
        key, _, value = item.partition("=")
        params[key] = _parse_value(value)
    params.setdefault("qubits", list(sess.device_state()))

    result = sess.run(args.experiment, params, update=not args.no_update, tags=args.tags, note=args.note)
    print(json.dumps(result, indent=2))
    if "data_path" in result:
        print(f"\nsaved: {result['data_path']}")


if __name__ == "__main__":
    main()

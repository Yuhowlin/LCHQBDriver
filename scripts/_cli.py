"""Shared CLI engine behind run_experiment.py and the scripts/experiments/ launchers.

`run_experiment_cli(None)` = generic form (experiment name as positional argument);
`run_experiment_cli("qubit_ramsey")` = fixed-experiment form used by the generated
launcher stubs, whose --help shows that experiment's own parameter schema.
"""

from __future__ import annotations

import argparse
import json
import os

from _lab import build_session, default_qubits


def _parse_value(text: str):
    """Parse a --set value: JSON if it looks like it, bare string otherwise."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _schema_epilog(experiment: str) -> str:
    """Human-readable parameter list from the experiment's pydantic schema."""
    from scqo import catalog  # experiments already registered via the _lab import

    entry = next((e for e in catalog() if e["name"] == experiment), None)
    if entry is None:
        return ""
    schema = entry["parameters_schema"]
    required = set(schema.get("required", []))
    lines = [entry["description"], "", "parameters (set with --set KEY=VALUE):"]
    for key, spec in schema.get("properties", {}).items():
        default = "(required)" if key in required else repr(spec.get("default", ""))
        lines.append(f"  {key:26s} {spec.get('type', ''):8s} default={default:16s} {spec.get('description', '')}")
    return "\n".join(lines)


def run_experiment_cli(experiment: str | None = None, doc: str | None = None) -> int:
    # --help prints during parsing, so the parameter epilog must be decided BEFORE the
    # real parse. In the generic form, peek at the command line for the experiment name
    # so `run_experiment.py qubit_power_rabi --help` shows that experiment's parameters.
    help_target = experiment
    if help_target is None:
        peek = argparse.ArgumentParser(add_help=False)
        peek.add_argument("experiment", nargs="?")
        help_target = peek.parse_known_args()[0].experiment

    parser = argparse.ArgumentParser(
        description=doc or __doc__,
        epilog=_schema_epilog(help_target) if help_target else None,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    if experiment is None:
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
    name = experiment or args.experiment

    sess, cfg = build_session(args.config)

    if not name:
        print(f"# lab config: {cfg.source or 'built-in defaults (simulated, nothing saved)'}")
        for entry in sess.catalog():
            tag = " [contrib]" if entry.get("maturity") == "contrib" else ""
            print(f"{entry['name'] + tag:32s} {entry['description']}")
        return 0

    params: dict = {}
    if args.params:
        try:
            if os.path.isfile(args.params):
                with open(args.params, encoding="utf-8") as f:
                    loaded = json.load(f)
            else:
                loaded = json.loads(args.params)
            if not isinstance(loaded, dict):
                raise SystemExit(f"--params must be a JSON object {{...}}, got {type(loaded).__name__}")
            params.update(loaded)
        except json.JSONDecodeError as err:
            msg = f"--params expects a JSON file path or inline JSON, got: {args.params!r} ({err})"
            if "=" in args.params and not args.params.lstrip().startswith("{"):
                msg += f"\nDid you mean:  --set {args.params}"
            else:
                msg += '\nExamples:  --params my_params.json   or   --params "{""num_points"": 201}"'
            raise SystemExit(msg)
    if args.qubits:
        params["qubits"] = args.qubits
    for item in args.set:
        key, _, value = item.partition("=")
        params[key] = _parse_value(value)
    params.setdefault("qubits", default_qubits(sess))

    result = sess.run(name, params, update=not args.no_update, tags=args.tags, note=args.note)
    print(json.dumps(result, indent=2))
    if "data_path" in result:
        print(f"\nsaved: {result['data_path']}")
    return 1 if result.get("error") else 0

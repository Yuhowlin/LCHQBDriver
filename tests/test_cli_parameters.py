"""The student CLI end-to-end with a standing parameters file (simulated backend).

Subprocess-based: exercises the real scripts exactly as a student runs them.
``scripts/_cli.py`` is a byte-identical mirror in LCHQMDriver, so this coverage
transfers; the test lives here only because tests sit outside the mirrored
``scripts/`` tree.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(tmp_path: Path, *args: str, parameters_toml: str | None = None) -> subprocess.CompletedProcess:
    """Run scripts/run_experiment.py against a temp lab config (simulated, persisted)."""
    lines = ["[lab]", 'backend = "simulated"', f"data_root = '{(tmp_path / 'data').as_posix()}'"]
    if parameters_toml is not None:
        params = tmp_path / "parameters.toml"
        params.write_text(parameters_toml, encoding="utf-8")
        lines.append(f"parameters_file = '{params.as_posix()}'")
    config = tmp_path / "config.toml"
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_experiment.py"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "SCQO_CONFIG": str(config)},
        cwd=REPO,
    )


def _result(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout.split("\nsaved:")[0])


def test_file_defaults_reach_the_saved_run(tmp_path):
    proc = _run(
        tmp_path,
        "resonator_spectroscopy",
        parameters_toml='[resonator_spectroscopy]\nnum_points = 51\nqubits = ["q0"]\n',
    )
    assert proc.returncode == 0, proc.stderr
    result = _result(proc)
    # file-supplied qubits applied — NOT masked by the all-device fallback (q0 AND q1)
    assert result["outcomes"] == {"q0": "successful"}
    saved = json.loads((Path(result["data_path"]) / "parameters.json").read_text(encoding="utf-8"))
    assert saved["num_points"] == 51
    # provenance goes to stderr so stdout stays parseable JSON
    assert "# parameter defaults from" in proc.stderr


def test_cli_set_beats_file_defaults(tmp_path):
    proc = _run(
        tmp_path,
        "resonator_spectroscopy",
        "--set",
        "num_points=99",
        parameters_toml="[resonator_spectroscopy]\nnum_points = 51\n",
    )
    assert proc.returncode == 0, proc.stderr
    saved = json.loads((Path(_result(proc)["data_path"]) / "parameters.json").read_text(encoding="utf-8"))
    assert saved["num_points"] == 99

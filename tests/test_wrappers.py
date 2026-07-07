"""Backward-compat surface: the scripts/ wrappers + the qblox backend entry point.

The real CLI coverage lives in SCQO/tests (test_cli_*.py) against the built-in
simulated backend; this smoke test only proves the driver-side glue: wrappers
forward to scqo.cli, regenerated stubs import cleanly, the `_lab` shim still serves
its old importers, and the `scqo.backends` entry point resolves to a working factory.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _env(tmp_path: Path) -> dict:
    config = tmp_path / "config.toml"
    config.write_text(
        f"[lab]\nbackend = \"simulated\"\ndata_root = '{(tmp_path / 'data').as_posix()}'\n",
        encoding="utf-8",
    )
    return {**os.environ, "SCQO_CONFIG": str(config), "SCQO_USER_CONFIG": "none"}


def test_wrapper_runs_end_to_end(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run_experiment.py"),
         "resonator_spectroscopy", "--qubits", "q0"],
        capture_output=True, text=True, env=_env(tmp_path), cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.split("\nsaved:")[0])
    assert result["outcomes"] == {"q0": "successful"}


def test_regenerated_stub_help(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "experiments" / "resonator_spectroscopy.py"), "--help"],
        capture_output=True, text=True, env=_env(tmp_path), cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    assert "frequency_span_hz" in proc.stdout  # schema epilog through scqo.cli


def test_lab_shim_still_serves_old_importers(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ai_loop_demo.py")],
        capture_output=True, text=True, env=_env(tmp_path), cwd=REPO / "scripts",
    )
    assert proc.returncode == 0, proc.stderr


def test_backend_entry_point_resolves(tmp_path, monkeypatch):
    """The scqo.backends entry point loads and the factory fails loudly (no hardware
    needed) when the config lacks the vendor working copy."""
    from importlib.metadata import entry_points

    import pytest

    from scqo import load_lab_config

    eps = {ep.name: ep for ep in entry_points(group="scqo.backends")}
    assert "qblox" in eps, "reinstall the editable (uv pip install -e .) to register entry points"
    factory = eps["qblox"].load()

    monkeypatch.setenv("SCQO_USER_CONFIG", "none")  # hermetic: no real ~/.scqo/user.toml
    config = tmp_path / "config.toml"
    config.write_text(
        f"[lab]\nbackend = \"qblox\"\n\n[qblox]\nconfig_dir = '{(tmp_path / 'empty').as_posix()}'\n",
        encoding="utf-8",
    )
    cfg = load_lab_config(str(config))
    with pytest.raises(SystemExit, match="dut_config.json"):
        factory(cfg)

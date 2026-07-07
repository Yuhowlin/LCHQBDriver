"""Backward-compat surface: the scripts/ wrappers + the qblox backend entry point.

The real CLI coverage lives in SCQO/tests (test_cli_*.py) against the built-in
simulated backend; this smoke test only proves the driver-side glue: wrappers
forward to scqo.cli, regenerated stubs import cleanly, the `_lab` shim still serves
its old importers, and the `scqo.backends` entry point resolves to a working factory
(v0.5.0 signature: build_backend(cfg, setup)).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO.parents[0] / "SCQO" / "tests" / "demo_instr_config"


def _env(tmp_path: Path) -> dict:
    data_root = tmp_path / "data"
    (data_root / "simdev").mkdir(parents=True)
    (data_root / "simdev" / "cooldowns.toml").write_text(
        '[cd1]\nstart = 2026-07-01\n[[cd1.setup]]\nsince = 2026-07-01\nbackend = "simulated"\n',
        encoding="utf-8",
    )
    config = tmp_path / "config.toml"
    config.write_text(
        f"[lab]\ndevice = \"simdev\"\ndata_root = '{data_root.as_posix()}'\n", encoding="utf-8"
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


def test_backend_entry_point_resolves(tmp_path):
    """The scqo.backends entry point loads and the v0.5.0 factory fails loudly (no
    hardware needed) when the setup's folder lacks the canonical vendor files."""
    from importlib.metadata import entry_points

    import pytest

    eps = {ep.name: ep for ep in entry_points(group="scqo.backends")}
    assert "qblox" in eps, "reinstall the editable (uv pip install -e .) to register entry points"
    factory = eps["qblox"].load()

    empty = tmp_path / "empty"
    empty.mkdir()
    setup = {"since": "2026-07-01", "backend": "qblox", "instrument_config": str(empty)}
    with pytest.raises(SystemExit, match="dut_config.json"):
        factory(None, setup)
    with pytest.raises(SystemExit, match="qblox"):
        factory(None, {"backend": "qm"})  # wrong family refused


def test_real_fixture_dut_config_parses(tmp_path):
    """The lab's real dut config (SCQO/tests/demo_instr_config) deserializes through
    the same path the factory uses (parse-grade; the fixture has no hw_config)."""
    import pytest

    src = FIXTURES / "QBlox_Scheduler" / "dut_config_AS_QRC.json"
    if not src.is_file():
        pytest.skip("SCQO checkout with demo_instr_config not found side-by-side")
    shutil.copy(src, tmp_path / "dut_config.json")

    import lchqb.elements  # noqa: F401  register custom element types
    from qblox_scheduler import QuantumDevice

    device = QuantumDevice.from_json_file(str(tmp_path / "dut_config.json"))
    assert device.elements  # the real device tree deserialized

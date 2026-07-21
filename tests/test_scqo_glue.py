"""Driver-side scqo glue: the `scqo` CLI works in THIS venv + the qblox factory.

The real CLI coverage lives in SCQO/tests (test_cli_*.py) against the built-in
simulated backend; this smoke test only proves the driver-side glue: the `scqo`
command runs end-to-end in the qblox venv, the per-repo demo scripts import
cleanly from scqo.cli, and the `scqo.backends` entry point resolves to a working
factory (build_backend(cfg, setup); the setup is a NAMED record — backend + note,
plus the DERIVED "instrument_config" vendor folder injected by scqo since v0.9).
The v0.4-era scripts/ wrapper layer and the launcher stubs were retired in v0.7.0.
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
        '[cd1]\nstart = 2026-07-01\n[cd1.setup.practice]\nbackend = "simulated"\n',
        encoding="utf-8",
    )
    # post-cutover a CONFIGURED device REQUIRES a component roster
    (data_root / "simdev" / "components.toml").write_text(
        'schema = 1\n'
        '[components.q0]\n'
        'physical   = "FixedTransmon"\n'
        'instrument = "ReadableTransmon"\n'
        'operations = ["rx", "readout"]\n'
        '[components.q0_res]\n'
        'physical = "Resonator"\n'
        '[components.q0_ro]\n'
        'physical = "ReadoutLine"\n'
        'members  = { transmon = "q0", resonator = "q0_res" }\n'
        '[components.q0_xy]\n'
        'physical = "XYControl"\n'
        'members  = { transmon = "q0" }\n',
        encoding="utf-8",
    )
    config = tmp_path / "config.toml"
    config.write_text(
        f"[lab]\ndevice = \"simdev\"\ndata_root = '{data_root.as_posix()}'\n", encoding="utf-8"
    )
    return {**os.environ, "SCQO_CONFIG": str(config), "SCQO_USER_CONFIG": "none"}


def test_scqo_run_end_to_end(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "scqo.cli", "run", "resonator_spectroscopy", "--targets", "q0"],
        capture_output=True, text=True, env=_env(tmp_path), cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout.split("\nsaved:")[0])
    assert result["outcomes"] == {"q0": "successful"}


def test_ai_loop_demo_runs(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ai_loop_demo.py")],
        capture_output=True, text=True, env=_env(tmp_path), cwd=REPO,
    )
    assert proc.returncode == 0, proc.stderr


def test_field_catalog_matches_implementation():
    """The declared field catalog cannot drift: per category, bindings plus the
    declared Unrealized entries cover EXACTLY scqo's pushed fields (a new core
    field fails here until this driver binds or declines it — the combo-release
    alarm), coupled names are real sibling fields, the vendor-only inventory
    collides with no declared neutral field, and the module is pure data
    (importable without qblox_scheduler — enforced on its import statements)."""
    import ast

    from scqo.categories import field_categories, pushed_fields

    from lchqb.backend import fieldmap

    pushed = set(pushed_fields("ReadableTransmon"))
    bindings = fieldmap.FIELD_BINDINGS["ReadableTransmon"]
    unrealized = fieldmap.UNREALIZED.get("ReadableTransmon", {})
    assert set(bindings) | set(unrealized) == pushed
    assert not set(bindings) & set(unrealized)  # realized XOR unrealized, never both
    for name, binding in bindings.items():
        assert binding.path, f"{name}: empty vendor path"
        assert set(binding.coupled) <= pushed - {name}, name
    for name, entry in unrealized.items():
        assert entry.category == "ReadableTransmon" and entry.field == name, name
        assert entry.reason, name
    assert not set(fieldmap.VENDOR_ONLY) & set(field_categories())
    assert all(v.path and v.doc for v in fieldmap.VENDOR_ONLY.values())

    # every entry carries a valid placement-rule kind; unique entries must state
    # the lock-in fact (no counterpart on the other backend)
    from scqo.fieldmap import VENDOR_ONLY_KINDS

    for name, v in fieldmap.VENDOR_ONLY.items():
        assert v.kind in VENDOR_ONLY_KINDS, name
        if v.kind == "unique":
            assert "no qm counterpart" in v.doc.lower(), name

    tree = ast.parse(Path(fieldmap.__file__).read_text(encoding="utf-8"))
    imported = {
        name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name in ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module])
    }
    assert imported <= {"__future__", "scqo.fieldmap"}, imported

    # the backend class serves exactly the declared catalog (methods are pure)
    from lchqb.backend.qblox_backend import QbloxBackend

    assert QbloxBackend.field_bindings(None) == fieldmap.FIELD_BINDINGS
    assert QbloxBackend.unrealized(None) == fieldmap.UNREALIZED
    assert QbloxBackend.vendor_only(None) == fieldmap.VENDOR_ONLY


def test_backend_entry_point_resolves(tmp_path):
    """The scqo.backends entry point loads and the factory fails loudly (no
    hardware needed) when the setup's folder lacks the canonical vendor files."""
    from importlib.metadata import entry_points

    import pytest

    eps = {ep.name: ep for ep in entry_points(group="scqo.backends")}
    assert "qblox" in eps, "reinstall the editable (uv pip install -e .) to register entry points"
    factory = eps["qblox"].load()

    empty = tmp_path / "empty"
    empty.mkdir()
    setup = {"backend": "qblox", "instrument_config": str(empty)}
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

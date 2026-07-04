"""Self-test the scqo stack against a REAL Qblox device config — no hardware needed.

    python scripts/check_real_config.py D:\\qpu_data\\SQ_demo\\QBLOX_config
    python scripts/check_real_config.py <config_dir> --qubits q1 q2

Loads your lab's dut/hw config (any ``dut_config*.json`` + ``hw_config*.json`` in the
given folder), then runs the full scqo pipeline with SIMULATED data over the REAL
device tree: read neutral fields -> run experiments -> fit -> write results back ->
save in vendor format -> reload and compare. Everything happens on a temporary copy;
your original files are never opened for writing.

Needs an environment with qblox_scheduler (lab: ``conda activate LCHQB``); scqo/scqat
are picked up from the sibling repos automatically if not installed.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # lchqb without pip install
try:
    import scqo  # noqa: F401
except ImportError:  # sibling-repo layout (D:/github)
    sys.path[:0] = [str(REPO.parent / "SCQO"), str(REPO.parent / "SCqubit-analysis-tool")]


def _pick(source: Path, pattern: str) -> Path:
    hits = [p for p in sorted(source.glob(pattern)) if "viewable" not in p.name]
    if not hits:
        raise SystemExit(f"no {pattern} found in {source}")
    return hits[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config_dir", help="folder holding dut_config*.json + hw_config*.json")
    parser.add_argument("--qubits", nargs="+", help="qubits to exercise (default: elements named q*)")
    args = parser.parse_args()

    source = Path(args.config_dir)
    work = Path(tempfile.mkdtemp(prefix="scqo_qblox_selftest_"))
    shutil.copy(_pick(source, "dut_config*.json"), work / "dut_config.json")
    shutil.copy(_pick(source, "hw_config*.json"), work / "hw_config.json")
    print(f"sandbox: {work}")
    print("  (temporary self-test copies + throwaway run data: your originals and your")
    print("   real data_root are NOT touched; real measurements use run_experiment.py)")

    try:
        import lchqb.elements  # noqa: F401  register the lab's custom element types
        from qblox_scheduler import QuantumDevice
    except ModuleNotFoundError as err:
        raise SystemExit(
            f"missing package: {err.name}\n"
            "This self-test needs the Qblox stack. Either install it into this environment:\n"
            "    uv pip install --python <your-venv-python> -e D:/github/LCHQBDriver\n"
            "or activate an environment that has it (lab: conda activate LCHQB)."
        )

    qd = QuantumDevice.from_json_file(str(work / "dut_config.json"))
    print(f"[1/5] loaded device '{qd.name}' | elements: {list(qd.elements)}")

    from lchqb.backend.qblox_backend import QbloxDeviceModel

    dm = QbloxDeviceModel(qd, config_file=str(work / "dut_config.json"))
    snap = dm.snapshot()
    for name, fields in snap.items():
        print(f"      {name}: {fields}")
    qubits = args.qubits or [n for n in snap if n.startswith("q")]
    print(f"[2/5] snapshot OK | testing qubits: {qubits}")

    import lchqb.experiments  # noqa: F401
    from scqo import Session
    from scqo.testing import SimulatedBackend

    sess = Session(SimulatedBackend(dm), data_root=work / "data", device_name="selftest", state_sync="push")
    before = {q: dict(v) for q, v in sess.device_state().items()}
    failures = []
    for experiment in ("resonator_spectroscopy", "qubit_power_rabi"):
        result = sess.run(experiment, {"qubits": qubits}, tags=["selftest"])
        ok = all(result["outcomes"].get(q) == "successful" for q in qubits) and not result.get("error")
        print(f"[3/5] {experiment}: {result['outcomes']}" + (f" error={result['error']}" if result.get("error") else ""))
        if not ok:
            failures.append(experiment)

    after = sess.device_state()
    moved = [q for q in qubits if after[q] != before[q]]
    print(f"[4/5] writeback reached the real device tree for: {moved or 'NONE'}")
    if set(moved) != set(qubits):
        failures.append("writeback")

    dm.save()
    reloaded = QuantumDevice.from_json_file(str(work / "dut_config.json"))
    dm2 = QbloxDeviceModel(reloaded)
    round_trip = all(
        abs(dm2.snapshot()[q]["readout_freq"] - after[q]["readout_freq"]) < 1e-3 for q in qubits
    )
    print(f"[5/5] vendor-format save/reload round-trip: {'OK' if round_trip else 'MISMATCH'}")
    if not round_trip:
        failures.append("save-roundtrip")

    print(f"\nruns saved + indexed under {work / 'data'}: "
          f"{[r['run_id'] for r in sess.find_runs(tag='selftest')]}")
    print("\nPASS - scqo works against this real config" if not failures
          else f"\nFAIL - problems in: {', '.join(failures)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())

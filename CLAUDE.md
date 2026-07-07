# LCHQBDriver — Qblox backend for the `scqo` experiment API

## What this repo is
The Qblox sibling of LCHQMDriver. It implements the **`scqo`** instrument-agnostic
experiment API (`D:\github\SCQO`) against the **Qblox** control stack
(`qblox_scheduler`: `Schedule`, `HardwareAgent`, `QuantumDevice`).

## Three design rules (do not break these)
1. **Independent of Quantum Machines.** Never import `qm`, `quam`, `quam_builder`,
   `qualibrate`, or `qualibration_libs`. The only shared code is `scqo`, which is
   itself vendor-free. (See `pyproject.toml` — no QM packages.)
2. **The common API lives in `scqo`, not here.** Parameters, Result, `estimate`,
   `simulate`, `update`, registry and `Session` come from `scqo`. This repo adds
   only the Qblox-specific halves: `probe()` per experiment and the backend/device adapter.
3. **Runs manually and via AI through the same `scqo.Session`.** `Session.catalog()` /
   `Session.run()` / `Session.device_state()` are plain JSON in/out.

## Layout
```
lchqb/
  backend/qblox_backend.py   # QbloxBackend (scqo.Backend) + QbloxDeviceModel/QbloxQubitView
                             #   wraps qblox_scheduler.HardwareAgent + QuantumDevice
  experiments/
    __init__.py              # imports each experiment module so @register runs (populates catalog)
    resonator_spectroscopy.py# QbloxResonatorSpectroscopy(ResonatorSpectroscopy): only probe()
    qubit_ramsey.py          # QbloxQubitRamsey(QubitRamsey): only probe()
    qubit_power_rabi.py      # QbloxQubitPowerRabi(QubitPowerRabi): only probe()
qblox_config/                # ~ quam_config: device-model + config generation (stubs)
qblox_state/                 # ~ quam_state: serialized dut_config.json / hw_config.json (generated)
lchqb/scqo_backend.py            # the `scqo.backends` entry-point factory: builds the
                                 #   qblox / qblox_sim Backend for the `scqo` CLI (vendor
                                 #   imports stay inside the branches)
scripts/                         # BACKWARD-COMPAT WRAPPERS (≤10 lines each) since scqo
                                 #   v0.4.0 — the engine lives in scqo/cli; students use
                                 #   the `scqo` command from any directory
  _lab.py / _cli.py              # import shims (build_session/default_qubits/engine re-exports)
  run_experiment.py etc.         # 8 command wrappers -> scqo.cli.<module>.main
  check_real_config.py           # PER-REPO: self-test vs a REAL dut/hw config (unchanged)
  run_resonator_spectroscopy.py  # PER-REPO: worked single-experiment example
  ai_loop_demo.py                # PER-REPO: the catalog -> decide -> run -> find loop
  experiments/                   # AUTO-GENERATED launchers (regenerate: `scqo sync-launchers`
    _sync.py                     #   or python scripts/experiments/_sync.py in this venv)
    <name>.py                    #   direct run; --help shows the parameter schema
```
Students use the **`scqo` command** and edit **nothing** here: backend choice, data_root,
device name and default tags come from `~/.scqo/config.toml` (+ personal `user.toml` /
`parameters.toml`; see `scqo.labconfig`). With no config everything runs simulated and
saves nothing.

## Adding an experiment
1. Subclass the backend-free experiment from `scqo.experiments.<name>`.
2. Implement only `probe()` using `qblox_scheduler` (import the vendor lib *inside* the
   method / backend so `import lchqb` stays light and the simulated path needs no Qblox).
3. `@register` the subclass and import the module in `lchqb/experiments/__init__.py`.
Everything else (parameters, fitting, writeback, simulation) is inherited from `scqo`.

## Reference
- Terminology (Experiment = probe + estimator; "protocol" retired): `D:\github\SCQO\CLAUDE.md` → **Terminology**.
- Shared API + patterns: `D:\github\SCQO\CLAUDE.md`.
- Qblox usage examples (read-only demo repo): `D:\github\QBLOX_training\docs\applications\superconducting`.
- QM sibling (do not import from it): `D:\github\LCHQMDriver`.

## Status
`resonator_spectroscopy`, `qubit_ramsey` and `qubit_power_rabi` run end-to-end on the simulated
backend. **2026-07-04 — verified against the lab's REAL dut config** (`AS_QRC`: q1, q2 + coupler
c12): `lchqb/elements.py` vendors the lab's `FluxTunableTransmonElement` (from QBLOX_training's
`custom_elements.py`; keep in sync) so `QuantumDevice.from_json_file` can deserialize it —
`QbloxBackend` registers it before loading. `QbloxQubitView` reads/writes both scheduler API
generations (legacy QCoDeS callables and the pydantic-model plain attributes), and `snapshot()`
tolerates non-transmon elements. Full scqo Session (simulated data over the real device tree:
read -> fit -> writeback -> vendor-format save) passes. Remaining for real hardware:
`QbloxBackend._to_canonical()` against the lab's acquisition output.

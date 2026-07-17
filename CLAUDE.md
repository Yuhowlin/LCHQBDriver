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
    <name>.py                # one module per core experiment (all 12): Qblox<Name>(<Name>) with
                             #   only probe() — e.g. resonator_spectroscopy, qubit_ramsey, ...
qblox_config/                # ~ quam_config: device-model + config generation (stubs)
qblox_state/                 # ~ quam_state: serialized dut_config.json / hw_config.json (generated)
lchqb/scqo_backend.py            # the `scqo.backends` entry-point factory
                                 #   build_backend(cfg, setup): loads the SELECTED named
                                 #   setup's vendor folder (setup["instrument_config"],
                                 #   DERIVED <cid>/<setup>/backend_config since scqo v0.9;
                                 #   canonical names dut_config.json + hw_config.json;
                                 #   loud SystemExit when missing); vendor imports stay lazy
scripts/                         # check_real_config.py + ai_loop_demo.py (a worked Session example)
```
Students use the **`scqo` command** and edit **nothing** here: select a setup
(`scqo user --device <name> [--setup <name>]`) and run. With no config everything runs
simulated and saves nothing. Setup/labconfig detail lives in `SCQO\INSTALL.md` §2.

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

## Hardware invariants
- `lchqb/elements.py` vendors the lab's `FluxTunableTransmonElement`; keep it in sync
  with upstream. `QbloxBackend` must register it BEFORE `QuantumDevice.from_json_file`,
  or the device tree won't deserialize.
- `QbloxQubitView` reads/writes BOTH scheduler API generations (legacy QCoDeS callables
  and the pydantic-model plain attributes).
- The agent's `hardware_configuration` dict is AUTHORITATIVE: every run recompiles from
  it and re-pushes attenuations, so a direct qcodes `.set()` is overwritten.
- `save()` writes BOTH config files (`dut_config.json` + `hw_config.json`); the dut's
  embedded `hardware_config` copy is synced first so they cannot diverge.
- `readout_power_dbm` ↔ `output_att`, which takes EVEN integers 0–60 dB.
- Two readout-power probes: `resonator_spectroscopy_power_chain` sweeps power with a
  Python loop (one 1D detuning scan per point); `resonator_spectroscopy_power_amp` is a
  single-program FPGA sweep over Python-UNROLLED geometric amplitude blocks, giving a
  uniform-dBm axis.

## Tests
`tests/test_scqo_glue.py` (scqo↔backend glue) and `tests/test_qblox_power.py`
(readout-power path).

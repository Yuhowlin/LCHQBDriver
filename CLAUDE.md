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
                                 #   setup's instrument_config folder (canonical names
                                 #   dut_config.json + hw_config.json; loud SystemExit
                                 #   when missing); vendor imports stay lazy
scripts/                         # PER-REPO content ONLY — the wrapper layer (command
                                 #   wrappers, _lab/_cli shims, auto-generated launcher
                                 #   stubs + `scqo sync-launchers`) was fully RETIRED in
                                 #   v0.7.0: `scqo run <name>` (etc.) is the one CLI.
                                 #   Never add wrappers or per-command stubs again.
  check_real_config.py           # self-test vs a REAL dut/hw config (unchanged)
  ai_loop_demo.py                # the catalog -> decide -> run -> find loop (imports scqo.cli;
                                 #   THE worked Session-API example — single-experiment runs
                                 #   are just `scqo run <name>`)
```
Students use the **`scqo` command** and edit **nothing** here: they select a sample
and setup with `scqo user --device <name> [--setup <name>]` (written to their
`~/.scqo/user.toml`; data_root comes from the shared config). Which instrument
carries the sample — plus where its `dut_config.json`/`hw_config.json` folder lives —
is a NAMED setup of the device's ACTIVE cooldown cycle (`[<cycle>.setup.<name>]`;
scqo v0.7.0, see `scqo.labconfig`/`SCQO\INSTALL.md` §2; a single-setup cycle
auto-selects). With no config everything runs simulated and saves nothing. The
`qblox_sim` twin mode was retired with v0.5.0 (`simulated` is the practice mode).

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
read -> fit -> writeback -> vendor-format save) passes.

**2026-07-05 — hardware-proven:** real measurements run on the lab cluster through the scqo
path (`_to_canonical` handles the lab's acquisition output, incl. N-D sweeps and per-shot
contracts); the driver now covers all 12 core experiments. **2026-07-08 — scqo v0.5.0:**
the entry-point factory is `build_backend(cfg, setup)` — it loads `dut_config.json` +
`hw_config.json` from the setup's `instrument_config` folder (loud SystemExit when
missing); the `qblox_sim` twin mode is retired. **2026-07-12 — scqo v0.7.0 (named
setups):** the setup passed to the factory is the user-SELECTED `[<cycle>.setup.<name>]`
record (keys: backend/instrument_config/note; `since` dates + port maps retired); runs
stamp `(cooldown, setup-name)`. The scripts/ WRAPPER LAYER is fully RETIRED (user
decision — no users yet, so no compat burden): ALL command wrappers, the
`_lab`/`_cli` import shims, the auto-generated `scripts/experiments/` launcher
stubs and scqo's `sync-launchers` subcommand are deleted; `scqo run <name>` (and
`scqo state`/`scqo device`/`scqo user`/...) is the one CLI. scripts/ keeps only
check_real_config.py + ai_loop_demo.py (now `from scqo.cli import build_session`;
run_resonator_spectroscopy.py deleted too — redundant with `scqo run`);
tests/test_wrappers.py became tests/test_scqo_glue.py. Never add
wrappers or per-command stubs again.

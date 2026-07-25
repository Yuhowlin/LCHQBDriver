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
  backend/qblox_backend.py   # QbloxBackend (scqo.Backend) + QbloxDeviceModel + ONE view class
                             #   per CHANNEL KIND: QbloxDriveChannel / QbloxReadoutChannel /
                             #   QbloxFluxChannel (subclass scqo.device.make_view_base("drive"|
                             #   "readout"|"flux")); all three resolve onto the SAME
                             #   qblox_scheduler DeviceElement (the channel's single target)
                             #   wraps qblox_scheduler.HardwareAgent + QuantumDevice
  experiments/
    __init__.py              # imports each experiment module so @register runs (populates catalog)
    _vendor.py               # the probes' one door out of the neutral surface: the raw
                             #   DeviceElement behind a target's default channel (ports,
                             #   flux sweet spot), addressed through the ROSTER
    <name>.py                # one module per core experiment (all 12): Qblox<Name>(<Name>) with
                             #   only probe() — e.g. resonator_spectroscopy, qubit_ramsey, ...
qblox_config/                # ~ quam_config: device-model + config generation (stubs)
qblox_state/                 # ~ quam_state: serialized dut_config.json / hw_config.json (generated)
lchqb/scqo_backend.py            # the `scqo.backends` entry-point factory
                                 #   build_backend(cfg, setup, roster): loads the SELECTED
                                 #   named setup's vendor folder (setup["instrument_config"],
                                 #   DERIVED <cid>/<setup>/backend_config since scqo v0.9;
                                 #   canonical names dut_config.json + hw_config.json;
                                 #   loud SystemExit when missing) and threads the device
                                 #   ROSTER into the backend (entity-name resolution needs
                                 #   it); vendor imports stay lazy
scripts/                         # check_real_config.py + ai_loop_demo.py (a worked Session example)
```
Students use the **`scqo` command** and edit **nothing** here: select a setup
(`scqo user --device <name> [--setup <name>]`) and run. With no config everything runs
simulated and saves nothing. Setup/labconfig detail lives in `SCQO\INSTALL.md` §2.

## Adding an experiment
1. Subclass the backend-free experiment from `scqo.experiments.<name>`.
2. Implement only `probe()` using `qblox_scheduler` (import the vendor lib *inside* the
   method / backend so `import lchqb` stays light and the simulated path needs no Qblox).
   Read device state through the CHANNEL that owns the knob —
   `self.device.channel(target, "readout").readout_freq_hz`, `...("drive").pi_amp` —
   never `backend.device.component(<qubit>)`; vendor-only bits (ports, the flux sweet
   spot) come from `_vendor.vendor_element(self, target, kind)`.
3. `@register` the subclass and import the module in `lchqb/experiments/__init__.py`.
Everything else (parameters, fitting, writeback, simulation) is inherited from `scqo`.

## Reference
- Terminology (Experiment = probe + estimator; "protocol" retired): `D:\github\SCQO\CLAUDE.md` → **Terminology**.
- Shared API + patterns: `D:\github\SCQO\CLAUDE.md`.
- Qblox usage examples (read-only demo repo): `D:\github\QBLOX_training\docs\applications\superconducting`.
- QM sibling (do not import from it): `D:\github\LCHQMDriver`.

## Hardware invariants
- `lchqb/elements.py` vendors the lab's element types and deliberately EXTENDS the
  QBLOX_training copy: `LCHTransmonElement` adds the `spec` submodule (`spec_amp`,
  the saturation-drive slot behind `drive_amp`/`drive_power_dbm`);
  `FluxTunableTransmonElement` subclasses it. `QbloxBackend` must register them
  BEFORE `QuantumDevice.from_json_file`, or the device tree won't deserialize.
  A dut config missing the `spec` block still loads (spec_amp defaults NaN =
  field unknown until seeded).
- The channel views read/write BOTH scheduler API generations (legacy QCoDeS
  callables and the pydantic-model plain attributes).
- `QbloxDeviceModel.component()` takes a ROSTER ENTITY name (`q1_ro`, `q1_xy`,
  `q1_z`) and resolves it through the roster (kind -> view class, single target ->
  vendor element). Everything the vendor does not realize — modes, lines,
  composites, pump/multi-target channels, a target with no element — is a KeyError.
  A view's `.name` is the ENTITY name; `_element.name` is the vendor element.
- The agent's `hardware_configuration` dict is AUTHORITATIVE: every run recompiles from
  it and re-pushes attenuations, so a direct qcodes `.set()` is overwritten.
- `save()` writes BOTH config files (`dut_config.json` + `hw_config.json`); the dut's
  embedded `hardware_config` copy is synced first so they cannot diverge.
- `readout_power_dbm` ↔ readout `output_att` + `measure.pulse_amp`;
  `drive_power_dbm` ↔ drive-port `output_att` + `element.spec.spec_amp`
  (`output_att` takes EVEN integers 0–60 dB; both solves keep the amplitude
  ≤ 0.5, the amplitude carries the exact residual).
- `readout_duration_s` ↔ `measure.pulse_duration`, `readout_integration_s` ↔
  `measure.integration_time`: both positive multiples of 4 ns (REFUSED otherwise),
  window ≤ pulse (QM-portability contract — the hardware here would allow more),
  and a pulse shrink clamps the window down with it.
- Readout/drive LO = `hw_config.json` `hardware_options.modulation_frequencies`
  (PORT-level, shared by every element on the output; untracked wiring). Hand-edit
  only while NO session is live — `save()` rewrites the file from the in-memory
  config and would silently revert the edit — and restart notebook kernels after.
  `power_context` stamps the readout LO into every run record.
- Placement rule (which store owns which value): `scqo state --rule` / SCQO TUTORIAL §10.
  A vendor copy of a neutral/physical value is legal only as a CACHE with a named
  refresh trigger — the SCQO stores are truth.
- Two readout-power probes: `resonator_spectroscopy_power_chain` sweeps power with a
  Python loop (one 1D detuning scan per point); `resonator_spectroscopy_power_amp` is a
  single-program FPGA sweep over Python-UNROLLED geometric amplitude blocks, giving a
  uniform-dBm axis.

## Tests
`tests/conftest.py` holds the shared fixture chip — a schema-3 roster for the demo
dut config (`ROSTER_TOML`: q1/q2 + coupler c12, one multiplexed feedline, a drive and
a flux wire each) plus `make_backend` / `make_experiment` (the latter attaches the
`RecordingDevice` a Session would). `tests/test_scqo_glue.py` (scqo↔backend glue, the
per-kind fieldmap drift alarm, the `components()` witness), `tests/test_qblox_power.py`
(the readout AND drive absolute-power paths), `tests/test_probe_surface.py` (EVERY
registered probe builds its Schedule against the channel-entity surface).

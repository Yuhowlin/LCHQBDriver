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
- `readout_rotation_rad` ↔ `measure.acq_rotation` (**radians ↔ DEGREES**, converted
  in the view — QM's `integration_weights_angle` is radians, and one `scqo set` must
  mean the same rotation on both backends) and **FOLDED**: the sequencer takes
  degrees in [0, 360] and refuses anything outside, while the neutral field keeps
  (−π, π], so both directions wrap; `readout_threshold` ↔ `measure.acq_threshold`,
  unconverted (same normalized frame the probes acquire in) and unfolded (its
  limits are ±1.7e7, which a real threshold never approaches).
  These two arm `use_state_discrimination` on the four coherent-drive probes:
  `experiments/_state.py` asks for `acq_protocol="ThresholdedAcquisition"` and the
  compiler reads the numbers off the element. Vendor default `0.0` = UNCALIBRATED and
  the probes refuse it by name. `readout_rus_threshold` stays Unrealized (QM-only).
  Calibrated by `single_shot_readout`, whose Qblox `update()` proposes both.
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
registered probe COMPILES its Schedule against the channel-entity surface — building
one proves nothing, since the time grid, the DAC range and the latched-parameter
alignment all live in the compiler; `conftest.compile_probe` is the shared door).

**One vendor version, both venvs.** `uv run pytest` uses `.venv`; `scqo run` on the
cluster uses `D:\github\.venv-qblox`. They must hold the same `qblox-scheduler` — on
2026-07-26 they did not (b4 vs b6) and the two versions *disagreed about whether a
schedule is legal*: `readout_frequency` compiled clean offline and died on hardware.
Both are now 1.0.0b6 + qblox_instruments 1.3.0. After changing either, run the suite
in the lab venv too:
`D:\github\.venv-qblox\Scripts\python.exe -m pytest tests/ -q`.

### Testing discipline — here, just run the whole thing
`uv run pytest tests/ -q` — **88 tests, ~31 s** (plain `uv run` is correct: `scqo` is a hard
dependency in `pyproject.toml`, so uv's sync keeps it). At this size a selection map would cost
more attention than it saves; unlike SCQO (476 tests, ~7 min) and scqat (296 / ~53 s), the full
suite IS the targeted run. Run it before every commit.

The one narrowing worth knowing: **`test_scqo_glue.py` is ~14 s of the 31 s** — it shells out to
the real `scqo` CLI and runs the AI-loop demo end-to-end. While iterating on a probe, loop on
`uv run pytest tests/test_probe_surface.py tests/test_time_grid.py -q` (30 tests, ~10 s measured —
per-test time is milliseconds, the cost is fixture + qblox_scheduler import) and pick the glue test
back up before you commit. Below ~10 s there is nothing left to win here; don't over-narrow.

| File | Covers |
|---|---|
| `test_probe_surface.py` | every registered probe **compiles** its Schedule on the channel-entity surface |
| `test_time_grid.py` | the specific swept WINDOWS whose naive linspace step was fractional |
| `test_state_discrimination.py` | `use_state_discrimination`: the two knobs, the thresholded probes, the `state` decode, the single_shot_readout proposal |
| `test_qblox_power.py` | output-att solves, the hardware-config write surface, dual-file save, `power_context` |
| `test_qblox_reset.py` | `thermalization_time_s` as a neutral drive-channel knob |
| `test_readout_duration.py` | duration/window knobs on the readout view (pure stubs, no qblox_scheduler) |
| `test_hw_config_serialization.py` | explicit nulls never written or trusted |
| `test_scqo_glue.py` | the `scqo` CLI works in THIS venv + the qblox factory (slow — see above) |

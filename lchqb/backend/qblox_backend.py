"""Qblox backend: maps the scqo abstractions onto qblox_scheduler.

``qblox_scheduler`` is imported lazily (inside methods) so that ``import lchqb`` works
without the Qblox stack installed, and so the simulated path never needs it.

Neutral-name mapping: declared ONCE in ``lchqb/backend/fieldmap.py`` (the catalog
``scqo state --fields`` renders; drift-tested per category against scqo's pushed
fields). The executable conversions are ``QbloxReadableTransmon``'s properties below.
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import xarray as xr
from scqo.backend import Backend
from scqo.device import ComponentInfo, DeviceModel, make_view_base
from scqo.fieldmap import Unrealized, VendorBinding, VendorOnly

from lchqb.backend.fieldmap import FIELD_BINDINGS, UNREALIZED, VENDOR_ONLY

if TYPE_CHECKING:
    from scqo.experiment import Experiment

#: Nominal QRM-RF full-scale output (dBm) at pulse_amp=1.0, output_att=0 — the
#: datasheet maximum (+5 dBm into 50 Ohm). Frequency/LO/mixer-dependent in reality,
#: so absolute powers derived from it are good to ±a few dB; a per-setup
#: photon-number anchor (AC-Stark) is the Phase-3 refinement.
QBLOX_NOMINAL_FULL_SCALE_DBM = 5.0
#: The canonical digital operating point: keep the pulse amplitude <= 0.5 full
#: scale (shared by the readout AND drive chain solves).
_CANONICAL_MAX_AMP = 0.5


def _solve_att(name: str, target: float, what: str) -> tuple[int, float]:
    """Solve an output chain for an absolute port power: the largest EVEN
    attenuation in [0, 60] keeping the amplitude <= 0.5 (the module validator is
    Multiples(2), 0..60 — an odd value would only fail later, at instrument
    prepare); the amplitude absorbs the exact residual."""
    if target > QBLOX_NOMINAL_FULL_SCALE_DBM:
        raise ValueError(
            f"{name}: target {target} dBm exceeds the chain maximum "
            f"(+{QBLOX_NOMINAL_FULL_SCALE_DBM} dBm at amplitude 1, output_att=0)"
        )
    att_max = QBLOX_NOMINAL_FULL_SCALE_DBM - target + 20.0 * math.log10(_CANONICAL_MAX_AMP)
    att = int(min(60, max(0, 2 * math.floor(att_max / 2.0))))
    amp = 10.0 ** ((target - QBLOX_NOMINAL_FULL_SCALE_DBM + att) / 20.0)
    if amp > _CANONICAL_MAX_AMP:  # only when att=0 cannot absorb it (target > ~-1 dBm)
        warnings.warn(
            f"{name}: hitting {target} dBm needs {what}={amp:.3f} > "
            f"{_CANONICAL_MAX_AMP} (output_att already 0) — above the canonical "
            f"operating point"
        )
    return att, amp


def _read(owner: Any, name: str) -> float:
    """Read a scheduler parameter across API generations: the legacy QCoDeS style
    exposes a callable (``param()``), the pydantic-model style a plain attribute."""
    attr = getattr(owner, name)
    return float(attr() if callable(attr) else attr)


def _write(owner: Any, name: str, value: float) -> None:
    attr = getattr(owner, name)
    if callable(attr):
        attr(float(value))
    else:
        setattr(owner, name, float(value))


def _grid_s(value: float, what: str) -> float:
    """Validate a seconds duration as a positive multiple of 4 ns and return it
    re-derived from the integer grid (so both backends store the identical
    canonical float). 4 ns is the PORTABLE neutral contract — QM's
    pulse/integration-weights resolution; the scheduler itself is finer, but an
    off-grid value here would be unrealizable on the QM backend."""
    ns = float(value) * 1e9
    grid = round(ns)
    if abs(ns - grid) > 1e-3 or grid <= 0 or grid % 4:
        raise ValueError(
            f"{what}={value!r} s: must be a positive multiple of 4 ns (the "
            f"portable pulse/weights grid; no silent rounding)")
    # / 1e9 (exact), never * 1e-9: division rounds correctly, so the stored float
    # equals the parsed literal (2000 -> exactly 2e-6) on BOTH backends.
    return grid / 1e9


class QbloxReadableTransmon(make_view_base("ReadableTransmon")):
    """The scqo ReadableTransmon view backed by a qblox_scheduler ``DeviceElement``.

    ``hw_agent`` (the backend's HardwareAgent) is needed only by
    ``readout_power_dbm``: the readout attenuation lives in the hardware
    compilation config, one level above the element. Its
    ``hardware_configuration`` dict is the AUTHORITATIVE runtime surface — every
    ``run()`` recompiles from it and re-pushes ``out<n>_att`` to the module, so
    writes there survive; a direct qcodes ``.set()`` would be overwritten.
    """

    def __init__(self, element: Any, hw_agent: Any = None) -> None:
        self.name = element.name
        self._element = element
        self._hw_agent = hw_agent

    @property
    def readout_freq(self) -> float:
        return _read(self._element.clock_freqs, "readout")

    @readout_freq.setter
    def readout_freq(self, value: float) -> None:
        _write(self._element.clock_freqs, "readout", value)

    @property
    def drive_freq(self) -> float:
        return _read(self._element.clock_freqs, "f01")

    @drive_freq.setter
    def drive_freq(self, value: float) -> None:
        _write(self._element.clock_freqs, "f01", value)

    @property
    def pi_amp(self) -> float:
        return _read(self._element.rxy, "amp180")

    @pi_amp.setter
    def pi_amp(self, value: float) -> None:
        _write(self._element.rxy, "amp180", value)

    @property
    def readout_amp(self) -> float:
        return _read(self._element.measure, "pulse_amp")

    @readout_amp.setter
    def readout_amp(self, value: float) -> None:
        _write(self._element.measure, "pulse_amp", value)

    # ------------------------------------------- readout duration / window
    @property
    def readout_duration_s(self) -> float:
        return _read(self._element.measure, "pulse_duration")

    @readout_duration_s.setter
    def readout_duration_s(self, value: float) -> None:
        new_s = _grid_s(value, "readout_duration_s")
        _write(self._element.measure, "pulse_duration", new_s)
        # Portable contract (QM parity — its weights cannot span past the pulse):
        # the window never outlives the pulse, so a shrink clamps it down; the
        # scqo layer re-reads it and records the echo as a COUPLED change.
        if _read(self._element.measure, "integration_time") > new_s:
            _write(self._element.measure, "integration_time", new_s)

    @property
    def readout_integration_s(self) -> float:
        return _read(self._element.measure, "integration_time")

    @readout_integration_s.setter
    def readout_integration_s(self, value: float) -> None:
        new_s = _grid_s(value, "readout_integration_s")
        duration = _read(self._element.measure, "pulse_duration")
        if new_s > duration + 1e-12:
            raise ValueError(
                f"{self.name}: readout_integration_s={value!r} s exceeds the "
                f"readout pulse ({duration} s). The hardware here would allow "
                f"it, but QM cannot integrate past the pulse, so the portable "
                f"contract is window <= duration - raise readout_duration_s "
                f"first (or set both in one command; the pulse pushes first)")
        _write(self._element.measure, "integration_time", new_s)

    # ------------------------------------------------------------ absolute power
    def _port_clock(self) -> str:
        """The hardware-options key of this element's readout line, e.g. 'q1:res-q1.ro'."""
        port = getattr(self._element.ports, "readout")
        port = port() if callable(port) else port
        return f"{port}-{self.name}.ro"

    def _drive_port_clock(self) -> str:
        """The hardware-options key of this element's drive line, e.g. 'q1:mw-q1.01'."""
        port = getattr(self._element.ports, "microwave")
        port = port() if callable(port) else port
        return f"{port}-{self.name}.01"

    def _output_att(self, port_clock: str | None = None) -> int:
        """Current output attenuation (dB) of a line from the hardware config
        (default: the readout line; missing key -> 0 dB, the instrument default)."""
        if self._hw_agent is None:
            raise RuntimeError(
                f"{self.name}: no HardwareAgent attached — output_att (and so the "
                f"absolute powers) needs the hardware compilation config"
            )
        opts = self._hw_agent.hardware_configuration.hardware_options
        att_map = getattr(opts, "output_att", None) or {}
        return int(att_map.get(port_clock or self._port_clock(), 0))

    def _write_output_att(self, port_clock: str, att: int) -> None:
        if self._hw_agent is None:
            raise RuntimeError(
                f"{self.name}: no HardwareAgent attached — cannot write output_att"
            )
        opts = self._hw_agent.hardware_configuration.hardware_options
        if opts.output_att is None:
            opts.output_att = {}
        opts.output_att[port_clock] = att  # authoritative: recompiled+pushed each run

    @property
    def readout_power_dbm(self) -> float:
        amp = _read(self._element.measure, "pulse_amp")
        if amp <= 0:  # log10 domain — the absolute power is undefined, not zero
            raise ValueError(
                f"{self.name}: readout pulse_amp is {amp} — absolute power undefined"
            )
        return QBLOX_NOMINAL_FULL_SCALE_DBM - self._output_att() + 20.0 * math.log10(amp)

    @readout_power_dbm.setter
    def readout_power_dbm(self, value: float) -> None:
        att, amp = _solve_att(self.name, float(value), "pulse_amp")
        self._write_output_att(self._port_clock(), att)
        _write(self._element.measure, "pulse_amp", amp)

    # The drive twin, anchored to the stored SATURATION (spec) amplitude
    # (element.spec.spec_amp — the CW VoltageOffset the qubit_spectroscopy probe
    # plays). The drive output_att is PORT-level and shared by every xy pulse:
    # while it is off its standing value the stored pi_amp means a different
    # power (qubit_spectroscopy's run() sets and exactly reverts it; the even
    # discrete att + verbatim amplitude restore make the revert lossless).
    @property
    def drive_amp(self) -> float:
        amp = _read(self._element.spec, "spec_amp")
        if math.isnan(amp):
            raise ValueError(
                f"{self.name}: spec_amp is unset (NaN) — seed it (or set "
                f"drive_power_dbm, which writes it as the chain residual)"
            )
        return amp

    @drive_amp.setter
    def drive_amp(self, value: float) -> None:
        _write(self._element.spec, "spec_amp", value)

    @property
    def drive_power_dbm(self) -> float:
        amp = _read(self._element.spec, "spec_amp")
        # NaN would silently propagate through log10 into the config — refuse it
        # exactly like a zero/negative amplitude (power undefined, not a number).
        if not (amp > 0) or not math.isfinite(amp):
            raise ValueError(
                f"{self.name}: spec_amp is {amp} — absolute drive power undefined"
            )
        return (QBLOX_NOMINAL_FULL_SCALE_DBM - self._output_att(self._drive_port_clock())
                + 20.0 * math.log10(amp))

    @drive_power_dbm.setter
    def drive_power_dbm(self, value: float) -> None:
        att, amp = _solve_att(self.name, float(value), "spec_amp")
        self._write_output_att(self._drive_port_clock(), att)
        _write(self._element.spec, "spec_amp", amp)

    # ------------------------------------------------------- unrealized fields
    # idle_flux_v is declared Unrealized in lchqb.backend.fieldmap.UNREALIZED —
    # make_view_base declares the abstract pair (the category schema), so a
    # concrete raising implementation is required for the class to instantiate.
    _IDLE_FLUX_V_UNREALIZED = (
        "idle_flux_v is Unrealized on the Qblox backend: no flux-tunable device "
        "yet; the setter lands with the first flux chip"
    )

    @property
    def idle_flux_v(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._IDLE_FLUX_V_UNREALIZED}")

    @idle_flux_v.setter
    def idle_flux_v(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._IDLE_FLUX_V_UNREALIZED}")

    # drag_beta is Unrealized on Qblox (fieldmap.UNREALIZED): rxy.beta exists but
    # no scqo experiment calibrates it here yet. Concrete raising pair required
    # because make_view_base declares the abstract property for every pushed field.
    _DRAG_BETA_UNREALIZED = (
        "drag_beta is Unrealized on the Qblox backend: no DRAG calibration wired "
        "here yet (the drag experiments are QM-only)"
    )

    @property
    def drag_beta(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._DRAG_BETA_UNREALIZED}")

    @drag_beta.setter
    def drag_beta(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._DRAG_BETA_UNREALIZED}")


def _read_or_none(view: QbloxReadableTransmon, field: str) -> float | None:
    """Read a neutral field, returning None if this element doesn't carry it.

    ValueError covers readout_power_dbm on a zero/unset pulse_amp; RuntimeError
    covers a device model constructed without a HardwareAgent (no hardware config
    to read the attenuation from)."""
    try:
        return getattr(view, field)
    except (TypeError, AttributeError, KeyError, ValueError, RuntimeError):
        return None


class QbloxDeviceModel(DeviceModel):
    """Wraps a qblox_scheduler ``QuantumDevice`` (+ optionally its HardwareAgent).

    The agent reference (and its hardware config file path) enables the
    ``readout_power_dbm`` surface — the readout attenuation lives in the hardware
    compilation config, not on the element. Constructing without an agent keeps
    the legacy (element-only) behavior working.
    """

    def __init__(self, quantum_device: Any, config_file: str | None = None,
                 hw_agent: Any = None, hw_config_file: str | None = None) -> None:
        self._qd = quantum_device
        self._config_file = config_file
        self._hw_agent = hw_agent
        self._hw_config_file = hw_config_file

    def component(self, name: str) -> QbloxReadableTransmon:
        return QbloxReadableTransmon(self._qd.get_element(name), hw_agent=self._hw_agent)

    def components(self) -> dict[str, ComponentInfo]:
        # Derived inventory (the doctor's WITNESS, never truth): element_type
        # cannot distinguish couplers, the roster arbitrates. Edges exist in the
        # dut config but pairs are Phase 2 — ignored here.
        return {name: ComponentInfo("ReadableTransmon", operations=("rx", "readout"))
                for name in self._qd.elements}

    def save(self) -> None:
        # Write back to the EXACT files the device was loaded from. (to_json_file
        # writes <device_name>.json, which silently diverges from the dut_config.json
        # the backend loads — calibrations would be stale after a restart.)
        hw = self._hw_agent.hardware_configuration if self._hw_agent is not None else None
        if hw is not None:
            # The separate hw_config.json is the RUNTIME truth (connect_clusters
            # overwrites qd.hardware_config from it on every run); keep the copy
            # embedded in dut_config.json in step BEFORE serializing the quantum
            # device, so the two files can never drift through a save.
            self._qd.hardware_config = hw
            if self._hw_config_file is not None:
                with open(self._hw_config_file, "w", encoding="utf-8") as f:
                    # exclude_none is LOAD-BEARING: pydantic's default dump writes
                    # every unset Optional as an explicit null, and the qblox
                    # compiler treats an explicitly-null channel description as
                    # "user set None" (it lands in model_fields_set on reload) and
                    # crashes sequencer compilation — whereas an ABSENT key gets a
                    # default ChannelDescription. Never write nulls.
                    f.write(hw.model_dump_json(indent=2, exclude_none=True))
        if self._config_file is not None:
            with open(self._config_file, "w", encoding="utf-8") as f:
                f.write(self._qd.to_json())
            if hw is not None:
                # to_json has no exclude_none switch, so it re-embeds the hardware
                # config WITH explicit nulls (the crash trigger above). Rewrite that
                # one block from the SAME clean dump hw_config.json got — the two
                # files then carry identical config content and no nulls survive.
                import json as _json

                data = _json.loads(Path(self._config_file).read_text(encoding="utf-8"))
                if "hardware_config" in data:
                    data["hardware_config"] = _json.loads(hw.model_dump_json(exclude_none=True))
                    Path(self._config_file).write_text(_json.dumps(data, indent=4),
                                                       encoding="utf-8")

    def snapshot(self) -> dict:
        # Tolerate non-transmon elements (couplers etc.): report None for a field the
        # element doesn't carry rather than crashing on a real lab device tree.
        state: dict[str, dict] = {}
        for name in self._qd.elements:
            view = self.component(name)
            state[name] = {
                field: _read_or_none(view, field)
                for field in ("readout_freq", "drive_freq", "pi_amp",
                              "drive_amp", "drive_power_dbm", "readout_amp",
                              "readout_power_dbm", "readout_duration_s",
                              "readout_integration_s")
            }
        return state


class QbloxBackend(Backend):
    """scqo Backend over a Qblox cluster (or dummy connections for dry runs)."""

    def __init__(self, hardware_config: str, device_config: str, output_dir: str | None = None) -> None:
        # Lazy import keeps `import lchqb` free of qblox_scheduler. The elements import
        # registers the lab's custom element types (FluxTunableTransmonElement) so the
        # dut config can be deserialized.
        import lchqb.elements  # noqa: F401
        from qblox_scheduler import HardwareAgent

        self._hw_agent = HardwareAgent(
            hardware_configuration=hardware_config,
            quantum_device_configuration=device_config,
            output_dir=output_dir,
        )
        # HardwareAgent parses a config PATH into a plain dict; the validated model
        # only appears once connect_clusters runs. Validate it NOW (the very call
        # connect_clusters makes) so the hardware config is readable/writable with
        # no cluster attached — readout_power_dbm and save() need it. A later
        # connect_clusters re-validates the same object harmlessly.
        import json as _json

        from qblox_scheduler.backends.qblox_backend import QbloxHardwareCompilationConfig

        validated = QbloxHardwareCompilationConfig.model_validate(
            self._hw_agent._hardware_configuration
        )
        # NORMALIZE through an exclude_none round-trip: a file carrying explicit
        # nulls (e.g. one written by a pre-fix save(), or the QBLOX_training
        # placeholder dumps) marks those fields as SET-to-None, and the compiler's
        # channel-description lookup then passes None into the sequencer config and
        # crashes. Dropping the nulls here takes them OUT of model_fields_set, so
        # poisoned configs load, compile, and self-heal on the next save().
        self._hw_agent._hardware_configuration = QbloxHardwareCompilationConfig.model_validate(
            _json.loads(validated.model_dump_json(exclude_none=True))
        )
        self._device = QbloxDeviceModel(
            self._hw_agent.quantum_device,
            config_file=device_config,
            hw_agent=self._hw_agent,
            hw_config_file=hardware_config,
        )

    @classmethod
    def load(cls, config_dir: str = "./qblox_state", output_dir: str | None = None) -> "QbloxBackend":
        """Construct from the repo's standard config locations."""
        return cls(
            hardware_config=f"{config_dir}/hw_config.json",
            device_config=f"{config_dir}/dut_config.json",
            output_dir=output_dir,
        )

    @property
    def device(self) -> QbloxDeviceModel:
        return self._device

    def field_bindings(self) -> dict[str, dict[str, VendorBinding]]:
        """The declared per-category neutral-field catalog (lchqb.backend.fieldmap)
        — the conversion CODE is QbloxReadableTransmon above; this is its description."""
        return {category: dict(bindings) for category, bindings in FIELD_BINDINGS.items()}

    def unrealized(self) -> dict[str, dict[str, Unrealized]]:
        """Pushed fields this backend cannot realize, per category (see fieldmap)."""
        return {category: dict(entries) for category, entries in UNREALIZED.items()}

    def vendor_only(self) -> dict[str, VendorOnly]:
        """Qblox-unique calibration knobs, vendor-owned (see fieldmap)."""
        return dict(VENDOR_ONLY)

    def power_context(self, qubits: list[str]) -> dict:
        """Raw readout + drive chain values per qubit (run-record provenance only)."""
        out: dict = {}
        for name in qubits:
            try:
                view = self._device.component(name)
                out[name] = {
                    "output_att_db": view._output_att(),
                    "pulse_amp": _read(view._element.measure, "pulse_amp"),
                    "nominal_full_scale_dbm": QBLOX_NOMINAL_FULL_SCALE_DBM,
                    "readout_power_dbm": view.readout_power_dbm,
                    "note": "power derived from the nominal +5 dBm full scale "
                            "(frequency-dependent, ±a few dB)",
                }
                # The readout LO the data was taken at: a hand-edited lo_freq is
                # otherwise invisible in provenance (readout_freq alone cannot
                # explain a jump across the IF window). Only when configured — a
                # missing entry must not degrade the rest of the context.
                opts = self._hw_agent.hardware_configuration.hardware_options
                mf = getattr(opts, "modulation_frequencies", None) or {}
                lo = getattr(mf.get(view._port_clock()), "lo_freq", None)
                if lo is not None:
                    out[name]["readout_lo_freq_hz"] = float(lo)
            except Exception:  # provenance must never fail a run
                out[name] = {}
            # The drive chain behind drive_power_dbm — same never-fail rule, and
            # independent of the readout block (an element without a spec slot
            # still reports its readout chain).
            try:
                view = self._device.component(name)
                out[name].update({
                    "drive_output_att_db": view._output_att(view._drive_port_clock()),
                    "spec_amp": _read(view._element.spec, "spec_amp"),
                    "drive_power_dbm": view.drive_power_dbm,
                })
                opts = self._hw_agent.hardware_configuration.hardware_options
                mf = getattr(opts, "modulation_frequencies", None) or {}
                lo = getattr(mf.get(view._drive_port_clock()), "lo_freq", None)
                if lo is not None:
                    out[name]["drive_lo_freq_hz"] = float(lo)
            except Exception:  # provenance must never fail a run
                pass
        return out

    def acquire(self, experiment: "Experiment") -> xr.Dataset:
        schedule = experiment.probe()  # native qblox_scheduler.Schedule
        raw = self._hw_agent.run(schedule, timeout=120)
        return self._to_canonical(raw, experiment)

    @staticmethod
    def _to_canonical(raw: xr.Dataset, experiment: "Experiment") -> xr.Dataset:
        """Relabel a raw Qblox dataset into scqo's convention: dims (target, <sweep>), vars I/Q.

        The probes label every acquisition ``acq_channel=f"S_21_{qubit}"`` with the
        sweep loop variable as a per-point coordinate (cal02 reference pattern), so
        the hardware returns one complex S21 array per qubit over the swept axis
        (repetitions averaged on the cluster). The canonical sweep values come from
        ``experiment.sweep_axes`` — the probe built its loop from exactly those.
        On a structure mismatch the raw dataset is pickled for offline inspection.
        """
        import numpy as np

        qubits = list(experiment.params.targets)  # type: ignore[attr-defined]
        axes = {name: np.asarray(values) for name, values in experiment.sweep_axes.items()}
        shape = tuple(len(v) for v in axes.values())
        try:
            i_rows, q_rows = [], []
            for name in qubits:
                key = f"S_21_{name}"
                if key not in raw.data_vars:
                    raise KeyError(
                        f"acquisition channel {key!r} not in raw dataset "
                        f"(data_vars={list(raw.data_vars)}) — probe/hardware mismatch"
                    )
                values = np.asarray(raw[key].values).squeeze()
                if values.shape != shape:
                    if values.ndim == len(shape) and values.shape == tuple(reversed(shape)):
                        values = values.T  # labeled axes returned in reversed order
                    elif values.size == int(np.prod(shape)):
                        # flat bin order follows the probe's loop nesting (outer axis
                        # first), which matches sweep_axes insertion order
                        values = values.reshape(shape)
                    else:
                        raise ValueError(
                            f"{key}: expected shape {shape} for axes {list(axes)}, "
                            f"got {values.shape} (dims={dict(raw.sizes)})"
                        )
                i_rows.append(values.real)
                q_rows.append(values.imag)
        except (KeyError, ValueError) as err:
            raise type(err)(f"{err}; {_dump_raw(raw)}") from err
        dims = ("target", *axes.keys())
        return xr.Dataset(
            {"I": (dims, np.stack(i_rows)), "Q": (dims, np.stack(q_rows))},
            coords={"target": qubits, **axes},
        )


def _dump_raw(raw: xr.Dataset) -> str:
    """Pickle the raw hardware dataset for offline inspection (netCDF can't hold the
    complex S21 data); a failed bring-up run is never wasted."""
    import pickle
    import tempfile
    from datetime import datetime
    from pathlib import Path

    dump = Path(tempfile.gettempdir()) / f"qblox_raw_{datetime.now():%Y%m%d-%H%M%S}.pkl"
    try:
        with open(dump, "wb") as f:
            pickle.dump(raw, f)
        return f"raw dataset pickled to {dump}"
    except Exception as err:
        return f"raw dataset could not be pickled ({type(err).__name__}: {err})"

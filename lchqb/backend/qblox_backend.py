"""Qblox backend: maps the scqo abstractions onto qblox_scheduler.

``qblox_scheduler`` is imported lazily (inside methods) so that ``import lchqb`` works
without the Qblox stack installed, and so the simulated path never needs it.

Neutral-name mapping (scqo QubitView -> Qblox DeviceElement):
    readout_freq       <-> element.clock_freqs.readout
    drive_freq         <-> element.clock_freqs.f01
    pi_amp             <-> element.rxy.amp180
    readout_amp        <-> element.measure.pulse_amp
    readout_power_dbm  <-> hardware_options.output_att["<ro-port>-<q>.ro"]
                            + element.measure.pulse_amp (nominal +5 dBm full scale)
"""

from __future__ import annotations

import math
import warnings
from typing import TYPE_CHECKING, Any

import xarray as xr
from scqo.backend import Backend
from scqo.device import DeviceModel, QubitView

if TYPE_CHECKING:
    from scqo.experiment import Experiment

#: Nominal QRM-RF full-scale output (dBm) at pulse_amp=1.0, output_att=0 — the
#: datasheet maximum (+5 dBm into 50 Ohm). Frequency/LO/mixer-dependent in reality,
#: so absolute powers derived from it are good to ±a few dB; a per-setup
#: photon-number anchor (AC-Stark) is the Phase-3 refinement.
QBLOX_NOMINAL_FULL_SCALE_DBM = 5.0
#: The canonical digital operating point: keep the readout amplitude <= 0.5 full scale.
_CANONICAL_MAX_AMP = 0.5


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


class QbloxQubitView(QubitView):
    """A scqo QubitView backed by a qblox_scheduler ``DeviceElement``.

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

    # ------------------------------------------------------------ absolute power
    def _port_clock(self) -> str:
        """The hardware-options key of this element's readout line, e.g. 'q1:res-q1.ro'."""
        port = getattr(self._element.ports, "readout")
        port = port() if callable(port) else port
        return f"{port}-{self.name}.ro"

    def _output_att(self) -> int:
        """Current readout output attenuation (dB) from the hardware config
        (missing key -> 0 dB, the instrument default)."""
        if self._hw_agent is None:
            raise RuntimeError(
                f"{self.name}: no HardwareAgent attached — output_att (and so "
                f"readout_power_dbm) needs the hardware compilation config"
            )
        opts = self._hw_agent.hardware_configuration.hardware_options
        att_map = getattr(opts, "output_att", None) or {}
        return int(att_map.get(self._port_clock(), 0))

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
        target = float(value)
        if target > QBLOX_NOMINAL_FULL_SCALE_DBM:
            raise ValueError(
                f"{self.name}: target {target} dBm exceeds the chain maximum "
                f"(+{QBLOX_NOMINAL_FULL_SCALE_DBM} dBm at pulse_amp=1, output_att=0)"
            )
        # Largest EVEN attenuation in [0, 60] keeping the amplitude <= 0.5 (the
        # module validator is Multiples(2), 0..60 — an odd value would only fail
        # later, at instrument prepare); the amplitude absorbs the exact residual.
        att_max = QBLOX_NOMINAL_FULL_SCALE_DBM - target + 20.0 * math.log10(_CANONICAL_MAX_AMP)
        att = int(min(60, max(0, 2 * math.floor(att_max / 2.0))))
        amp = 10.0 ** ((target - QBLOX_NOMINAL_FULL_SCALE_DBM + att) / 20.0)
        if amp > _CANONICAL_MAX_AMP:  # only when att=0 cannot absorb it (target > ~-1 dBm)
            warnings.warn(
                f"{self.name}: hitting {target} dBm needs pulse_amp={amp:.3f} > "
                f"{_CANONICAL_MAX_AMP} (output_att already 0) — above the canonical "
                f"operating point"
            )
        if self._hw_agent is None:
            raise RuntimeError(
                f"{self.name}: no HardwareAgent attached — cannot write output_att"
            )
        opts = self._hw_agent.hardware_configuration.hardware_options
        if opts.output_att is None:
            opts.output_att = {}
        opts.output_att[self._port_clock()] = att  # authoritative: recompiled+pushed each run
        _write(self._element.measure, "pulse_amp", amp)


def _read_or_none(view: QubitView, field: str) -> float | None:
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

    def qubit(self, name: str) -> QbloxQubitView:
        return QbloxQubitView(self._qd.get_element(name), hw_agent=self._hw_agent)

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
                    f.write(hw.model_dump_json(indent=2))
        if self._config_file is not None:
            with open(self._config_file, "w", encoding="utf-8") as f:
                f.write(self._qd.to_json())

    def snapshot(self) -> dict:
        # Tolerate non-transmon elements (couplers etc.): report None for a field the
        # element doesn't carry rather than crashing on a real lab device tree.
        state: dict[str, dict] = {}
        for name in self._qd.elements:
            view = self.qubit(name)
            state[name] = {
                field: _read_or_none(view, field)
                for field in ("readout_freq", "drive_freq", "pi_amp", "readout_amp",
                              "readout_power_dbm")
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
        from qblox_scheduler.backends.qblox_backend import QbloxHardwareCompilationConfig

        self._hw_agent._hardware_configuration = QbloxHardwareCompilationConfig.model_validate(
            self._hw_agent._hardware_configuration
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

    def power_context(self, qubits: list[str]) -> dict:
        """Raw readout output-chain values per qubit (run-record provenance only)."""
        out: dict = {}
        for name in qubits:
            try:
                view = self._device.qubit(name)
                out[name] = {
                    "output_att_db": view._output_att(),
                    "pulse_amp": _read(view._element.measure, "pulse_amp"),
                    "nominal_full_scale_dbm": QBLOX_NOMINAL_FULL_SCALE_DBM,
                    "readout_power_dbm": view.readout_power_dbm,
                    "note": "power derived from the nominal +5 dBm full scale "
                            "(frequency-dependent, ±a few dB)",
                }
            except Exception:  # provenance must never fail a run
                out[name] = {}
        return out

    def acquire(self, experiment: "Experiment") -> xr.Dataset:
        schedule = experiment.probe()  # native qblox_scheduler.Schedule
        raw = self._hw_agent.run(schedule, timeout=120)
        return self._to_canonical(raw, experiment)

    @staticmethod
    def _to_canonical(raw: xr.Dataset, experiment: "Experiment") -> xr.Dataset:
        """Relabel a raw Qblox dataset into scqo's convention: dims (qubit, <sweep>), vars I/Q.

        The probes label every acquisition ``acq_channel=f"S_21_{qubit}"`` with the
        sweep loop variable as a per-point coordinate (cal02 reference pattern), so
        the hardware returns one complex S21 array per qubit over the swept axis
        (repetitions averaged on the cluster). The canonical sweep values come from
        ``experiment.sweep_axes`` — the probe built its loop from exactly those.
        On a structure mismatch the raw dataset is pickled for offline inspection.
        """
        import numpy as np

        qubits = list(experiment.params.qubits)  # type: ignore[attr-defined]
        if experiment.name == "qubit_tomography":
            n_train = int(experiment.params.num_training_shots)
            reps = int(experiment.params.num_averages)
            symmetrized = experiment.params.symmetrized_readout
            n_sym = 2 if symmetrized else 1
            n_gc = len(experiment.params.gate_counts)
            
            i_tomo_rows, q_tomo_rows = [], []
            i_train_rows, q_train_rows = [], []
            
            try:
                for name in qubits:
                    key = f"S_21_{name}"
                    if key not in raw.data_vars:
                        raise KeyError(f"Acquisition channel {key!r} not found in raw data.")
                    flat_data = np.asarray(raw[key].values).flatten()
                    
                    train_0 = flat_data[0:n_train]
                    train_1 = flat_data[n_train:2*n_train]
                    train_data = np.stack([train_0, train_1], axis=0)
                    
                    tomo_flat = flat_data[2*n_train:]
                    tomo_shape = (3, n_sym, n_gc, reps)
                    if tomo_flat.size != np.prod(tomo_shape):
                        raise ValueError(
                            f"Tomography data size mismatch for {name}: expected {np.prod(tomo_shape)} points, "
                            f"got {tomo_flat.size}"
                        )
                    tomo_data = tomo_flat.reshape(tomo_shape)
                    
                    i_train_rows.append(train_data.real)
                    q_train_rows.append(train_data.imag)
                    i_tomo_rows.append(tomo_data.real)
                    q_tomo_rows.append(tomo_data.imag)
            except (KeyError, ValueError) as err:
                raise type(err)(f"{err}; {_dump_raw(raw)}") from err
                
            return xr.Dataset(
                {
                    "I_tomo": (("qubit", "basis", "sym", "gate_count", "shot_idx"), np.stack(i_tomo_rows)),
                    "Q_tomo": (("qubit", "basis", "sym", "gate_count", "shot_idx"), np.stack(q_tomo_rows)),
                    "I_train": (("qubit", "prepared_state", "train_shot_idx"), np.stack(i_train_rows)),
                    "Q_train": (("qubit", "prepared_state", "train_shot_idx"), np.stack(q_train_rows)),
                },
                coords={
                    "qubit": qubits,
                    "basis": np.array(["x", "y", "z"]),
                    "sym": np.array(["reg", "inv"] if symmetrized else ["reg"]),
                    "gate_count": np.array(experiment.params.gate_counts),
                    "shot_idx": np.arange(reps),
                    "prepared_state": np.array([0, 1]),
                    "train_shot_idx": np.arange(n_train),
                }
            )

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
        dims = ("qubit", *axes.keys())
        return xr.Dataset(
            {"I": (dims, np.stack(i_rows)), "Q": (dims, np.stack(q_rows))},
            coords={"qubit": qubits, **axes},
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

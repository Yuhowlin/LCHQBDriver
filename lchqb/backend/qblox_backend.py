"""Qblox backend: maps the scqo abstractions onto qblox_scheduler.

``qblox_scheduler`` is imported lazily (inside methods) so that ``import lchqb`` works
without the Qblox stack installed, and so the simulated path never needs it.

Neutral-name mapping (scqo QubitView -> Qblox DeviceElement):
    readout_freq  <-> element.clock_freqs.readout
    drive_freq    <-> element.clock_freqs.f01
    pi_amp        <-> element.rxy.amp180
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import xarray as xr
from scqo.backend import Backend
from scqo.device import DeviceModel, QubitView

if TYPE_CHECKING:
    from scqo.experiment import Experiment


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
    """A scqo QubitView backed by a qblox_scheduler ``DeviceElement``."""

    def __init__(self, element: Any) -> None:
        self.name = element.name
        self._element = element

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


def _read_or_none(view: QubitView, field: str) -> float | None:
    """Read a neutral field, returning None if this element doesn't carry it."""
    try:
        return getattr(view, field)
    except (TypeError, AttributeError, KeyError):
        return None


class QbloxDeviceModel(DeviceModel):
    """Wraps a qblox_scheduler ``QuantumDevice``."""

    def __init__(self, quantum_device: Any, config_file: str | None = None) -> None:
        self._qd = quantum_device
        self._config_file = config_file

    def qubit(self, name: str) -> QbloxQubitView:
        return QbloxQubitView(self._qd.get_element(name))

    def save(self) -> None:
        # Write back to the EXACT file the device was loaded from. (to_json_file
        # writes <device_name>.json, which silently diverges from the dut_config.json
        # the backend loads — calibrations would be stale after a restart.)
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
                for field in ("readout_freq", "drive_freq", "pi_amp", "readout_amp")
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
        self._device = QbloxDeviceModel(self._hw_agent.quantum_device, config_file=device_config)

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

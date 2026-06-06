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
    from scqo.protocol import Protocol


class QbloxQubitView(QubitView):
    """A scqo QubitView backed by a qblox_scheduler ``DeviceElement``."""

    def __init__(self, element: Any) -> None:
        self.name = element.name
        self._element = element

    @property
    def readout_freq(self) -> float:
        return float(self._element.clock_freqs.readout())

    @readout_freq.setter
    def readout_freq(self, value: float) -> None:
        self._element.clock_freqs.readout(float(value))

    @property
    def drive_freq(self) -> float:
        return float(self._element.clock_freqs.f01())

    @drive_freq.setter
    def drive_freq(self, value: float) -> None:
        self._element.clock_freqs.f01(float(value))

    @property
    def pi_amp(self) -> float:
        return float(self._element.rxy.amp180())

    @pi_amp.setter
    def pi_amp(self, value: float) -> None:
        self._element.rxy.amp180(float(value))


class QbloxDeviceModel(DeviceModel):
    """Wraps a qblox_scheduler ``QuantumDevice``."""

    def __init__(self, quantum_device: Any, config_dir: str | None = None) -> None:
        self._qd = quantum_device
        self._config_dir = config_dir

    def qubit(self, name: str) -> QbloxQubitView:
        return QbloxQubitView(self._qd.get_element(name))

    def save(self) -> None:
        if self._config_dir is not None:
            self._qd.to_json_file(self._config_dir, add_timestamp=False)

    def snapshot(self) -> dict:
        state: dict[str, dict] = {}
        for name in self._qd.elements:
            view = self.qubit(name)
            state[name] = {
                "readout_freq": view.readout_freq,
                "drive_freq": view.drive_freq,
                "pi_amp": view.pi_amp,
            }
        return state


class QbloxBackend(Backend):
    """scqo Backend over a Qblox cluster (or dummy connections for dry runs)."""

    def __init__(self, hardware_config: str, device_config: str, output_dir: str | None = None) -> None:
        # Lazy import keeps `import lchqb` free of qblox_scheduler.
        from qblox_scheduler import HardwareAgent

        self._hw_agent = HardwareAgent(
            hardware_configuration=hardware_config,
            quantum_device_configuration=device_config,
            output_dir=output_dir,
        )
        self._device = QbloxDeviceModel(self._hw_agent.quantum_device, config_dir=output_dir)

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

    def acquire(self, protocol: "Protocol") -> xr.Dataset:
        schedule = protocol.build()  # native qblox_scheduler.Schedule
        raw = self._hw_agent.run(schedule, timeout=120)
        return self._to_canonical(raw, protocol)

    @staticmethod
    def _to_canonical(raw: xr.Dataset, protocol: "Protocol") -> xr.Dataset:
        """Relabel a raw Qblox dataset into scqo's convention: dims (qubit, <sweep>), vars I/Q.

        TODO: implement against the real ``hw_agent.run`` output schema for the lab's
        acquisition setup. Kept explicit so the seam is obvious; until then the Qblox
        hardware path raises rather than silently returning mislabeled data.
        """
        raise NotImplementedError(
            "Map the raw Qblox dataset to scqo canonical form (dims=(qubit, sweep...), vars=I/Q) "
            "for this lab's acquisition. Use SimulatedBackend for offline runs."
        )

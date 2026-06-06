"""Qblox resonator spectroscopy — supplies only ``build()``.

Parameters, fitting, device writeback and the simulator are all inherited from
``scqo.protocols.ResonatorSpectroscopy``. ``qblox_scheduler`` is imported inside
``build()`` so the simulated path (and ``import lchqb``) needs no Qblox install.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.protocols import ResonatorSpectroscopy


@register
class QbloxResonatorSpectroscopy(ResonatorSpectroscopy):
    """Build a multiplexed resonator-spectroscopy Schedule for a Qblox cluster."""

    def build(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        detuning = self.sweep_axes["detuning_hz"]
        span = float(detuning[-1] - detuning[0])
        num = self.params.num_points
        reps = self.params.num_averages

        schedule = Schedule("resonator_spectroscopy_multiplexed")
        for qubit_name in self.params.qubits:
            element = self.backend.device.qubit(qubit_name)  # QbloxQubitView
            center = element.readout_freq
            sub = Schedule(f"res_spec_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                with sub.loop(
                    linspace(center - span / 2, center + span / 2, num, dtype=DType.FREQUENCY)
                ) as freq:
                    sub.add(Measure(qubit_name, freq=freq))
                    sub.add(IdlePulse(10e-6))
            schedule.add(sub)
        return schedule

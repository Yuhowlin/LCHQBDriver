"""Qblox power Rabi — supplies only ``probe()``.

Amplitude sweep: X(amp) — Measure, looping the drive amplitude. Parameters, the cosine
fit, pi_amp recovery and writeback are inherited from ``scqo.experiments.PowerRabi``.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import PowerRabi


@register
class QbloxPowerRabi(PowerRabi):
    """Build a multiplexed power-Rabi Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, X
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        amp_factor = self.sweep_axes["amp_factor"]
        reps = self.params.num_averages

        schedule = Schedule("power_rabi_multiplexed")
        for qubit_name in self.params.qubits:
            pi_amp = self.backend.device.qubit(qubit_name).pi_amp  # neutral field -> absolute volts
            amp_abs = amp_factor * pi_amp
            sub = Schedule(f"power_rabi_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                with sub.loop(linspace(amp_abs[0], amp_abs[-1], amp_abs.size, dtype=DType.AMPLITUDE)) as amp:
                    sub.add(X(qubit_name, amp180=amp))
                    sub.add(Measure(qubit_name))
                    sub.add(IdlePulse(10e-6))
            schedule.add(sub)
        return schedule

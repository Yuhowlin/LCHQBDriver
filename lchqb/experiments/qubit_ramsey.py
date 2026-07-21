"""Qblox Ramsey — supplies only ``probe()``.

Same one-method pattern as resonator spectroscopy, on a completely different physics
experiment: X90 — idle(t) — X90 — Measure, looping the idle time. Parameters, the
decaying-cosine fit, T2*/detuning extraction, and the drive_freq writeback are all
inherited from ``scqo.experiments.QubitRamsey``.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import QubitRamsey


@register
class QbloxQubitRamsey(QubitRamsey):
    """Build a multiplexed Ramsey Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, X90
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        idle_ns = self.sweep_axes["idle_time_ns"]
        reps = self.params.num_averages
        detuning = self.params.frequency_detuning_hz

        schedule = Schedule("ramsey_multiplexed")
        for qubit_name in self.params.targets:
            sub = Schedule(f"ramsey_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                with sub.loop(
                    linspace(idle_ns[0] * 1e-9, idle_ns[-1] * 1e-9, idle_ns.size, dtype=DType.TIME)
                ) as tau:
                    # First pi/2; the artificial detuning is applied as a frame phase that
                    # advances with the idle time, producing the Ramsey fringe.
                    sub.add(X90(qubit_name))
                    sub.add(IdlePulse(tau))
                    # Detune via accumulated phase = 2*pi * detuning * tau on the second pi/2.
                    sub.add(X90(qubit_name, phase=360.0 * detuning * tau))
                    sub.add(
                        Measure(
                            qubit_name,
                            coords={f"tau_{qubit_name}": tau},
                            acq_channel=f"S_21_{qubit_name}",
                        )
                    )
                    sub.add(IdlePulse(10e-6))
            schedule.add(sub)
        return schedule

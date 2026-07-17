"""Qblox qubit relaxation vs flux (T1 Spectrum) — supplies only ``probe()``.

Reset -> X (pi pulse) -> VoltageOffset (Z pulse) -> Measure delayed by swept wait.
"""

from __future__ import annotations

import math
from typing import Any

from scqo import register
from scqo.experiments import QubitRelaxationFlux


def _idle_flux(element: Any) -> float:
    try:
        sweet = element.flux_params.sweet_spot
        sweet = float(sweet() if callable(sweet) else sweet)
    except (AttributeError, TypeError):
        return 0.0
    return sweet if math.isfinite(sweet) else 0.0


@register
class QbloxQubitRelaxationFlux(QubitRelaxationFlux):
    """Build a multiplexed T1 vs flux Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, Reset, X, VoltageOffset
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        flux_v = self.sweep_axes["flux_amp"]
        wait_ns = self.sweep_axes["wait_time_ns"]
        reps = self.params.num_averages

        schedule = Schedule("qubit_relaxation_flux_multiplexed")
        for qubit_name in self.params.qubits:
            view = self.backend.device.qubit(qubit_name)
            element = view._element
            flux_port = element.ports.flux
            idle_flux = _idle_flux(element)
            
            sub = Schedule(f"t1_flux_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                with sub.loop(
                    linspace(float(flux_v[0]), float(flux_v[-1]), flux_v.size, dtype=DType.AMPLITUDE)
                ) as z_amp:
                    with sub.loop(
                        linspace(wait_ns[0] * 1e-9, wait_ns[-1] * 1e-9, wait_ns.size, dtype=DType.TIME)
                    ) as tau:
                        sub.add(Reset(qubit_name))
                        sub.add(X(qubit=qubit_name))
                        sub.add(VoltageOffset(idle_flux + z_amp, 0, port=flux_port))
                        sub.add(
                            Measure(
                                qubit_name,
                                coords={
                                    f"flux_{qubit_name}": z_amp,
                                    f"tau_{qubit_name}": tau,
                                },
                                acq_channel=f"S_21_{qubit_name}",
                            ),
                            rel_time=tau,
                        )
                        sub.add(VoltageOffset(idle_flux, 0, port=flux_port))
                        sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

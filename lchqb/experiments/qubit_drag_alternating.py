"""Qblox DRAG alternating (180/-180) calibration — supplies only ``probe()``.

Reset -> N repetitions of [X180(beta), Rxy(180, 180, -beta)] -> Measure.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import QubitDragAlternating


@register
class QbloxQubitDragAlternating(QubitDragAlternating):
    """Build a multiplexed DRAG alternating Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, Reset, X, Rxy
        from qblox_scheduler.operations.expressions import DType
        from qblox_scheduler.operations.loop_domains import arange

        beta = self.sweep_axes["beta"]
        nb_pulses = self.sweep_axes["nb_of_pulses"]
        reps = self.params.num_averages

        schedule = Schedule("drag_alternating_multiplexed")
        for qubit_name in self.params.qubits:
            sub = Schedule(f"drag_alt_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                for npi in nb_pulses:
                    npi_val = int(npi)
                    for b in beta:
                        beta_val = float(b)
                        
                        sub.add(Reset(qubit_name))
                        for _ in range(npi_val):
                            # Play X180 (theta=180, phi=0, beta)
                            sub.add(X(qubit=qubit_name, beta=beta_val))
                            # Play -X180 (theta=180, phi=180, -beta)
                            sub.add(Rxy(theta=180.0, phi=180.0, qubit=qubit_name, beta=-beta_val))
                            
                        sub.add(
                            Measure(
                                qubit_name,
                                coords={
                                    f"nb_of_pulses_{qubit_name}": npi_val,
                                    f"beta_{qubit_name}": beta_val,
                                },
                                acq_channel=f"S_21_{qubit_name}",
                            )
                        )
                        sub.add(IdlePulse(1e-6))
            schedule.add(sub)
        return schedule

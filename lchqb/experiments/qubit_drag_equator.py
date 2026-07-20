"""Qblox DRAG equator calibration — supplies only ``probe()``.

Reset -> X90(beta) -> repetitions of [Y180, -Y180, or X180] -> Measure.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import QubitDragEquator


@register
class QbloxQubitDragEquator(QubitDragEquator):
    """Build a multiplexed DRAG equator Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, Reset, X, X90, Y, Rxy
        from qblox_scheduler.operations.expressions import DType
        from qblox_scheduler.operations.loop_domains import arange

        beta = self.sweep_axes["beta"]
        reps = self.params.num_averages
        N = self.params.pulse_repetitions

        schedule = Schedule("drag_equator_multiplexed")
        for qubit_name in self.params.qubits:
            sub = Schedule(f"drag_eq_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                for b in beta:
                    beta_val = float(b)
                    
                    # Seq 0: X90 -> (Y180)^N
                    sub.add(Reset(qubit_name))
                    sub.add(X90(qubit=qubit_name, beta=beta_val))
                    for _ in range(N):
                        sub.add(Y(qubit=qubit_name, beta=beta_val))
                    sub.add(
                        Measure(
                            qubit_name,
                            coords={
                                f"seq_idx_{qubit_name}": 0,
                                f"beta_{qubit_name}": beta_val,
                            },
                            acq_channel=f"S_21_{qubit_name}",
                        )
                    )
                    sub.add(IdlePulse(1e-6))
                    
                    # Seq 1: X90 -> (-Y180)^N
                    sub.add(Reset(qubit_name))
                    sub.add(X90(qubit=qubit_name, beta=beta_val))
                    for _ in range(N):
                        sub.add(Rxy(theta=180.0, phi=270.0, qubit=qubit_name, beta=beta_val))
                    sub.add(
                        Measure(
                            qubit_name,
                            coords={
                                f"seq_idx_{qubit_name}": 1,
                                f"beta_{qubit_name}": beta_val,
                            },
                            acq_channel=f"S_21_{qubit_name}",
                        )
                    )
                    sub.add(IdlePulse(1e-6))

                    # Seq 2: X90 -> (X180)^N (Ref)
                    sub.add(Reset(qubit_name))
                    sub.add(X90(qubit=qubit_name, beta=beta_val))
                    for _ in range(N):
                        sub.add(X(qubit=qubit_name, beta=beta_val))
                    sub.add(
                        Measure(
                            qubit_name,
                            coords={
                                f"seq_idx_{qubit_name}": 2,
                                f"beta_{qubit_name}": beta_val,
                            },
                            acq_channel=f"S_21_{qubit_name}",
                        )
                    )
                    sub.add(IdlePulse(1e-6))
            schedule.add(sub)
        return schedule

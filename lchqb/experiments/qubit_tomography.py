"""Qblox qubit state tomography — supplies only ``probe()``.

Builds a multiplexed schedule that performs training (states 0 and 1) followed
by tomography (bases X, Y, Z for various gate counts and readouts).
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import QubitTomography


@register
class QbloxQubitTomography(QubitTomography):
    """Build a multiplexed state tomography Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, Reset, X, X90, Rxy
        from qblox_scheduler.operations.loop_domains import DType, arange

        n_train_shots = int(self.params.num_training_shots)
        reps = int(self.params.num_averages)
        gate_counts = self.params.gate_counts
        symmetrized = self.params.symmetrized_readout

        schedule = Schedule("tomography_multiplexed")
        for qubit_name in self.params.qubits:
            sub = Schedule(f"tomo_{qubit_name}")
            config = self.params.qubit_configs.get(qubit_name, {"init_state": "0", "target_gate": "X"})
            init_state = config["init_state"]
            target_gate = config["target_gate"]

            # --- 1. Training Part (Single-Shot, binned) ---
            # State 0 loop
            with sub.loop(arange(0, n_train_shots, 1, DType.NUMBER)) as shot:
                sub.add(Reset(qubit_name))
                sub.add(
                    Measure(
                        qubit_name,
                        coords={f"state_train_{qubit_name}": 0, f"shot_train_{qubit_name}": shot},
                        acq_channel=f"S_21_{qubit_name}",
                    )
                )
                sub.add(IdlePulse(10e-6))

            # State 1 loop
            with sub.loop(arange(0, n_train_shots, 1, DType.NUMBER)) as shot:
                sub.add(Reset(qubit_name))
                sub.add(X(qubit_name))
                sub.add(
                    Measure(
                        qubit_name,
                        coords={f"state_train_{qubit_name}": 1, f"shot_train_{qubit_name}": shot},
                        acq_channel=f"S_21_{qubit_name}",
                    )
                )
                sub.add(IdlePulse(10e-6))

            # --- 2. Tomography Part (Single-Shot, binned) ---
            for b_idx, basis in enumerate(["x", "y", "z"]):
                for s_idx, sym in enumerate(["reg", "inv"] if symmetrized else ["reg"]):
                    for gc_idx, gc in enumerate(gate_counts):
                        with sub.loop(arange(0, reps, 1, DType.NUMBER)) as shot:
                            sub.add(Reset(qubit_name))

                            # (A) Apply initialization state
                            if init_state == "1":
                                sub.add(X(qubit_name))
                            elif init_state == "+":
                                sub.add(Rxy(theta=90.0, phi=90.0, qubit=qubit_name))
                            elif init_state == "-":
                                sub.add(Rxy(theta=-90.0, phi=90.0, qubit=qubit_name))
                            elif init_state == "+i":
                                sub.add(Rxy(theta=-90.0, phi=0.0, qubit=qubit_name))
                            elif init_state == "-i":
                                sub.add(Rxy(theta=90.0, phi=0.0, qubit=qubit_name))

                            # (B) Apply target gate repeated gc times
                            for _ in range(gc):
                                if target_gate == "X":
                                    sub.add(X(qubit_name))
                                elif target_gate == "X90":
                                    sub.add(X90(qubit_name))
                                elif target_gate == "Y":
                                    sub.add(Rxy(theta=180.0, phi=90.0, qubit=qubit_name))
                                elif target_gate == "Y90":
                                    sub.add(Rxy(theta=90.0, phi=90.0, qubit=qubit_name))

                            # (C) Apply basis rotation
                            if basis == "x":
                                sub.add(Rxy(theta=90.0, phi=90.0, qubit=qubit_name))
                            elif basis == "y":
                                sub.add(Rxy(theta=-90.0, phi=0.0, qubit=qubit_name))

                            # (D) Apply inversion for symmetrized readout
                            if sym == "inv":
                                sub.add(X(qubit_name))

                            # (E) Measure and bin individually
                            sub.add(
                                Measure(
                                    qubit_name,
                                    coords={
                                        f"basis_{qubit_name}": b_idx,
                                        f"sym_{qubit_name}": s_idx,
                                        f"gate_count_{qubit_name}": gc_idx,
                                        f"shot_{qubit_name}": shot,
                                    },
                                    acq_channel=f"S_21_{qubit_name}",
                                )
                            )
                            sub.add(IdlePulse(10e-6))

            schedule.add(sub)
        return schedule

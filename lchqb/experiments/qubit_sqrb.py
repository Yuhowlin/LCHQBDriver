"""Qblox qubit SQRB — supplies only ``probe()``.

Builds a schedule executing randomized Clifford gate sequences of increasing depths.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import QubitSQRB


@register
class QbloxQubitSQRB(QubitSQRB):
    """Build a Single Qubit RB Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import Reset, Measure, X, X90, Y, Y90, Rxy
        
        # Lazy imports of the pycqed RB generators from qblox_drive_AS
        from qblox_drive_AS.SQRB_utils.pycqed_randomized_benchmarking.randomized_benchmarking import randomized_benchmarking_sequence
        from qblox_drive_AS.SQRB_utils.pycqed_randomized_benchmarking.two_qubit_clifford_group import SingleQubitClifford, common_cliffords

        qubits = self.params.qubits
        depths = self.params.get_depths()
        n_seqs = self.params.num_random_sequences
        reps = self.params.num_averages
        seed = self.params.seed

        pycqed_operation_map = {
            "X180": lambda q: X(q),
            "X90": lambda q: X90(q),
            "Y180": lambda q: Y(q),
            "Y90": lambda q: Y90(q),
            "mX90": lambda q: Rxy(qubit=q, phi=0.0, theta=-90.0),
            "mY90": lambda q: Rxy(qubit=q, phi=90.0, theta=-90.0),
        }

        # Repetitions=reps repeats the entire schedule on hardware
        schedule = Schedule("sqrb_multiplexed", repetitions=reps)
        
        # Loop over distinct sequences and depths on host side
        acq_index = 0
        for seq_idx in range(n_seqs):
            for d_idx, m in enumerate(depths):
                # Align elements across multiplexed qubits
                reset_ops = []
                for q in qubits:
                    reset_ops.append(schedule.add(Reset(q)))
                
                # Play sequence for each qubit
                for q_idx, q in enumerate(qubits):
                    reset = reset_ops[q_idx]
                    if m > 0:
                        seq_seed = seed + seq_idx if seed is not None else None
                        rb_sequence_m = randomized_benchmarking_sequence(
                            m, number_of_qubits=1, seed=seq_seed, desired_net_cl=common_cliffords["I"]
                        )
                        
                        align_reset = 1
                        for cl_idx in rb_sequence_m:
                            cl_decomp = SingleQubitClifford(cl_idx).gate_decomposition
                            for gate, _ in cl_decomp:
                                if gate != "I":
                                    schedule.add(
                                        pycqed_operation_map[gate](q),
                                        ref_op=reset if align_reset else None
                                    )
                            align_reset = 0
                
                # Perform multiplexed readouts
                for q in qubits:
                    # coords help define coordinates in the raw returned dataset
                    schedule.add(
                        Measure(
                            q,
                            coords={
                                f"depth_{q}": d_idx,
                                f"sequence_idx_{q}": seq_idx,
                            },
                            acq_channel=f"S_21_{q}",
                            acq_index=acq_index
                        )
                    )
                acq_index += 1
                
        return schedule

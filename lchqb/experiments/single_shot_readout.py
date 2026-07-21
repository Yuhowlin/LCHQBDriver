"""Qblox single-shot readout (IQ blobs) — supplies only ``probe()``.

cal16 (MultiplexedSSRO) reference pattern, per-shot mechanics: the shot loop
variable is CAPTURED and written into the acquisition ``coords`` — every
(state, shot) pair is then a distinct labeled bin, so the cluster appends one
I/Q point per shot instead of averaging (same mechanism the averaged probes use
in reverse: there the reps loop is *unlabeled*, so identical coords average).
No ``num_averages`` exists here by design.

Deviation from cal16: the two prepared states are sequential blocks (all |0>
shots, then all |1> shots) instead of interleaved per shot, so the flat bin
order is state-major and matches the canonical sweep-axes order
(``prepared_state``, ``shot_idx``) that ``_to_canonical`` reshapes by.
Parameters and the two-Gaussian fidelity fit are inherited from
``scqo.experiments.SingleShotReadout``.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import SingleShotReadout


@register
class QbloxSingleShotReadout(SingleShotReadout):
    """Build a multiplexed per-shot SSRO Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, Reset, X
        from qblox_scheduler.operations.loop_domains import DType, arange

        num_shots = int(self.params.num_shots)

        schedule = Schedule("single_shot_readout_multiplexed")
        for qubit_name in self.params.targets:
            sub = Schedule(f"ssro_{qubit_name}")
            # prepared_state 0: Reset -> Measure, one labeled bin per shot
            with sub.loop(arange(0, num_shots, 1, DType.NUMBER)) as shot:
                sub.add(Reset(qubit_name))
                sub.add(
                    Measure(
                        qubit_name,
                        coords={f"state_{qubit_name}": 0, f"shot_{qubit_name}": shot},
                        acq_channel=f"S_21_{qubit_name}",
                    )
                )
            # prepared_state 1: Reset -> X -> Measure, one labeled bin per shot
            with sub.loop(arange(0, num_shots, 1, DType.NUMBER)) as shot:
                sub.add(Reset(qubit_name))
                sub.add(X(qubit=qubit_name))
                sub.add(
                    Measure(
                        qubit_name,
                        coords={f"state_{qubit_name}": 1, f"shot_{qubit_name}": shot},
                        acq_channel=f"S_21_{qubit_name}",
                    )
                )
            sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

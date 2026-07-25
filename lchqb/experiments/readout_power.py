"""Qblox per-shot readout-amplitude scan — supplies only ``probe()``.

Per amplitude prefactor the readout pulse amplitude is set via
``Measure(pulse_amp=...)``, prefactor x the CURRENT ``readout_amp`` (read the same
way resonator_spectroscopy_power_amp's punchout probe reads it). Each prefactor runs
two sequential prepared-state blocks (|0>: Reset -> Measure, |1>: Reset -> X ->
Measure) with the shot loop variable CAPTURED into labeled coords — the
single_shot_readout per-shot mechanism, so the cluster appends one I/Q point per
shot instead of averaging. Flat bin order is amp-major, then state, then shot,
matching the canonical sweep axes (``amp_prefactor``, ``prepared_state``,
``shot_idx``). No reps loop / no ``num_averages`` by design.

Method note: QBLOX_training's cal17 calibrates readout amplitude via the AC-Stark
shift of the qubit frequency — a different (averaged) method deliberately NOT
followed here; this probe is the per-shot fidelity method matching the QM backend.
Parameters and the fidelity-vs-amplitude fit are inherited from
``scqo.experiments.ReadoutPower``.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import ReadoutPower


@register
class QbloxReadoutPower(ReadoutPower):
    """Build a multiplexed per-shot readout-amplitude Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, Reset, X
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        prefactors = self.sweep_axes["amp_prefactor"]
        num_shots = int(self.params.num_shots)

        schedule = Schedule("readout_power_multiplexed")
        for qubit_name in self.params.targets:
            view = self.device.channel(qubit_name, "readout")
            # the prefactor scales the CURRENT readout amplitude (punchout pattern)
            amp_lo = float(prefactors[0] * view.readout_amp)
            amp_hi = float(prefactors[-1] * view.readout_amp)
            sub = Schedule(f"readout_power_{qubit_name}")
            with sub.loop(
                linspace(amp_lo, amp_hi, prefactors.size, dtype=DType.AMPLITUDE)
            ) as amp:
                # prepared_state 0: Reset -> Measure, one labeled bin per shot
                with sub.loop(arange(0, num_shots, 1, DType.NUMBER)) as shot:
                    sub.add(Reset(qubit_name))
                    sub.add(
                        Measure(
                            qubit_name,
                            pulse_amp=amp,
                            coords={
                                f"amp_{qubit_name}": amp,
                                f"state_{qubit_name}": 0,
                                f"shot_{qubit_name}": shot,
                            },
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
                            pulse_amp=amp,
                            coords={
                                f"amp_{qubit_name}": amp,
                                f"state_{qubit_name}": 1,
                                f"shot_{qubit_name}": shot,
                            },
                            acq_channel=f"S_21_{qubit_name}",
                        )
                    )
            sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

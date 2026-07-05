"""Qblox resonator spectroscopy vs power (punchout) — supplies only ``probe()``.

cal03 reference pattern: the readout pulse amplitude is swept per point via
``Measure(pulse_amp=...)``. The scheduler only offers LINEAR loop domains, so the
hardware sweeps amplitude linearly; ``define_sweep`` is overridden to declare the
TRUE dB values of that linear-amplitude grid (the scqat estimator's optimal-power
derivative is value-based, so non-uniform dB spacing is handled exactly).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from scqo import register
from scqo.experiments import ResonatorSpectroscopyPower


@register
class QbloxResonatorSpectroscopyPower(ResonatorSpectroscopyPower):
    """Build a multiplexed punchout Schedule for a Qblox cluster."""

    def define_sweep(self) -> dict[str, np.ndarray]:
        sweep = super().define_sweep()
        # linear-amplitude hardware sweep -> declare its true (non-uniform) dB axis
        p = self.params
        amps_rel = np.linspace(
            10.0 ** (p.min_power_db / 20.0), 10.0 ** (p.max_power_db / 20.0), p.num_power_points
        )
        sweep["power_db"] = 20.0 * np.log10(amps_rel)
        return sweep

    def probe(self) -> Any:
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        detuning = self.sweep_axes["detuning_hz"]
        span = float(detuning[-1] - detuning[0])
        n_freq = self.params.num_freq_points
        amps_rel = 10.0 ** (np.asarray(self.sweep_axes["power_db"]) / 20.0)
        reps = self.params.num_averages

        schedule = Schedule("resonator_spectroscopy_power_multiplexed")
        for qubit_name in self.params.qubits:
            view = self.backend.device.qubit(qubit_name)
            center = view.readout_freq
            amp_lo = float(amps_rel[0] * view.readout_amp)
            amp_hi = float(amps_rel[-1] * view.readout_amp)
            sub = Schedule(f"punchout_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                # freq OUTER, amp INNER: flat bin order then matches the canonical
                # sweep-axes order (detuning_hz, power_db)
                with sub.loop(
                    linspace(center - span / 2, center + span / 2, n_freq, dtype=DType.FREQUENCY)
                ) as freq:
                    with sub.loop(
                        linspace(amp_lo, amp_hi, len(amps_rel), dtype=DType.AMPLITUDE)
                    ) as amp:
                        sub.add(
                            Measure(
                                qubit_name,
                                freq=freq,
                                pulse_amp=amp,
                                coords={f"frequency_{qubit_name}": freq, f"amp_{qubit_name}": amp},
                                acq_channel=f"S_21_{qubit_name}",
                            )
                        )
                        sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

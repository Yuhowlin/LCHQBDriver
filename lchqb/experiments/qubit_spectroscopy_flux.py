"""Qblox pulsed flux qubit spectroscopy — supplies only ``probe()``.

cal07 reference pattern: per flux point set a ``VoltageOffset`` on the qubit's own
flux line, step the drive clock across the detuning window around the current
``drive_freq``, apply an X probe pulse, then return the flux to its idle value
BEFORE measuring (clean readout at the calibrated operating point). Flux safety:
every subschedule ends with the flux line back at 0 V (cal07 pattern).
Parameters, the transmon-arch fit and the sweet-spot/Ej_sum reporting are
inherited from ``scqo.experiments.QubitSpectroscopyFlux``.
"""

from __future__ import annotations

import math
from typing import Any

from scqo import register
from scqo.experiments import QubitSpectroscopyFlux


def _idle_flux(element: Any) -> float:
    """The flux to measure at: the calibrated sweet spot when known, else 0 V.

    Tolerates both scheduler API generations (legacy QCoDeS callables and
    pydantic-model plain attributes) and elements without ``flux_params``.
    """
    try:
        sweet = element.flux_params.sweet_spot
        sweet = float(sweet() if callable(sweet) else sweet)
    except (AttributeError, TypeError):
        return 0.0
    return sweet if math.isfinite(sweet) else 0.0


@register
class QbloxQubitSpectroscopyFlux(QubitSpectroscopyFlux):
    """Build a multiplexed pulsed flux-spectroscopy Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        if self.params.flux_component is not None:
            raise NotImplementedError(
                "flux_component is not realized on the Qblox backend yet: this "
                "probe sweeps each target's OWN flux line only (an assigned "
                "source would be silently wrong, so it refuses)")
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import (
            IdlePulse,
            Measure,
            Reset,
            SetClockFrequency,
            VoltageOffset,
            X,
        )
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        flux_v = self.sweep_axes["flux_bias_v"]
        detuning = self.sweep_axes["detuning_hz"]
        reps = self.params.num_averages

        schedule = Schedule("qubit_spectroscopy_flux_multiplexed")
        for qubit_name in self.params.targets:
            view = self.backend.device.component(qubit_name)
            element = view._element  # driver-internal: ports live on the raw element
            flux_port = element.ports.flux
            center = view.drive_freq  # detuning is relative to the CURRENT drive_freq
            drive_clock = f"{qubit_name}.01"
            idle_flux = _idle_flux(element)
            sub = Schedule(f"qubit_spec_flux_{qubit_name}")
            with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                # flux OUTER, detuning INNER: flat bin order then matches the
                # canonical sweep-axes order (flux_bias_v, detuning_hz)
                with sub.loop(
                    linspace(float(flux_v[0]), float(flux_v[-1]), flux_v.size, dtype=DType.AMPLITUDE)
                ) as flux:
                    with sub.loop(
                        linspace(
                            center + float(detuning[0]),
                            center + float(detuning[-1]),
                            detuning.size,
                            dtype=DType.FREQUENCY,
                        )
                    ) as freq:
                        # 1. bias the qubit's own flux line for this point
                        sub.add(VoltageOffset(flux, 0, port=flux_port))
                        sub.add(IdlePulse(4e-9))
                        # 2. thermalize at the biased flux
                        sub.add(Reset(qubit_name))
                        # 3. probe pulse at the shifted drive frequency
                        sub.add(SetClockFrequency(clock=drive_clock, frequency=freq))
                        sub.add(X(qubit=qubit_name))
                        # 4. flux back to idle BEFORE the readout (cal07 pattern)
                        sub.add(VoltageOffset(idle_flux, 0, port=flux_port))
                        sub.add(IdlePulse(4e-9))
                        sub.add(IdlePulse(61e-9))  # QRC-with-QCM settling fudge (cal07)
                        sub.add(
                            Measure(
                                qubit_name,
                                coords={
                                    f"flux_{qubit_name}": flux,
                                    f"frequency_{qubit_name}": freq,
                                },
                                acq_channel=f"S_21_{qubit_name}",
                            )
                        )
            # SAFETY: flux line back to 0 V at the end of the subschedule (cal07)
            sub.add(VoltageOffset(0.0, 0, port=flux_port))
            sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

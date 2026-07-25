"""Qblox pulsed flux qubit spectroscopy — supplies only ``probe()``.

cal07b-style CW pattern: per flux point set a ``VoltageOffset`` on the qubit's own
flux line, step the drive clock across the detuning window around the current
``drive_freq_hz``, apply a weak CW SATURATION drive (``view.drive_amp`` — the
``drive_power_dbm`` residual parked on ``spec.spec_amp``) held through the driven
dwell, then return the flux to its idle value BEFORE measuring (clean readout at
the calibrated operating point, matching the QM flux probe). That return-to-idle
IS the ``_pulse`` name's probe contract: every slice reads out at the same
idle-flux condition, so the neutral ``estimate()`` reduces the whole map against
ONE global IQ reference. Unlike the old cal07
X-pulse version this needs no calibrated pi, so it works during bring-up. Flux
safety: every subschedule ends with the drive off and the flux line back at 0 V.

Parameters, the transmon-arch fit and the sweet-spot/Ej_sum reporting are
inherited from ``scqo.experiments.QubitSpectroscopyFluxPulse``. The core ``run()``
parks ``drive_power_dbm`` (a recorded set -> revert) before this probe reads
``view.drive_amp``.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import QubitSpectroscopyFluxPulse

from ._vendor import idle_flux as _idle_flux, vendor_element


@register
class QbloxQubitSpectroscopyFluxPulse(QubitSpectroscopyFluxPulse):
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
        )
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        flux_v = self.sweep_axes["flux_bias_v"]
        detuning = self.sweep_axes["detuning_hz"]
        reps = self.params.num_averages

        schedule = Schedule("qubit_spectroscopy_flux_pulse_multiplexed")
        for qubit_name in self.params.targets:
            view = self.device.channel(qubit_name, "drive")
            # ports are vendor-only; each is reached through the channel whose
            # FUNCTION it carries, so a target with no flux wiring refuses here
            element = vendor_element(self, qubit_name, "flux")
            flux_port = element.ports.flux
            microwave_port = vendor_element(self, qubit_name, "drive").ports.microwave
            center = view.drive_freq_hz  # detuning is relative to the CURRENT drive_freq_hz
            drive_amp = float(view.drive_amp)  # run() parked the solved spec_amp residual
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
                        # 2. weak CW saturation drive at the shifted frequency, held
                        #    through the driven dwell (Reset = the steady-state wait,
                        #    the cal05/cal07b idiom) — no calibrated pi needed
                        sub.add(SetClockFrequency(clock=drive_clock, frequency=freq))
                        sub.add(VoltageOffset(drive_amp, 0, port=microwave_port, clock=drive_clock))
                        sub.add(Reset(qubit_name))
                        sub.add(VoltageOffset(0, 0, port=microwave_port, clock=drive_clock))
                        # 3. flux back to idle BEFORE the readout (measure at the
                        #    calibrated operating point, matching the QM flux probe)
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
            # SAFETY: drive off + flux line back to 0 V at the end of the subschedule
            sub.add(VoltageOffset(0, 0, port=microwave_port, clock=drive_clock))
            sub.add(VoltageOffset(0.0, 0, port=flux_port))
            sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

"""Qblox resonator spectroscopy vs flux — supplies only ``probe()``.

cal04 reference pattern: per flux point set a ``VoltageOffset`` on the qubit's own
flux line and let it settle, then sweep the readout frequency across the detuning
window around the current ``readout_freq_hz`` via ``Measure(freq=...)``. Unlike
qubit_spectroscopy_flux_pulse there is no return-to-idle before readout — the resonator
is measured AT the biased flux, the flux-dependent dip IS the signal. Flux safety:
every subschedule ends with the flux line back at its idle value
(``_vendor.idle_flux``: the calibrated sweet spot when known, else 0 V — shared
with the qubit flux probe).
Parameters, the dispersive-model fit and the sweet-spot/f_r0/g reporting are
inherited from ``scqo.experiments.ResonatorSpectroscopyFlux``.
"""

from __future__ import annotations

from typing import Any

from scqo import register
from scqo.experiments import ResonatorSpectroscopyFlux

from ._vendor import idle_flux as _idle_flux, vendor_element


@register
class QbloxResonatorSpectroscopyFlux(ResonatorSpectroscopyFlux):
    """Build a multiplexed resonator-flux-map Schedule for a Qblox cluster."""

    def probe(self) -> Any:
        if self.params.flux_component is not None:
            raise NotImplementedError(
                "flux_component is not realized on the Qblox backend yet: this "
                "probe sweeps each target's OWN flux line only (an assigned "
                "source would be silently wrong, so it refuses)")
        from qblox_scheduler import Schedule
        from qblox_scheduler.operations import IdlePulse, Measure, VoltageOffset
        from qblox_scheduler.operations.loop_domains import DType, arange, linspace

        flux_v = self.sweep_axes["flux_bias_v"]
        detuning = self.sweep_axes["detuning_hz"]
        reps = self.params.num_averages

        schedule = Schedule("resonator_spectroscopy_flux_multiplexed")
        for qubit_name in self.params.targets:
            # the flux port is vendor-only; reaching it through the FLUX channel
            # means a target with no flux wiring refuses here, not mid-schedule
            element = vendor_element(self, qubit_name, "flux")
            flux_port = element.ports.flux
            # detuning is relative to the CURRENT readout_freq_hz (on q<n>_ro)
            center = self.device.channel(qubit_name, "readout").readout_freq_hz
            idle_flux = _idle_flux(element)
            sub = Schedule(f"res_spec_flux_{qubit_name}")
            # flux OUTER, detuning INNER: flat bin order then matches the canonical
            # sweep-axes order (flux_bias_v, detuning_hz). The reps loop sits between
            # them (cal04 pattern) so the flux offset is applied and settled ONCE per
            # flux point; identical coords still average on the cluster.
            with sub.loop(
                linspace(float(flux_v[0]), float(flux_v[-1]), flux_v.size, dtype=DType.AMPLITUDE)
            ) as flux:
                # 1. bias the qubit's own flux line for this point and let it settle
                sub.add(VoltageOffset(flux, 0, port=flux_port))
                sub.add(IdlePulse(1e-6))  # flux settling (cal04)
                with sub.loop(arange(0, reps, 1, DType.NUMBER)):
                    # 2. sweep the readout frequency across the detuning window
                    with sub.loop(
                        linspace(
                            center + float(detuning[0]),
                            center + float(detuning[-1]),
                            detuning.size,
                            dtype=DType.FREQUENCY,
                        )
                    ) as freq:
                        sub.add(
                            Measure(
                                qubit_name,
                                freq=freq,
                                coords={
                                    f"flux_{qubit_name}": flux,
                                    f"frequency_{qubit_name}": freq,
                                },
                                acq_channel=f"S_21_{qubit_name}",
                            )
                        )
                        sub.add(IdlePulse(10e-6))  # resonator decay (cal04)
            # SAFETY: flux line back to its idle value at the end of the subschedule
            sub.add(VoltageOffset(idle_flux, 0, port=flux_port))
            sub.add(IdlePulse(4e-9))
            schedule.add(sub)
        return schedule

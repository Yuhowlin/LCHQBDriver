"""Raw-vendor access for the probes — the one place that leaves the neutral surface.

Since the greenfield model a probe reads its NEUTRAL state through the channel
entity that owns the knob (``self.device.channel(target, "readout")``), which
serves the SCQO runtime value whether ``self.device`` is the Session's
RecordingDevice or a bare ``QbloxDeviceModel``. A few things a schedule needs
are vendor-only and have no neutral field at all — the element's ports
(``ports.flux``, ``ports.microwave``) and the vendor's flux sweet-spot slot — so
they come from the qblox ``DeviceElement`` itself, addressed through the roster
here.
"""

from __future__ import annotations

import math
from typing import Any


def vendor_element(experiment: Any, target: str, kind: str) -> Any:
    """The raw qblox ``DeviceElement`` behind ``target``'s DEFAULT channel of
    one kind.

    Entity names are resolved through the ROSTER, never by string arithmetic:
    ask for the default channel name, then address the vendor tree by that name
    (the core power_chain idiom — ``DeviceModel`` has no ``channel()``). Going
    through the channel KIND is also the capability guard: a target with no
    channel of that kind fails on a clear roster error here, instead of on a
    missing vendor port deep inside a schedule.
    """
    name = experiment.device.roster.default_channel(target, kind)
    return experiment.backend.device.component(name)._element


def idle_flux(element: Any) -> float:
    """The flux to measure at: the calibrated sweet spot when known, else 0 V.

    Vendor-only by necessity — the neutral standing-bias knob (``idle_flux`` on
    the flux channel) is Unrealized on this backend (backend/fieldmap.py), so
    the element's own ``flux_params.sweet_spot`` is the only source. Tolerates
    both scheduler API generations (legacy QCoDeS callables and pydantic-model
    plain attributes) and elements without ``flux_params``.
    """
    try:
        sweet = element.flux_params.sweet_spot
        sweet = float(sweet() if callable(sweet) else sweet)
    except (AttributeError, TypeError):
        return 0.0
    return sweet if math.isfinite(sweet) else 0.0

"""Every Qblox probe builds its Schedule against the greenfield device surface.

The cutover re-homed every probe's device READ from one per-qubit view onto the
CHANNEL ENTITY that owns the knob — ``self.device.channel(q, "readout")``
(``q1_ro``), ``...channel(q, "drive")`` (``q1_xy``) — plus the roster-resolved raw
element for the vendor-only bits (ports, the flux sweet spot). A stale field
spelling or a missing entity would otherwise surface only on hardware, so this
walks the WHOLE registered Qblox catalog and builds each probe once.

Offline: the real dut fixture + the minimal hw config, no cluster.
"""

from __future__ import annotations

import pytest

pytest.importorskip("qblox_scheduler")

from conftest import ROSTER_TOML, make_backend, make_experiment  # noqa: E402

import lchqb.experiments  # noqa: E402,F401  (import side effect: @register)
from scqo.experiments import catalog, get  # noqa: E402

#: every experiment whose registered class comes from THIS driver
QBLOX_PROBES = sorted(
    entry["name"] for entry in catalog()
    if get(entry["name"]).__module__.startswith("lchqb."))

#: keep the schedules small — this test is about the device surface, not physics
#: (the values still clear each Parameters' own minimums: >4 sweep points, >=100
#: shots; the per-shot loops are hardware loops, so the schedule stays tiny)
SMALL = {"num_points": 5, "num_freq_points": 5, "num_flux_points": 5,
         "num_power_points": 5, "num_averages": 2, "num_shots": 100}


def _params(cls):
    fields = set(cls.Parameters.model_fields)
    return cls.Parameters(targets=["q1"],
                          **{k: v for k, v in SMALL.items() if k in fields})


def test_the_whole_driver_catalog_is_covered():
    """The parametrization below is only worth as much as its list."""
    assert len(QBLOX_PROBES) == len(lchqb.experiments.__all__)


@pytest.mark.parametrize("name", QBLOX_PROBES)
def test_probe_builds_a_schedule(tmp_path, roster, name):
    cls = get(name)
    backend = make_backend(tmp_path, roster)
    exp = make_experiment(cls, backend, roster, _params(cls))
    # the two-tone probes play the drive chain's residual (spec_amp), which the
    # fixture leaves unseeded (NaN); the core run() solves it before probing
    exp.device.channel("q1", "drive").drive_power_dbm = -33.0
    exp.sweep_axes = exp.define_sweep()

    schedule = exp.probe()
    assert schedule.operations, f"{name}: empty schedule"


def test_flux_probe_refuses_a_target_with_no_flux_channel(tmp_path):
    """Reaching the flux port through the target's FLUX channel makes wiring the
    guard: a qubit with no flux line refuses in the roster, by name, instead of
    failing on a missing vendor port deep inside the schedule."""
    from scqo.roster import RosterError, parse_components

    from lchqb.experiments.resonator_spectroscopy_flux import (
        QbloxResonatorSpectroscopyFlux,
    )

    # same chip, but q2's flux wire was never installed
    roster = parse_components(ROSTER_TOML.replace('[lines.z2]\nflux = ["q2"]\n', ""))
    assert not roster.channels_of("q2") or "q2_z" not in roster.entities
    backend = make_backend(tmp_path, roster)
    exp = make_experiment(
        QbloxResonatorSpectroscopyFlux, backend, roster,
        _params(QbloxResonatorSpectroscopyFlux).model_copy(
            update={"targets": ["q2"]}),
    )
    exp.sweep_axes = exp.define_sweep()
    with pytest.raises(RosterError, match="no unique flux channel for 'q2'"):
        exp.probe()

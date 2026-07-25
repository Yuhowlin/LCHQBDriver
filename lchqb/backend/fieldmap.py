"""Declarative field catalog for the Qblox backend — PURE DATA, no vendor imports.

Keyed by CHANNEL KIND (``drive`` / ``readout`` / ``flux``) since the greenfield
model: knobs live on channel entities (``q1_xy``, ``q1_ro``, ``q1_z``), not on a
single per-qubit component. Per kind, one :class:`scqo.fieldmap.VendorBinding`
per realized KNOB (where it lives on the qblox_scheduler device tree, in what
unit, converted how — as a DESCRIPTION), one :class:`scqo.fieldmap.Unrealized`
per knob this backend cannot realize, plus the
:class:`scqo.fieldmap.VendorOnly` inventory of calibration-relevant knobs that
have no neutral counterpart yet. The EXECUTABLE conversions live in the three
channel views of ``qblox_backend.py`` (``QbloxDriveChannel`` /
``QbloxReadoutChannel`` / ``QbloxFluxChannel``) — this module documents them and
is pinned to the implementation by ``tests/test_scqo_glue.py``
(bindings | unrealized == scqo's KNOB fields per kind; imports stay vendor-free).

MONITORS are absent by construction: ``fidelity_g``/``fidelity_e``/``pos_*`` are
measured performance OF the current knobs, never pushed, so they need no vendor
binding and no Unrealized entry (the old ``readout_fidelity`` aggregate is gone;
the per-state pair replaces it). Facts (``flux_offset``, ``flux_per_phi0``,
``distortion_*``) live in physical.json and likewise bind nothing.

Rendered by ``scqo state --fields``; strings reach lab consoles, keep them ASCII.
"""

from __future__ import annotations

from scqo.fieldmap import Unrealized, VendorBinding, VendorOnly

FIELD_BINDINGS: dict[str, dict[str, VendorBinding]] = {
    "drive": {
        "drive_freq_hz": VendorBinding(
            path="element.clock_freqs.f01", unit="Hz"),
        "pi_amp": VendorBinding(
            path="element.rxy.amp180", unit=""),
        "pi_duration_s": VendorBinding(
            path="element.rxy.duration", unit="s",
            note="pi/x180 pulse length, seconds (chipA: 200 ns here vs 32 ns on "
                 "QM - genuinely per-chain calibrated). No 4 ns grid guard: the "
                 "portable-grid contract is the READOUT pulse/window pair, and "
                 "inventing one here would refuse values the scheduler accepts. "
                 "QM counterpart: xy.operations['x180'].length (ns)"),
        "drive_amp": VendorBinding(
            path="element.spec.spec_amp", unit="",
            note="the saturation (spec) drive amplitude - the CW VoltageOffset "
                 "fraction the qubit_spectroscopy probe plays, and the "
                 "drive_power_dbm chain solve's residual (lchqb.elements "
                 "LCHTransmonElement's spec submodule)"),
        "drive_power_dbm": VendorBinding(
            path='hardware_options.output_att["<mw-port>-<qubit>.01"] '
                 "+ element.spec.spec_amp",
            unit="dB + amp",
            convert="solve the DRIVE chain: largest EVEN output_att in [0, 60] keeping "
                    "spec_amp <= 0.5 against the nominal +5 dBm full scale; spec_amp "
                    "absorbs the exact residual (absolute power good to +/- a few dB)",
            coupled=("drive_amp",),
            note="the drive output_att is PORT-level and shared by every xy pulse: "
                 "while it is off its standing value the stored pi_amp means a "
                 "different power (qubit_spectroscopy sets it and reverts exactly); "
                 "EVEN integers 0-60 dB, hardware compilation config authoritative",
        ),
    },
    "readout": {
        "readout_freq_hz": VendorBinding(
            path="element.clock_freqs.readout", unit="Hz"),
        "readout_amp": VendorBinding(
            path="element.measure.pulse_amp", unit=""),
        "readout_power_dbm": VendorBinding(
            path='hardware_options.output_att["<ro-port>-<qubit>.ro"] '
                 "+ element.measure.pulse_amp",
            unit="dB + amp",
            convert="solve the output chain: largest EVEN output_att in [0, 60] keeping "
                    "pulse_amp <= 0.5 against the nominal +5 dBm full scale; pulse_amp "
                    "absorbs the exact residual (absolute power good to +/- a few dB)",
            coupled=("readout_amp",),
            note="output_att takes EVEN integers 0-60 dB (module validator); the "
                 "hardware compilation config is authoritative - recompiled and "
                 "re-pushed every run",
        ),
        "readout_duration_s": VendorBinding(
            path="element.measure.pulse_duration", unit="s",
            coupled=("readout_integration_s",),
            note="positive multiples of 4 ns only (the portable grid, from QM's "
                 "weights resolution; REFUSED otherwise, no silent rounding); "
                 "shrinking the pulse clamps integration_time down with it "
                 "(QM parity - its weights cannot span past the pulse)",
        ),
        "readout_integration_s": VendorBinding(
            path="element.measure.integration_time", unit="s",
            note="contract: <= readout_duration_s - the hardware here allows a "
                 "longer window but QM cannot realize one, so the portable "
                 "range stops at the pulse; multiples of 4 ns. QM counterpart: "
                 "zero-padded constant integration weights",
        ),
    },
    # The flux CHANNEL is realized (the probes play VoltageOffset on
    # element.ports.flux); its one KNOB is not - see UNREALIZED below. Declared
    # empty rather than omitted so the served-kind set is visible in one place.
    "flux": {},
}

#: Neutral KNOBS this backend cannot realize (declared, never silent): pushes are
#: skipped with the reason visible to doctor and the catalog view. The scqo
#: dataclass attribute is still spelled ``category``; it carries the channel KIND.
UNREALIZED: dict[str, dict[str, Unrealized]] = {
    "drive": {
        "drag_beta": Unrealized(
            "drive", "drag_beta",
            "no DRAG calibration wired for Qblox yet: rxy.beta exists (VENDOR_ONLY "
            "below) but no scqo experiment writes it here (the drag experiments are "
            "QM-only). Promote to a real rxy.beta binding when a Qblox DRAG "
            "experiment lands"),
    },
    "readout": {
        "readout_rotation_rad": Unrealized(
            "readout", "readout_rotation_rad",
            "no single_shot_readout wired for Qblox yet: acq_rotation exists "
            "(VENDOR_ONLY below, DEGREES) but no scqo experiment proposes it here. "
            "Promote to a real acq_rotation binding when a Qblox discriminator "
            "experiment lands"),
        "readout_threshold": Unrealized(
            "readout", "readout_threshold",
            "no single_shot_readout wired for Qblox yet: acq_threshold exists "
            "(VENDOR_ONLY below) but no scqo experiment proposes it here. Promote "
            "to a real acq_threshold binding when a Qblox discriminator experiment "
            "lands"),
        "readout_rus_threshold": Unrealized(
            "readout", "readout_rus_threshold",
            "no repeat-until-success on Qblox: no acq_rus knob exists (QM-only "
            "concept), so this field is never realized here"),
    },
    "flux": {
        "idle_flux": Unrealized(
            "flux", "idle_flux",
            "no standing-bias slot on the Qblox element: the flux port is driven "
            "per-schedule (VoltageOffset), and no DC source is wired into the "
            "hardware config yet; the setter lands with the first flux chip"),
    },
}

#: Backend-unique calibration knobs, vendor-owned and untracked by SCQO (edit in
#: dut_config.json / hw_config.json). Each entry carries its placement-rule kind
#: (scqo state --rule): realizer / candidate / vendor / unique. Doubles as the
#: neutral-field promotion backlog (the candidates pre-declare their convention).
VENDOR_ONLY: dict[str, VendorOnly] = {
    "readout_pulse_duration": VendorOnly(
        path="element.measure.pulse_duration", unit="s", kind="realizer",
        doc="readout pulse length - realizes the TRACKED readout_duration_s "
            "(a direct edit silently de-calibrates it; the governed write is "
            "scqo set QUBIT.readout_duration_s=...). QM counterpart: "
            "readout.length (ns)"),
    "readout_integration_time": VendorOnly(
        path="element.measure.integration_time", unit="s", kind="realizer",
        doc="acquisition integration window - realizes the TRACKED "
            "readout_integration_s (governed write: scqo set "
            "QUBIT.readout_integration_s=...; contract window <= pulse for QM "
            "portability). QM counterpart: the integration-weights support"),
    "readout_acq_delay": VendorOnly(
        path="element.measure.acq_delay", unit="s", kind="vendor",
        doc="delay from readout pulse start to acquisition start - aligns the "
            "instrument's receive path with its own transmit path (cable+"
            "electronics latency). The TOF measurement's product is written "
            "HERE, in SECONDS, offline - never a neutral field. QM counterpart: "
            "resonator.time_of_flight (ns)"),
    "reset_duration": VendorOnly(
        path="element.reset.duration", unit="s", kind="vendor",
        doc="passive reset / initialization wait between shots (IdlePulse "
            "length) - a policy value (should be >> T1, ~1/kappa), not a "
            "calibration outcome; per-run override exists "
            "(resonator_relaxation_time_ns). QM derives its wait as "
            "factor*T1 instead of an absolute time"),
    "readout_lo_freq": VendorOnly(
        path='hardware_options.modulation_frequencies["<ro-port>-<qubit>.ro"].lo_freq',
        unit="Hz", kind="vendor",
        doc="readout LO - PORT-level wiring shared by every element on that "
            "output; many LO/IF splits give the SAME RF, so SCQO owns only the "
            "RF (readout_freq_hz) and never moves the LO in a chain solve. Move "
            "it so IF = readout_freq_hz - lo_freq stays in the sequencer NCO "
            "range. Edit hw_config.json while NO session is live (a session's "
            "save() rewrites the file from memory) and restart kernels after. "
            "QM counterpart: opx_output.upconverter_frequency"),
    "drive_lo_freq": VendorOnly(
        path='hardware_options.modulation_frequencies["<mw-port>-<qubit>.01"].lo_freq',
        unit="Hz", kind="vendor",
        doc="drive LO - PORT-level, shared; keep IF = f01 - lo_freq in NCO range. "
            "Same no-live-session edit rule as readout_lo_freq"),
    "output_att": VendorOnly(
        path='hardware_options.output_att["<ro-port>-<qubit>.ro"]',
        unit="dB", kind="realizer",
        doc="the coarse readout power knob (EVEN integers 0-60) - it REALIZES "
            "the tracked readout_power_dbm (binding above). Change power with "
            "`scqo set QUBIT.readout_power_dbm=...` (solves the chain, keeps "
            "readout_amp coupled, recorded); a direct edit silently "
            "de-calibrates the absolute power, and any later readout_power_dbm "
            "write re-solves and overwrites a forced value. Same "
            "no-live-session edit rule as the LOs"),
    "drive_output_att": VendorOnly(
        path='hardware_options.output_att["<mw-port>-<qubit>.01"]',
        unit="dB", kind="realizer",
        doc="the coarse DRIVE power knob (EVEN integers 0-60, PORT-level - "
            "shared by every xy pulse) - it REALIZES the tracked "
            "drive_power_dbm (binding above). Change power with "
            "`scqo set QUBIT.drive_power_dbm=...` (solves the chain, keeps "
            "drive_amp coupled, recorded); a direct edit silently re-scales "
            "what every stored pi_amp AND the absolute drive power mean. "
            "QM counterpart: xy opx_output full_scale_power_dbm"),
    "x180_duration": VendorOnly(
        path="element.rxy.duration", unit="s", kind="realizer",
        doc="pi/x180 pulse length - it REALIZES the tracked pi_duration_s "
            "(promoted to a neutral drive knob in the greenfield catalog; "
            "binding above). The governed write is scqo set "
            "QUBIT.pi_duration_s=...; a direct edit silently de-calibrates the "
            "stored pi_amp with it. QM counterpart: "
            "xy.operations['x180'].length (ns)"),
    # NOTE: drag_beta is a neutral DRIVE knob (QM-realized). It is Unrealized on
    # Qblox for now (see UNREALIZED above) - element.rxy.beta is the vendor knob
    # that WOULD realize it; the binding lands when a Qblox DRAG experiment is
    # written. Kept out of VENDOR_ONLY to avoid colliding with the tracked name.
    "acq_threshold": VendorOnly(
        path="element.measure.acq_threshold", unit="", kind="realizer",
        doc="single-shot discrimination threshold in the rotated acquisition IQ "
            "frame - WOULD realize the tracked readout_threshold (Unrealized above "
            "until a Qblox single_shot_readout lands; then a real binding). "
            "Chain-dependent (input-chain gains + cable phase); invalidated by "
            "readout_input_att/input_gain edits. QM counterpart: readout threshold "
            "(demod units - different frame)"),
    "acq_rotation": VendorOnly(
        path="element.measure.acq_rotation", unit="deg", kind="realizer",
        doc="IQ rotation before thresholding (DEGREES here; QM "
            "integration_weights_angle is RADIANS) - WOULD realize the tracked "
            "readout_rotation_rad (Unrealized above until a Qblox "
            "single_shot_readout lands; the binding converts rad->deg). "
            "Acquisition-frame, chain-dependent; invalidated by input-chain edits"),
    "readout_input_att": VendorOnly(
        path='hardware_options.input_att["<ro-port>-<qubit>.ro"]',
        unit="dB", kind="vendor",
        doc="acquisition input attenuation (chipA: 10 dB; input_gain gain_I/"
            "gain_Q sit beside it) - edits silently invalidate every "
            "discrimination value (acq_threshold, acq_rotation) and all "
            "fidelity comparisons. QM counterpart: mw_input gain_db"),
    "reference_magnitude": VendorOnly(
        path="element.measure.reference_magnitude", unit="dBm/V/A", kind="unique",
        doc="hardware-referenced amplitude scaling of the measure pulse - no QM "
            "counterpart: an experiment depending on it runs ONLY on Qblox"),
}

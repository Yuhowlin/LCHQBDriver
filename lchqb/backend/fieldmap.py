"""Declarative field catalog for the Qblox backend — PURE DATA, no vendor imports.

Per category, one :class:`scqo.fieldmap.VendorBinding` per realized pushed
neutral field (where it lives on the qblox_scheduler device tree, in what unit,
converted how — as a DESCRIPTION), one :class:`scqo.fieldmap.Unrealized` per
pushed field this backend cannot realize, plus the
:class:`scqo.fieldmap.VendorOnly` inventory of calibration-relevant knobs that
have no neutral counterpart yet. The EXECUTABLE conversions live in
``QbloxReadableTransmon`` (qblox_backend.py) — this module documents them and is
pinned to the implementation by ``tests/test_scqo_glue.py``
(bindings | unrealized == scqo's pushed fields per category; imports stay
vendor-free).

Rendered by ``scqo state --fields``; strings reach lab consoles, keep them ASCII.
"""

from __future__ import annotations

from scqo.fieldmap import Unrealized, VendorBinding, VendorOnly

FIELD_BINDINGS: dict[str, dict[str, VendorBinding]] = {
    "ReadableTransmon": {
        "readout_freq": VendorBinding(
            path="element.clock_freqs.readout", unit="Hz"),
        "drive_freq": VendorBinding(
            path="element.clock_freqs.f01", unit="Hz"),
        "pi_amp": VendorBinding(
            path="element.rxy.amp180", unit=""),
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
}

#: Pushed neutral fields THIS backend cannot realize (declared, never silent):
#: pushes are skipped with the reason visible to doctor and the catalog view.
UNREALIZED: dict[str, dict[str, Unrealized]] = {
    "ReadableTransmon": {
        "idle_flux_v": Unrealized(
            "ReadableTransmon", "idle_flux_v",
            "no flux-tunable device yet; the setter lands with the first flux chip"),
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
            "RF (readout_freq) and never moves the LO in a chain solve. Move it "
            "so IF = readout_freq - lo_freq stays in the sequencer NCO range. "
            "Edit hw_config.json while NO session is live (a session's save() "
            "rewrites the file from memory) and restart kernels after. "
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
        unit="dB", kind="vendor",
        doc="the untracked DRIVE-chain scale that makes pi_amp portable=False "
            "(chipA: 18 dB) - no neutral drive_power_dbm twin exists (optional "
            "future engineering). Changing it silently re-scales what every "
            "stored pi_amp means. QM counterpart: xy opx_output "
            "full_scale_power_dbm"),
    "x180_duration": VendorOnly(
        path="element.rxy.duration", unit="s", kind="candidate",
        doc="pi/x180 pulse length - neutral pi_duration_s candidate (seconds; "
            "chipA: 200 ns here vs 32 ns on QM - genuinely per-chain "
            "calibrated). QM counterpart: xy.operations['x180'].length (ns)"),
    "drag_beta": VendorOnly(
        path="element.rxy.beta", unit="s", kind="candidate",
        doc="DRAG derivative scale of the pi pulse - neutral candidate with "
            "pre-declared convention: anharmonicity-normalized lambda bound to "
            "x180; the setter will derive beta from lambda and physical.json "
            "anharmonicity. QM counterpart: operations['x180_DragCosine'].alpha "
            "(dimensionless, per-gate - different math convention)"),
    "acq_threshold": VendorOnly(
        path="element.measure.acq_threshold", unit="", kind="vendor",
        doc="single-shot discrimination threshold in the rotated acquisition IQ "
            "frame - NO declarable reference plane (depends on input-chain "
            "gains and cable phase), never a neutral field. Portable traces: "
            "readout_fidelity (state) + confusion entries (run records). "
            "Invalidated by readout_input_att/input_gain edits. QM counterpart: "
            "readout threshold (demod VOLTS - different frame)"),
    "acq_rotation": VendorOnly(
        path="element.measure.acq_rotation", unit="deg", kind="vendor",
        doc="IQ rotation before thresholding (DEGREES here; QM "
            "integration_weights_angle is RADIANS) - acquisition-frame, "
            "chain-dependent; invalidated by input-chain edits"),
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

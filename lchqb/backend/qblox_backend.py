"""Qblox backend: maps the scqo abstractions onto qblox_scheduler.

``qblox_scheduler`` is imported lazily (inside methods) so that ``import lchqb`` works
without the Qblox stack installed, and so the simulated path never needs it.

Since the greenfield model a driver serves a view PER CHANNEL ENTITY, not per
qubit: the roster's ``q1_xy`` / ``q1_ro`` / ``q1_z`` each carry their own
function's knobs, and all three resolve onto the SAME qblox_scheduler
``DeviceElement`` (the channel's single target). ``QbloxDeviceModel.component``
does that resolution through the roster — never by parsing names.

Neutral-name mapping: declared ONCE in ``lchqb/backend/fieldmap.py`` (the catalog
``scqo state --fields`` renders; drift-tested per channel kind against scqo's knob
fields). The executable conversions are the three channel views below.
"""

from __future__ import annotations

import math
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import xarray as xr
from scqo.backend import Backend
from scqo.catalog import derived_op
from scqo.device import ComponentInfo, DeviceModel, EntityView, make_view_base
from scqo.entities import Channel
from scqo.fieldmap import Unrealized, VendorBinding, VendorOnly

from lchqb.backend.fieldmap import FIELD_BINDINGS, UNREALIZED, VENDOR_ONLY

if TYPE_CHECKING:
    from scqo.experiment import Experiment
    from scqo.roster import Roster

#: Nominal QRM-RF full-scale output (dBm) at pulse_amp=1.0, output_att=0 — the
#: datasheet maximum (+5 dBm into 50 Ohm). Frequency/LO/mixer-dependent in reality,
#: so absolute powers derived from it are good to ±a few dB; a per-setup
#: photon-number anchor (AC-Stark) is the Phase-3 refinement.
QBLOX_NOMINAL_FULL_SCALE_DBM = 5.0
#: The canonical digital operating point: keep the pulse amplitude <= 0.5 full
#: scale (shared by the readout AND drive chain solves).
_CANONICAL_MAX_AMP = 0.5


def _solve_att(name: str, target: float, what: str) -> tuple[int, float]:
    """Solve an output chain for an absolute port power: the largest EVEN
    attenuation in [0, 60] keeping the amplitude <= 0.5 (the module validator is
    Multiples(2), 0..60 — an odd value would only fail later, at instrument
    prepare); the amplitude absorbs the exact residual."""
    if target > QBLOX_NOMINAL_FULL_SCALE_DBM:
        raise ValueError(
            f"{name}: target {target} dBm exceeds the chain maximum "
            f"(+{QBLOX_NOMINAL_FULL_SCALE_DBM} dBm at amplitude 1, output_att=0)"
        )
    att_max = QBLOX_NOMINAL_FULL_SCALE_DBM - target + 20.0 * math.log10(_CANONICAL_MAX_AMP)
    att = int(min(60, max(0, 2 * math.floor(att_max / 2.0))))
    amp = 10.0 ** ((target - QBLOX_NOMINAL_FULL_SCALE_DBM + att) / 20.0)
    if amp > _CANONICAL_MAX_AMP:  # only when att=0 cannot absorb it (target > ~-1 dBm)
        warnings.warn(
            f"{name}: hitting {target} dBm needs {what}={amp:.3f} > "
            f"{_CANONICAL_MAX_AMP} (output_att already 0) — above the canonical "
            f"operating point"
        )
    return att, amp


def _read(owner: Any, name: str) -> float:
    """Read a scheduler parameter across API generations: the legacy QCoDeS style
    exposes a callable (``param()``), the pydantic-model style a plain attribute."""
    attr = getattr(owner, name)
    return float(attr() if callable(attr) else attr)


def _write(owner: Any, name: str, value: float) -> None:
    attr = getattr(owner, name)
    if callable(attr):
        attr(float(value))
    else:
        setattr(owner, name, float(value))


def _grid_s(value: float, what: str) -> float:
    """Validate a seconds duration as a positive multiple of 4 ns and return it
    re-derived from the integer grid (so both backends store the identical
    canonical float). 4 ns is the PORTABLE neutral contract — QM's
    pulse/integration-weights resolution; the scheduler itself is finer, but an
    off-grid value here would be unrealizable on the QM backend."""
    ns = float(value) * 1e9
    grid = round(ns)
    if abs(ns - grid) > 1e-3 or grid <= 0 or grid % 4:
        raise ValueError(
            f"{what}={value!r} s: must be a positive multiple of 4 ns (the "
            f"portable pulse/weights grid; no silent rounding)")
    # / 1e9 (exact), never * 1e-9: division rounds correctly, so the stored float
    # equals the parsed literal (2000 -> exactly 2e-6) on BOTH backends.
    return grid / 1e9


class _QbloxChannelView:
    """Shared plumbing of the three channel views.

    ``name`` is the ROSTER ENTITY name (``q1_ro``) — what scqo addresses and what
    every error message must cite; the VENDOR element name (``q1``) is
    ``_element.name`` and is what the port-clock keys are built from. The two were
    the same string in the pre-greenfield model, which is why the split matters.

    ``hw_agent`` (the backend's HardwareAgent) is needed only by the absolute-power
    knobs: an output attenuation lives in the hardware compilation config, one level
    above the element. Its ``hardware_configuration`` dict is the AUTHORITATIVE
    runtime surface — every ``run()`` recompiles from it and re-pushes
    ``out<n>_att`` to the module, so writes there survive; a direct qcodes ``.set()``
    would be overwritten.
    """

    def __init__(self, name: str, element: Any, hw_agent: Any = None) -> None:
        self.name = name
        self._element = element
        self._hw_agent = hw_agent

    @property
    def _qubit(self) -> str:
        """The vendor element name behind this channel (the port-clock key half)."""
        return self._element.name

    def _output_att(self, port_clock: str) -> int:
        """Current output attenuation (dB) of a line from the hardware config
        (missing key -> 0 dB, the instrument default)."""
        if self._hw_agent is None:
            raise RuntimeError(
                f"{self.name}: no HardwareAgent attached — output_att (and so the "
                f"absolute powers) needs the hardware compilation config"
            )
        opts = self._hw_agent.hardware_configuration.hardware_options
        att_map = getattr(opts, "output_att", None) or {}
        return int(att_map.get(port_clock, 0))

    def _write_output_att(self, port_clock: str, att: int) -> None:
        if self._hw_agent is None:
            raise RuntimeError(
                f"{self.name}: no HardwareAgent attached — cannot write output_att"
            )
        opts = self._hw_agent.hardware_configuration.hardware_options
        if opts.output_att is None:
            opts.output_att = {}
        opts.output_att[port_clock] = att  # authoritative: recompiled+pushed each run


class QbloxReadoutChannel(_QbloxChannelView, make_view_base("readout")):
    """The scqo READOUT channel view (``q1_ro``) over the target's ``DeviceElement``.

    Carries the dispersive-readout knobs: tone frequency, pulse amplitude/power,
    and the pulse/window pair. The discriminator knobs are Unrealized here
    (fieldmap.UNREALIZED); the monitors (fidelity_g/e, blob positions) are never
    pushed and so have no vendor surface at all.
    """

    @property
    def readout_freq_hz(self) -> float:
        return _read(self._element.clock_freqs, "readout")

    @readout_freq_hz.setter
    def readout_freq_hz(self, value: float) -> None:
        _write(self._element.clock_freqs, "readout", value)

    @property
    def readout_amp(self) -> float:
        return _read(self._element.measure, "pulse_amp")

    @readout_amp.setter
    def readout_amp(self, value: float) -> None:
        _write(self._element.measure, "pulse_amp", value)

    # ------------------------------------------- readout duration / window
    @property
    def readout_duration_s(self) -> float:
        return _read(self._element.measure, "pulse_duration")

    @readout_duration_s.setter
    def readout_duration_s(self, value: float) -> None:
        new_s = _grid_s(value, "readout_duration_s")
        _write(self._element.measure, "pulse_duration", new_s)
        # Portable contract (QM parity — its weights cannot span past the pulse):
        # the window never outlives the pulse, so a shrink clamps it down; the
        # scqo layer re-reads it and records the echo as a COUPLED change.
        if _read(self._element.measure, "integration_time") > new_s:
            _write(self._element.measure, "integration_time", new_s)

    @property
    def readout_integration_s(self) -> float:
        return _read(self._element.measure, "integration_time")

    @readout_integration_s.setter
    def readout_integration_s(self, value: float) -> None:
        new_s = _grid_s(value, "readout_integration_s")
        duration = _read(self._element.measure, "pulse_duration")
        if new_s > duration + 1e-12:
            raise ValueError(
                f"{self.name}: readout_integration_s={value!r} s exceeds the "
                f"readout pulse ({duration} s). The hardware here would allow "
                f"it, but QM cannot integrate past the pulse, so the portable "
                f"contract is window <= duration - raise readout_duration_s "
                f"first (or set both in one command; the pulse pushes first)")
        _write(self._element.measure, "integration_time", new_s)

    # ------------------------------------------------------------ absolute power
    def _port_clock(self) -> str:
        """The hardware-options key of this element's readout line, e.g. 'q1:res-q1.ro'."""
        port = getattr(self._element.ports, "readout")
        port = port() if callable(port) else port
        return f"{port}-{self._qubit}.ro"

    @property
    def readout_power_dbm(self) -> float:
        amp = _read(self._element.measure, "pulse_amp")
        if amp <= 0:  # log10 domain — the absolute power is undefined, not zero
            raise ValueError(
                f"{self.name}: readout pulse_amp is {amp} — absolute power undefined"
            )
        return (QBLOX_NOMINAL_FULL_SCALE_DBM - self._output_att(self._port_clock())
                + 20.0 * math.log10(amp))

    @readout_power_dbm.setter
    def readout_power_dbm(self, value: float) -> None:
        att, amp = _solve_att(self.name, float(value), "pulse_amp")
        self._write_output_att(self._port_clock(), att)
        _write(self._element.measure, "pulse_amp", amp)

    # ------------------------------------------------------- unrealized knobs
    # The readout discriminator (rotation/threshold/rus) is Unrealized on Qblox
    # (fieldmap.UNREALIZED): acq_rotation/acq_threshold exist but no scqo
    # single_shot_readout calibrates them here yet, and Qblox has no RUS. Concrete
    # raising pairs required (make_view_base declares an abstract property per knob
    # of the kind); promote to real acq_rotation/acq_threshold bindings when a
    # Qblox discriminator experiment lands.
    _DISCRIMINATOR_UNREALIZED = (
        "the readout discriminator is Unrealized on the Qblox backend: no "
        "single_shot_readout wired here yet (acq_rotation/acq_threshold exist; RUS "
        "has no Qblox counterpart)"
    )

    @property
    def readout_rotation_rad(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._DISCRIMINATOR_UNREALIZED}")

    @readout_rotation_rad.setter
    def readout_rotation_rad(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._DISCRIMINATOR_UNREALIZED}")

    @property
    def readout_threshold(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._DISCRIMINATOR_UNREALIZED}")

    @readout_threshold.setter
    def readout_threshold(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._DISCRIMINATOR_UNREALIZED}")

    @property
    def readout_rus_threshold(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._DISCRIMINATOR_UNREALIZED}")

    @readout_rus_threshold.setter
    def readout_rus_threshold(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._DISCRIMINATOR_UNREALIZED}")


class QbloxDriveChannel(_QbloxChannelView, make_view_base("drive")):
    """The scqo DRIVE channel view (``q1_xy``) over the target's ``DeviceElement``.

    Carries the xy knobs: drive frequency, the calibrated pi pulse (amplitude and
    length), and the saturation-drive pair behind the absolute drive power.
    """

    @property
    def drive_freq_hz(self) -> float:
        return _read(self._element.clock_freqs, "f01")

    @drive_freq_hz.setter
    def drive_freq_hz(self, value: float) -> None:
        _write(self._element.clock_freqs, "f01", value)

    @property
    def pi_amp(self) -> float:
        return _read(self._element.rxy, "amp180")

    @pi_amp.setter
    def pi_amp(self, value: float) -> None:
        _write(self._element.rxy, "amp180", value)

    @property
    def pi_duration_s(self) -> float:
        return _read(self._element.rxy, "duration")

    @pi_duration_s.setter
    def pi_duration_s(self, value: float) -> None:
        # No 4 ns grid guard: the portable pulse/weights grid is the READOUT
        # pulse/window contract (QM's integration weights); an x180 length is a
        # plain seconds value on both backends, and refusing off-grid ones here
        # would invent a contract the neutral catalog does not state.
        _write(self._element.rxy, "duration", value)

    # Lives on the element's IdlingReset submodule, not on a drive parameter:
    # the wait is the qubit's own relaxation, and the scheduler's Reset() gate
    # compiles to IdlePulse(reset.duration). The drive channel is the neutral
    # home because scqo knobs live on channels, never on modes. Both sides are
    # absolute seconds, so this is a pass-through with no conversion — the one
    # backend where the neutral field maps 1:1.
    @property
    def thermalization_time_s(self) -> float:
        return _read(self._element.reset, "duration")

    @thermalization_time_s.setter
    def thermalization_time_s(self, value: float) -> None:
        if not (float(value) > 0):
            raise ValueError(
                f"{self.name}: thermalization_time_s={value!r} s must be positive"
            )
        _write(self._element.reset, "duration", value)

    # ------------------------------------------------------------ absolute power
    # The drive twin, anchored to the stored SATURATION (spec) amplitude
    # (element.spec.spec_amp — the CW VoltageOffset the qubit_spectroscopy probe
    # plays). The drive output_att is PORT-level and shared by every xy pulse:
    # while it is off its standing value the stored pi_amp means a different
    # power (qubit_spectroscopy's run() sets and exactly reverts it; the even
    # discrete att + verbatim amplitude restore make the revert lossless).
    def _drive_port_clock(self) -> str:
        """The hardware-options key of this element's drive line, e.g. 'q1:mw-q1.01'."""
        port = getattr(self._element.ports, "microwave")
        port = port() if callable(port) else port
        return f"{port}-{self._qubit}.01"

    @property
    def drive_amp(self) -> float:
        amp = _read(self._element.spec, "spec_amp")
        if math.isnan(amp):
            raise ValueError(
                f"{self.name}: spec_amp is unset (NaN) — seed it (or set "
                f"drive_power_dbm, which writes it as the chain residual)"
            )
        return amp

    @drive_amp.setter
    def drive_amp(self, value: float) -> None:
        _write(self._element.spec, "spec_amp", value)

    @property
    def drive_power_dbm(self) -> float:
        amp = _read(self._element.spec, "spec_amp")
        # NaN would silently propagate through log10 into the config — refuse it
        # exactly like a zero/negative amplitude (power undefined, not a number).
        if not (amp > 0) or not math.isfinite(amp):
            raise ValueError(
                f"{self.name}: spec_amp is {amp} — absolute drive power undefined"
            )
        return (QBLOX_NOMINAL_FULL_SCALE_DBM - self._output_att(self._drive_port_clock())
                + 20.0 * math.log10(amp))

    @drive_power_dbm.setter
    def drive_power_dbm(self, value: float) -> None:
        att, amp = _solve_att(self.name, float(value), "spec_amp")
        self._write_output_att(self._drive_port_clock(), att)
        _write(self._element.spec, "spec_amp", amp)

    # ------------------------------------------------------- unrealized knobs
    # drag_beta is Unrealized on Qblox (fieldmap.UNREALIZED): rxy.beta exists but
    # no scqo experiment calibrates it here yet. Concrete raising pair required
    # because make_view_base declares the abstract property for every knob.
    _DRAG_BETA_UNREALIZED = (
        "drag_beta is Unrealized on the Qblox backend: no DRAG calibration wired "
        "here yet (the drag experiments are QM-only)"
    )

    @property
    def drag_beta(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._DRAG_BETA_UNREALIZED}")

    @drag_beta.setter
    def drag_beta(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._DRAG_BETA_UNREALIZED}")


class QbloxFluxChannel(_QbloxChannelView, make_view_base("flux")):
    """The scqo FLUX channel view (``q1_z``) over the target's ``DeviceElement``.

    The flux LINE is realized — the probes play ``VoltageOffset`` on
    ``element.ports.flux`` — but the STANDING bias knob is not: nothing in the
    Qblox element or hardware config holds a DC set-point (see
    fieldmap.UNREALIZED). The transfer-function FACTS (flux_offset,
    flux_per_phi0) are physical.json content and never push, so this view carries
    exactly one raising knob pair.
    """

    _IDLE_FLUX_UNREALIZED = (
        "idle_flux is Unrealized on the Qblox backend: the flux port is driven "
        "per-schedule (VoltageOffset) and no standing DC source is wired into the "
        "hardware config; the setter lands with the first flux chip"
    )

    @property
    def idle_flux(self) -> float:
        raise NotImplementedError(f"{self.name}: {self._IDLE_FLUX_UNREALIZED}")

    @idle_flux.setter
    def idle_flux(self, value: float) -> None:
        raise NotImplementedError(f"{self.name}: {self._IDLE_FLUX_UNREALIZED}")


#: channel kind -> the view class this backend serves for it. A kind absent here
#: (``pump``) and every non-channel entity (modes, lines, composites) is a KeyError
#: from ``component()`` — the contract scqo degrades gracefully against.
_CHANNEL_VIEWS: dict[str, type[_QbloxChannelView]] = {
    "drive": QbloxDriveChannel,
    "readout": QbloxReadoutChannel,
    "flux": QbloxFluxChannel,
}


def _read_or_none(view: EntityView, field: str) -> float | None:
    """Read a neutral knob, returning None if this element doesn't carry it.

    ValueError covers readout_power_dbm on a zero/unset pulse_amp; RuntimeError
    covers a device model constructed without a HardwareAgent (no hardware config
    to read the attenuation from) — and NotImplementedError, the Unrealized
    knobs' signal, is a RuntimeError subclass."""
    try:
        return getattr(view, field)
    except (TypeError, AttributeError, KeyError, ValueError, RuntimeError):
        return None


def _derived_operations(roster: "Roster", channel: Channel) -> tuple[str, ...]:
    """The single-mode operation this channel derives on its target — read from
    scqo's (channel kind x target kind) table, never declared here."""
    target = roster.entities.get(channel.target[0])
    if target is None:
        return ()
    try:
        op = derived_op(channel.kind, target.kind)
    except KeyError:
        return ()
    return (op,) if op else ()


class QbloxDeviceModel(DeviceModel):
    """Wraps a qblox_scheduler ``QuantumDevice`` (+ optionally its HardwareAgent).

    Entity names are ROSTER names: ``component("q1_ro")`` resolves the channel
    entity through the roster, takes its KIND and its single TARGET, fetches the
    vendor element for that target, and returns the matching channel view. The
    roster is therefore not optional — without it the driver cannot tell what
    ``q1_ro`` means.

    The agent reference (and its hardware config file path) enables the
    ``*_power_dbm`` surfaces — an output attenuation lives in the hardware
    compilation config, not on the element.
    """

    def __init__(self, quantum_device: Any, roster: "Roster",
                 config_file: str | None = None,
                 hw_agent: Any = None, hw_config_file: str | None = None) -> None:
        self._qd = quantum_device
        self._roster = roster
        self._config_file = config_file
        self._hw_agent = hw_agent
        self._hw_config_file = hw_config_file

    @property
    def roster(self) -> "Roster":
        """The device's authority on which entities exist (read-only)."""
        return self._roster

    def component(self, name: str) -> EntityView:
        """The view for one vendor-realized entity, addressed by ROSTER name.

        KeyError for everything this backend does not realize — an unknown name,
        a mode/line/composite (Qblox exposes no gate-macro surface), a pump or
        multi-target channel, and a channel whose target has no element in the
        dut config. That is the contract: scqo degrades gracefully and the doctor
        reports the gap against ``components()``.
        """
        e = self._roster.entities.get(name)
        if e is None:
            raise KeyError(
                f"unknown entity {name!r} — not in this device's roster")
        if not isinstance(e, Channel):
            channels = [c.name for c in self._roster.channels_of(name)]
            raise KeyError(
                f"{name!r} is a {type(e).__name__.lower()}; the Qblox backend "
                f"serves channel entities only (knobs live on channels) — "
                f"address {channels or '(none wired)'}")
        view_cls = _CHANNEL_VIEWS.get(e.kind)
        if view_cls is None:
            raise KeyError(
                f"{name!r} is a {e.kind} channel — the Qblox backend realizes "
                f"{sorted(_CHANNEL_VIEWS)} channels only")
        if len(e.target) != 1:
            raise KeyError(
                f"{name!r} is a multi-target {e.kind} channel {e.target} — the "
                f"Qblox backend serves one element per channel")
        try:
            element = self._qd.get_element(e.target[0])
        except KeyError:
            raise KeyError(
                f"{name!r} targets {e.target[0]!r}, which is not an element of "
                f"the loaded dut config (elements: {sorted(self._qd.elements)})"
            ) from None
        return view_cls(name, element, hw_agent=self._hw_agent)

    def components(self) -> dict[str, ComponentInfo]:
        """Derived inventory (the doctor's WITNESS, never truth): every roster
        channel this backend actually serves a view for, with the kind it serves
        it AS — ``vendor_checks`` FAILS on a kind disagreement, so this reports
        the channel's kind, not an element type (element_type cannot distinguish
        a coupler from a qubit; the roster arbitrates). Composites are absent:
        no Qblox gate-macro surface exists yet.
        """
        elements = set(self._qd.elements)
        out: dict[str, ComponentInfo] = {}
        for name, ch in self._roster.channels().items():
            if ch.kind not in _CHANNEL_VIEWS or len(ch.target) != 1:
                continue
            if ch.target[0] not in elements:
                continue
            out[name] = ComponentInfo(
                kind=ch.kind, target=tuple(ch.target), line=ch.line,
                operations=_derived_operations(self._roster, ch))
        return out

    def save(self) -> None:
        # Write back to the EXACT files the device was loaded from. (to_json_file
        # writes <device_name>.json, which silently diverges from the dut_config.json
        # the backend loads — calibrations would be stale after a restart.)
        hw = self._hw_agent.hardware_configuration if self._hw_agent is not None else None
        if hw is not None:
            # The separate hw_config.json is the RUNTIME truth (connect_clusters
            # overwrites qd.hardware_config from it on every run); keep the copy
            # embedded in dut_config.json in step BEFORE serializing the quantum
            # device, so the two files can never drift through a save.
            self._qd.hardware_config = hw
            if self._hw_config_file is not None:
                with open(self._hw_config_file, "w", encoding="utf-8") as f:
                    # exclude_none is LOAD-BEARING: pydantic's default dump writes
                    # every unset Optional as an explicit null, and the qblox
                    # compiler treats an explicitly-null channel description as
                    # "user set None" (it lands in model_fields_set on reload) and
                    # crashes sequencer compilation — whereas an ABSENT key gets a
                    # default ChannelDescription. Never write nulls.
                    f.write(hw.model_dump_json(indent=2, exclude_none=True))
        if self._config_file is not None:
            with open(self._config_file, "w", encoding="utf-8") as f:
                f.write(self._qd.to_json())
            if hw is not None:
                # to_json has no exclude_none switch, so it re-embeds the hardware
                # config WITH explicit nulls (the crash trigger above). Rewrite that
                # one block from the SAME clean dump hw_config.json got — the two
                # files then carry identical config content and no nulls survive.
                import json as _json

                data = _json.loads(Path(self._config_file).read_text(encoding="utf-8"))
                if "hardware_config" in data:
                    data["hardware_config"] = _json.loads(hw.model_dump_json(exclude_none=True))
                    Path(self._config_file).write_text(_json.dumps(data, indent=4),
                                                       encoding="utf-8")

    def snapshot(self) -> dict:
        """``{entity: {knob: value}}`` over the channel entities this backend
        realizes, reporting only the knobs the fieldmap declares BOUND (the
        Unrealized ones have no vendor value to seed from). None for a knob a
        given element cannot answer — a real lab device tree carries elements
        without a spec slot, and provenance must never crash a session."""
        state: dict[str, dict] = {}
        for name, ch in self._roster.channels().items():
            try:
                view = self.component(name)
            except KeyError:
                continue  # not realized here: absent from the snapshot entirely
            state[name] = {
                field: _read_or_none(view, field)
                for field in FIELD_BINDINGS.get(ch.kind, {})
            }
        return state


class QbloxBackend(Backend):
    """scqo Backend over a Qblox cluster (or dummy connections for dry runs)."""

    def __init__(self, hardware_config: str, device_config: str,
                 output_dir: str | None = None, *, roster: "Roster") -> None:
        # Lazy import keeps `import lchqb` free of qblox_scheduler. The elements import
        # registers the lab's custom element types (FluxTunableTransmonElement) so the
        # dut config can be deserialized.
        import lchqb.elements  # noqa: F401
        from qblox_scheduler import HardwareAgent

        self._roster = roster
        self._hw_agent = HardwareAgent(
            hardware_configuration=hardware_config,
            quantum_device_configuration=device_config,
            output_dir=output_dir,
        )
        # HardwareAgent parses a config PATH into a plain dict; the validated model
        # only appears once connect_clusters runs. Validate it NOW (the very call
        # connect_clusters makes) so the hardware config is readable/writable with
        # no cluster attached — readout_power_dbm and save() need it. A later
        # connect_clusters re-validates the same object harmlessly.
        import json as _json

        from qblox_scheduler.backends.qblox_backend import QbloxHardwareCompilationConfig

        validated = QbloxHardwareCompilationConfig.model_validate(
            self._hw_agent._hardware_configuration
        )
        # NORMALIZE through an exclude_none round-trip: a file carrying explicit
        # nulls (e.g. one written by a pre-fix save(), or the QBLOX_training
        # placeholder dumps) marks those fields as SET-to-None, and the compiler's
        # channel-description lookup then passes None into the sequencer config and
        # crashes. Dropping the nulls here takes them OUT of model_fields_set, so
        # poisoned configs load, compile, and self-heal on the next save().
        self._hw_agent._hardware_configuration = QbloxHardwareCompilationConfig.model_validate(
            _json.loads(validated.model_dump_json(exclude_none=True))
        )
        self._device = QbloxDeviceModel(
            self._hw_agent.quantum_device,
            roster,
            config_file=device_config,
            hw_agent=self._hw_agent,
            hw_config_file=hardware_config,
        )

    @classmethod
    def load(cls, config_dir: str = "./qblox_state", output_dir: str | None = None,
             *, roster: "Roster") -> "QbloxBackend":
        """Construct from the repo's standard config locations."""
        return cls(
            hardware_config=f"{config_dir}/hw_config.json",
            device_config=f"{config_dir}/dut_config.json",
            output_dir=output_dir,
            roster=roster,
        )

    @property
    def device(self) -> QbloxDeviceModel:
        return self._device

    @property
    def roster(self) -> "Roster":
        """The device roster this backend was built against."""
        return self._roster

    def field_bindings(self) -> dict[str, dict[str, VendorBinding]]:
        """The declared per-CHANNEL-KIND neutral-knob catalog (lchqb.backend.fieldmap)
        — the conversion CODE is the channel views above; this is its description."""
        return {kind: dict(bindings) for kind, bindings in FIELD_BINDINGS.items()}

    def unrealized(self) -> dict[str, dict[str, Unrealized]]:
        """Knobs this backend cannot realize, per channel kind (see fieldmap)."""
        return {kind: dict(entries) for kind, entries in UNREALIZED.items()}

    def vendor_only(self) -> dict[str, VendorOnly]:
        """Qblox-unique calibration knobs, vendor-owned (see fieldmap)."""
        return dict(VENDOR_ONLY)

    def _default_view(self, target: str, kind: str) -> EntityView | None:
        """The target's DEFAULT channel view of one kind, or None when the roster
        or the vendor tree cannot serve it (provenance must never fail a run)."""
        try:
            return self._device.component(
                self._roster.default_channel(target, kind))
        except Exception:
            return None

    def power_context(self, qubits: list[str]) -> dict:
        """Raw readout + drive chain values per qubit (run-record provenance only).

        Addressed by MODE name (``params.targets``): each target's default readout
        and drive channels are resolved through the roster, so the two blocks stay
        independent — an element without a spec slot still reports its readout chain.
        """
        out: dict = {}
        for name in qubits:
            out[name] = {}
            view = self._default_view(name, "readout")
            try:
                out[name] = {
                    "output_att_db": view._output_att(view._port_clock()),
                    "pulse_amp": _read(view._element.measure, "pulse_amp"),
                    "nominal_full_scale_dbm": QBLOX_NOMINAL_FULL_SCALE_DBM,
                    "readout_power_dbm": view.readout_power_dbm,
                    "note": "power derived from the nominal +5 dBm full scale "
                            "(frequency-dependent, ±a few dB)",
                }
                # The readout LO the data was taken at: a hand-edited lo_freq is
                # otherwise invisible in provenance (readout_freq_hz alone cannot
                # explain a jump across the IF window). Only when configured — a
                # missing entry must not degrade the rest of the context.
                opts = self._hw_agent.hardware_configuration.hardware_options
                mf = getattr(opts, "modulation_frequencies", None) or {}
                lo = getattr(mf.get(view._port_clock()), "lo_freq", None)
                if lo is not None:
                    out[name]["readout_lo_freq_hz"] = float(lo)
            except Exception:  # provenance must never fail a run
                out[name] = {}
            # The drive chain behind drive_power_dbm — same never-fail rule, and
            # independent of the readout block.
            try:
                view = self._default_view(name, "drive")
                out[name].update({
                    "drive_output_att_db": view._output_att(view._drive_port_clock()),
                    "spec_amp": _read(view._element.spec, "spec_amp"),
                    "drive_power_dbm": view.drive_power_dbm,
                })
                opts = self._hw_agent.hardware_configuration.hardware_options
                mf = getattr(opts, "modulation_frequencies", None) or {}
                lo = getattr(mf.get(view._drive_port_clock()), "lo_freq", None)
                if lo is not None:
                    out[name]["drive_lo_freq_hz"] = float(lo)
            except Exception:  # provenance must never fail a run
                pass
        return out

    def _drive_views(self, targets: list[str]) -> dict[str, Any]:
        """Every run target's DEFAULT drive view, keyed by channel name.

        A composite target (a pair) has no drive channel of its own, so it
        expands to its MEMBER modes' drive channels — the entities the reset
        actually happens on. Roster-resolved; never string arithmetic."""
        from scqo.entities import Composite

        views: dict[str, Any] = {}
        for target in targets:
            entity = self._roster.entities.get(target)
            modes = [target]
            if isinstance(entity, Composite):
                modes = [m for names in entity.roles.values() for m in names]
            for mode in modes:
                try:
                    name = self._roster.default_channel(mode, "drive")
                except Exception:
                    continue
                if name not in views:
                    views[name] = self.device.component(name)
        return views

    @contextmanager
    def _thermalization_override(self, experiment: "Experiment"):
        """Per-run override of the thermal-reset wait: recorded set -> run ->
        exact revert.

        The STANDING wait already lives in the dut config (scqo pushes the
        neutral ``thermalization_time_s`` knob onto ``element.reset.duration``),
        so ``Reset()`` needs no argument and no probe changes. Only an explicit
        per-run override acts — and unlike QM, where the wait is baked in at
        program-BUILD time, the scheduler expands ``Reset`` into
        ``IdlePulse(reset.duration)`` during COMPILATION, which happens inside
        ``run()``. So this must bracket the whole acquire, not just probe().

        Writes go straight to the vendor tree, NOT through the recording
        device: a per-run override must leave no ChangeRecord and no store row."""
        override_ns = getattr(experiment.params, "thermalization_time_ns", None)
        if override_ns is None:
            yield
            return
        views = self._drive_views(list(experiment.params.targets))
        if not views:
            raise RuntimeError(
                f"thermalization_time_ns={override_ns} was set but no drive "
                f"channel resolved for targets {list(experiment.params.targets)} "
                f"— refusing to run with the override silently ignored")
        previous = {n: v.thermalization_time_s for n, v in views.items()}
        for view in views.values():
            view.thermalization_time_s = float(override_ns) / 1e9
        try:
            yield
        finally:
            for name, view in views.items():
                view.thermalization_time_s = previous[name]

    def acquire(self, experiment: "Experiment") -> xr.Dataset:
        with self._thermalization_override(experiment):
            schedule = experiment.probe()  # native qblox_scheduler.Schedule
            raw = self._hw_agent.run(schedule, timeout=120)
        return self._to_canonical(raw, experiment)

    @staticmethod
    def _to_canonical(raw: xr.Dataset, experiment: "Experiment") -> xr.Dataset:
        """Relabel a raw Qblox dataset into scqo's convention: dims (target, <sweep>), vars I/Q.

        The probes label every acquisition ``acq_channel=f"S_21_{qubit}"`` with the
        sweep loop variable as a per-point coordinate (cal02 reference pattern), so
        the hardware returns one complex S21 array per qubit over the swept axis
        (repetitions averaged on the cluster). The canonical sweep values come from
        ``experiment.sweep_axes`` — the probe built its loop from exactly those.
        On a structure mismatch the raw dataset is pickled for offline inspection.
        """
        import numpy as np

        qubits = list(experiment.params.targets)  # type: ignore[attr-defined]
        axes = {name: np.asarray(values) for name, values in experiment.sweep_axes.items()}
        shape = tuple(len(v) for v in axes.values())
        try:
            i_rows, q_rows = [], []
            for name in qubits:
                key = f"S_21_{name}"
                if key not in raw.data_vars:
                    raise KeyError(
                        f"acquisition channel {key!r} not in raw dataset "
                        f"(data_vars={list(raw.data_vars)}) — probe/hardware mismatch"
                    )
                values = np.asarray(raw[key].values).squeeze()
                if values.shape != shape:
                    if values.ndim == len(shape) and values.shape == tuple(reversed(shape)):
                        values = values.T  # labeled axes returned in reversed order
                    elif values.size == int(np.prod(shape)):
                        # flat bin order follows the probe's loop nesting (outer axis
                        # first), which matches sweep_axes insertion order
                        values = values.reshape(shape)
                    else:
                        raise ValueError(
                            f"{key}: expected shape {shape} for axes {list(axes)}, "
                            f"got {values.shape} (dims={dict(raw.sizes)})"
                        )
                i_rows.append(values.real)
                q_rows.append(values.imag)
        except (KeyError, ValueError) as err:
            raise type(err)(f"{err}; {_dump_raw(raw)}") from err
        dims = ("target", *axes.keys())
        return xr.Dataset(
            {"I": (dims, np.stack(i_rows)), "Q": (dims, np.stack(q_rows))},
            coords={"target": qubits, **axes},
        )


def _dump_raw(raw: xr.Dataset) -> str:
    """Pickle the raw hardware dataset for offline inspection (netCDF can't hold the
    complex S21 data); a failed bring-up run is never wasted."""
    import pickle
    import tempfile
    from datetime import datetime
    from pathlib import Path

    dump = Path(tempfile.gettempdir()) / f"qblox_raw_{datetime.now():%Y%m%d-%H%M%S}.pkl"
    try:
        with open(dump, "wb") as f:
            pickle.dump(raw, f)
        return f"raw dataset pickled to {dump}"
    except Exception as err:
        return f"raw dataset could not be pickled ({type(err).__name__}: {err})"

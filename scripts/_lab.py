"""Deprecated shim — the engine moved into scqo v0.4.0 (scqo.cli).

Kept so `from _lab import build_session, default_qubits` (ai_loop_demo.py,
run_resonator_spectroscopy.py, personal notebooks) keeps working. The backend
itself is discovered via the `scqo.backends` entry point this repo registers.
"""

from scqo.cli import build_session, default_qubits  # noqa: F401

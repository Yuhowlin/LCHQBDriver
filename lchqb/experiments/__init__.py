"""Importing this package registers every Qblox experiment into the scqo catalog.

Add a line here for each new experiment module so its ``@register`` runs.
"""

from . import qubit_power_rabi  # noqa: F401  (import side effect: @register)
from . import qubit_ramsey  # noqa: F401  (import side effect: @register)
from . import resonator_spectroscopy  # noqa: F401  (import side effect: @register)

__all__ = ["resonator_spectroscopy", "qubit_ramsey", "qubit_power_rabi"]

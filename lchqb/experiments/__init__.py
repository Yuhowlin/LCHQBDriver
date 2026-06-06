"""Importing this package registers every Qblox experiment into the scqo catalog.

Add a line here for each new experiment module so its ``@register`` runs.
"""

from . import power_rabi  # noqa: F401  (import side effect: @register)
from . import ramsey  # noqa: F401  (import side effect: @register)
from . import resonator_spectroscopy  # noqa: F401  (import side effect: @register)

__all__ = ["resonator_spectroscopy", "ramsey", "power_rabi"]

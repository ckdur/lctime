# SPDX-FileCopyrightText: 2024 Thomas Kramer <code@tkramer.ch>
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Measurement of the input capacitance by driving the input pin with a constant current.
"""

from .util import *
from .piece_wise_linear import *
from .ngspice_subprocess import run_simulation
from ..lccommon.net_util import get_subcircuit_ports

import logging
from typing import Dict
from itertools import product
from scipy import interpolate

logger = logging.getLogger(__name__)


def characterize_leakage_power(
        input_pins: List[str],
        internal_state_nodes: List[str],
        cell_conf: CellConfig
) -> Dict[str, float]:
    pass

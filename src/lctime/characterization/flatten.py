# SPDX-FileCopyrightText: 2025 Thomas Kramer <code@tkramer.ch>
# SPDX-License-Identifier: AGPL-3.0-or-later

from .util import CellConfig, CharacterizationConfig
from .ngspice_subprocess import run_simulation
from ..lccommon.net_util import get_subcircuit_ports

from typing import List
import os
import logging

logger = logging.getLogger(__name__)

def flatten_circuit(
    cell_name: str,
    spice_netlist_file: str,
    setup_statements: List[str],
    workingdir: str,
) -> str:
    """
    Flatten a SPICE circuit using ngspice.
    This is used to resolve transistors which are wrapped in subcircuits.

    Returns a flatened SPICE subcircuit.
    """

    logger.debug("flatten netlist with ngspice")
    
    # Create a list of include files.
    setup_statements = setup_statements + [f".include {spice_netlist_file}"]
    
    ports = get_subcircuit_ports(spice_netlist_file, cell_name)

    # Load include files.
    for setup in setup_statements:
        logger.debug(f"Setup statement: {setup}")
    setup_statements_string = "\n".join(setup_statements)

    # Simulation script file path.
    file_name = f"lctime_flatten_{cell_name}"
    sim_file = os.path.join(workingdir, f"{file_name}.sp")

    # Create ngspice simulation script.
    sim_netlist = f"""* librecell {__name__}
.title Flatten circuit

.control
* Exit on error with return value 1
pre_set strict_errorhandling
.endc

{setup_statements_string}

Xcell {" ".join(ports)} {cell_name}

.control

set filetype=ascii
set wr_vecnames

listing r
exit
.endc

.end
"""

    # Dump netlist.
    logger.debug(sim_netlist)

    # Dump simulation script to the file.
    # logger.debug(f"Write simulation netlist: {sim_file}")
    open(sim_file, "w").write(sim_netlist)

    # Run simulation.
    stdout, stderr = run_simulation(sim_file)

    flattened = [f'.subckt {cell_name} {" ".join(ports)}']
    # Fetch flat netlist.
    for line in stdout.split("\n"):
        if line.startswith("m.xcell"):
            # Drop parameters of transistor.
            t = line.split()
            flattened.append(" ".join(t[:6]))
        if line.startswith("r.xcell"):
            flattened.append(line)
    flattened.append(".ends")


    return "\n".join(flattened)


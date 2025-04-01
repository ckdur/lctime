# Copyright (c) 2019-2020 Thomas Kramer.
# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Measurement of the input capacitance by driving the input pin with a constant current.
"""

import os

from itertools import product
from collections import Counter

from .util import *
from .piece_wise_linear import *
from .ngspice_subprocess import CellSimulation, NgSpiceInteractive
import logging
from typing import Dict

from scipy import interpolate

logger = logging.getLogger(__name__)


def characterize_input_capacitances(
        simulator: NgSpiceInteractive,
        input_pins: List[str],
        active_pin: str,
        output_pins: List[str],
        cell_conf: CellConfig
) -> Dict[str, float]:
    """
    Estimate the input capacitance of the `active_pin`.
    The estimation is done by simulating a constant current flowing into an input and measuring the
    time it takes for the input to go from high to low or low to high. This time multiplied by the current
    yields the transported charge which together with the voltage difference tells the capacitance.
    The measurement is done for all combinations of static inputs (all other inputs that are not measured).

    :param input_pins: List of all input pin names.
    :param active_pin: Name of the pin to be measured.
    :param output_pins: List of cell output pins.
    :param config: Parameters for the characterization.

    :returns: Dictionary containing input capacitances for rise, fall and average case.
    """

    assert isinstance(cell_conf, CellConfig)
    assert isinstance(cell_conf.global_conf, CharacterizationConfig)

    # Check for duplicated pins
    def duplicates(items: List) -> List:
        counted = Counter(items)
        return [i for i, c in counted.items() if c > 1]

    assert not duplicates(input_pins), f"Duplicated input pins: {duplicates(input_pins)}"
    assert not duplicates(output_pins), f"Duplicated output pins: {duplicates(output_pins)}"
    
    cfg = cell_conf.global_conf

    inputs_inverted = cell_conf.complementary_pins.values()
    assert active_pin not in inputs_inverted, f"Active pin '{active_pin}' must not be an inverted pin of a differential pair."
    input_pins_non_inverted = [p for p in input_pins if p not in inputs_inverted]
    active_pin_inverted = cell_conf.complementary_pins.get(active_pin)

    logger.debug("characterize_input_capacitances()")
    # Find ports of the SPICE netlist.
    ports = cell_conf.spice_ports
    logger.debug("Subcircuit ports: {}".format(", ".join(ports)))

    logger.debug("Ground net: {}".format(cell_conf.ground_net))
    logger.debug("Supply net: {}".format(cell_conf.supply_net))

    vdd = cfg.supply_voltage
    logger.debug("Vdd: {} V".format(vdd))

    # Create a list of include files.
    setup_statements = cfg.setup_statements + [f".include {cell_conf.spice_netlist_file}"]

    # Load include files.
    for setup in setup_statements:
        logger.debug(f"Setup statement: {setup}")
    setup_statements_string = "\n".join(setup_statements)

    # Add output load capacitance. Right now this is 1fF.
    output_load_statements = "\n".join((f"Cload_{p} {p} {cell_conf.ground_net} 1f" for p in output_pins))
        
    # Choose a maximum time to run the simulation.
    time_max = cfg.time_step * 1e6

    # Find function to summarize different timing arcs.
    reduction_function = {
        CalcMode.WORST: max,
        CalcMode.BEST: min,
        CalcMode.TYPICAL: np.mean
    }[cfg.timing_corner]
    logger.debug("Reduction function for summarizing multiple timing arcs: {}".format(reduction_function.__name__))

    logger.debug("Measuring input capacitance.")

    # If the ground net is not called GND, then it must be connected to GND or 0.
    # This seems to be a must for SPICE simulators.
    # See: https://codeberg.org/librecell/lctime/issues/12#issuecomment-2173526
    if cell_conf.ground_net not in ["GND", "gnd", "0"]:
        logger.debug(f"Connect ground net `{cell_conf.ground_net}` to simulators ground `0`.")
        ground_connection = f"* Connect ground net to GND\n" \
        f"vgnd {cell_conf.ground_net} 0 0"
    else:
        # Using standard name for ground net.
        ground_connection = ""


    # Generate all possible input combinations for the static input pins.
    static_input_nets = [i for i in input_pins_non_inverted if i != active_pin]
    num_inputs = len(static_input_nets)

    static_inputs = list(product(*([[0, 1]] * num_inputs)))
    logger.debug(f"Number of static input combinations: {len(static_inputs)}")

    input_current = cfg.input_current_for_capacitance_measurement
    logger.debug("Input current: {}".format(input_current))

    simulator.reset()

    input_voltages = dict()
    input_currents = dict()

    for pin in input_pins:
        if pin != active_pin:
            input_voltages[pin] = 0.0
    input_currents[active_pin] = 0.0
    if active_pin_inverted:
        input_current[active_pin_inverted] = 0.0
            
    input_voltages[cell_conf.supply_net] = cell_conf.global_conf.supply_voltage
    if cell_conf.pwell_pin:
        input_voltages[cell_conf.pwell_pin] = 0.0
    if cell_conf.nwell_pin:
        input_voltages[cell_conf.nwell_pin] = cell_conf.global_conf.supply_voltage
    # Create a list of include files.
    setup_statements = cell_conf.global_conf.setup_statements + [f".include {cell_conf.spice_netlist_file}"]

    initial_node_voltages = {active_pin: 0.0}
    if active_pin_inverted:
        initial_node_voltages[active_pin_inverted] = 0.0
    
    # Create simulation harness.
    simulation = CellSimulation(
        simulator,
        cell_name=cell_conf.cell_name,
        cell_ports=cell_conf.spice_ports,
        input_voltages=input_voltages, # First set all to 0V.
        input_currents=input_currents,
        output_load_capacitances={p: 1e-15 for p in output_pins}, # TODO
        initial_node_voltages=initial_node_voltages,
        setup_statements=setup_statements,
        ground_net=cell_conf.ground_net,
        simulation_title=f"measure input capacitance of {cell_conf.cell_name} {active_pin}",
        # Let ngspice find the initial voltages for output pins.
        set_initial_voltages_for_outputs=False
    )


    # Loop through all combinations of inputs.
    capacitances_rising = []
    capacitances_falling = []
    for static_input in static_inputs:
        for input_rising in [True, False]:
            simulation.reset()

            # Get voltages at static inputs.
            input_voltages = {net: cfg.supply_voltage * value for net, value in zip(static_input_nets, static_input)}
            # Set supply voltage.
            input_voltages[cell_conf.supply_net] = cfg.supply_voltage

            # Add input voltages for inverted inputs of differential pairs.
            for p in static_input_nets:
                inv = cell_conf.complementary_pins.get(p)
                if inv is not None:
                    assert inv not in input_voltages
                    # Add the inverted input voltage.
                    input_voltages[inv] = cfg.supply_voltage - input_voltages[p]

            # Add nwell voltage
            if cell_conf.nwell_pin is not None:
                input_voltages[cell_conf.nwell_pin] = cfg.supply_voltage
                
            # Add pwell voltage
            if cell_conf.pwell_pin is not None:
                input_voltages[cell_conf.pwell_pin] = 0.0
                
            logger.debug("Static input voltages: {}".format(input_voltages))

            # Simulation script file path.
            file_name = f"lctime_input_capacitance_" \
                        f"{''.join((f'{net}={v}' for net, v in input_voltages.items()))}_" \
                        f"{'rising' if input_rising else 'falling'}"

            # File for debug plot of the waveforms.
            sim_plot_file = os.path.join(cfg.workingdir, f"{file_name}_plot.svg")

            # Switch polarity of current for falling edges.
            _input_current = input_current if input_rising else -input_current

            # Get initial voltage of active pin.
            initial_voltage = 0 if input_rising else vdd
            initial_voltage_inv = vdd - initial_voltage

            # Get the breakpoint condition.
            if input_rising:
                breakpoint_statement = f"stop when v({active_pin}) > {vdd * 0.9}"
            else:
                breakpoint_statement = f"stop when v({active_pin}) < {vdd * 0.1}"
                
            # Initial node voltages.
            # Add static input voltages
            initial_conditions = input_voltages.copy()
            initial_conditions[active_pin] = initial_voltage
            initial_conditions[cell_conf.supply_net] = cfg.supply_voltage

            # Add initial voltage of inverted input pin (if any).
            if active_pin_inverted:
                initial_conditions[active_pin_inverted] = initial_voltage_inv

            for net, voltage in initial_conditions.items():
                simulation.set_initial_voltage(net, voltage)
            simulation.simulator.reset()

            # Set input voltages.
            for net, value in input_voltages.items():
                src = f"V{net}"
                simulation.set_source(src, value)

            # Set input current.
            ps = 1e-15
            ns = 1e-9
            input_current_pwl = PieceWiseLinear(
                [1*ns, 1*ns+1*ps],
                [0.0, _input_current],
                unit_y=""
            )

            simulation.set_source(f"I{active_pin}", input_current_pwl)
            if active_pin_inverted:
                simulation.set_source(f"I{active_pin_inverted}", -input_current_pwl)

            simulation.set_breakpoint(breakpoint_statement)

            # Set output loads.
            for pin in output_pins:
                simulation.set_capacitance(f"Cload_{pin}", 1e-15)

            time, voltages, currents = simulation.tran(
                t_step=cfg.time_step, t_stop=time_max,
                output_voltages=[active_pin],
                output_currents=[],
            )

            input_voltage = voltages[active_pin]

            if cfg.debug_plots:
                logger.info("Create plot of waveforms: {}".format(sim_plot_file))
                import matplotlib
                matplotlib.use('Agg')
                import matplotlib.pyplot as plt
                plt.close()
                plt.title(f"Measure input capacitance of pin {active_pin}.")
                plt.plot(time, input_voltage, label=f"V({active_pin}")
                plt.legend()
                plt.savefig(sim_plot_file)
                plt.close()

            # Calculate average derivative of voltage by finding the slope of the line
            # through the crossing point of the voltage with the two thresholds.
            #
            # TODO: How to chose the thresholds?
            if input_rising:
                thresh1 = vdd * cfg.trip_points.slew_lower_threshold_rise
                thresh2 = vdd * cfg.trip_points.slew_upper_threshold_rise
                assert thresh1 < thresh2
            else:
                thresh1 = vdd * cfg.trip_points.slew_upper_threshold_fall
                thresh2 = vdd * cfg.trip_points.slew_lower_threshold_fall
                assert thresh1 > thresh2

            # Find transition times for both thresholds.
            transition_time1 = transition_time(input_voltage, time, threshold=thresh1, n=-1)
            transition_time2 = transition_time(input_voltage, time, threshold=thresh2, n=-1)
            assert transition_time2 > transition_time1

            # Compute deltas of time and voltage between the crossing of the two thresholds.
            f_input_voltage = interpolate.interp1d(x=time, y=input_voltage)
            dt = transition_time2 - transition_time1
            dv = f_input_voltage(transition_time2) - f_input_voltage(transition_time1)

            # Compute capacitance.
            capacitance = float(_input_current) / (float(dv) / float(dt))

            logger.debug("dV: {}".format(dv))
            logger.debug("dt: {}".format(dt))
            logger.debug("I: {}".format(input_current))
            logger.debug("Input capacitance {}: {} F".format(active_pin, capacitance))

            if input_rising:
                capacitances_rising.append(capacitance)
            else:
                capacitances_falling.append(capacitance)

    logger.debug("Characterizing input capacitances: Done")

    # Find max, min or average depending on 'reduction_function'.
    logger.debug(
        "Convert capacitances of all timing arcs into the default capacitance ({})".format(reduction_function.__name__))
    final_capacitance_falling = reduction_function(capacitances_falling)
    final_capacitance_rising = reduction_function(capacitances_rising)
    final_capacitance = reduction_function([final_capacitance_falling, final_capacitance_rising])

    return {
        'rise_capacitance': final_capacitance_falling,
        'fall_capacitance': final_capacitance_rising,
        'capacitance': final_capacitance
    }

# SPDX-FileCopyrightText: 2019-2024 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Main program file for the `lctime` standard-cell characterization tool.
"""

import os
import argparse
import joblib
import tempfile
from typing import List, Set

import liberty.parser as liberty_parser
from liberty.types import *
from ..cell_types import Combinational, SingleEdgeDFF, Latch, CellType

from PySpice.Unit import *

from ..logic.util import is_unate_in_xi
from ..liberty import util as liberty_util
from ..logic import functional_abstraction
from ..logic import seq_recognition
from ..logic.types import CombinationalOutput

from .timing_combinatorial import characterize_comb_cell
from .timing_sequential import *
from .input_capacitance import characterize_input_capacitances
from . import flipflop
from . import util

from copy import deepcopy

from ..lccommon import net_util
from ..lccommon.net_util import load_transistor_netlist, is_ground_net, is_supply_net
import networkx as nx
from sympy.logic import satisfiable
import sympy.logic.boolalg

from PySpice.Spice.Parser import SpiceParser
import logging

from ..licence import licence_notice_string_single_line, original_source_repository


def _boolean_to_lambda(boolean: boolalg.Boolean, input_pins: List):
    """
    Convert a sympy.boolalg.Boolean expression into a Python lambda function.
    :param boolean: Boolean function
    :param input_pins: Ordered list of input pins. Used to keep ordering of arguments consistent between lambda function and original cell function.
    :return:
    """
    simple = sympy.simplify(boolean)
    atoms = boolean.atoms()
    input_pins = [sympy.Symbol(i) for i in input_pins]
    inputs = [i for i in input_pins if i in atoms]
    f = sympy.lambdify(inputs, simple)
    return f


def recognize_cell_from_liberty(cell_group: Group) -> Union[Latch, SingleEdgeDFF, Combinational]:
    """
    Analyze the liberty group and derive the type of the cell.
    :param cell_group:
    :return:
    """

    # Get information on pins from the liberty file.
    input_pins, outputs_user = liberty_util.get_pin_information(cell_group)

    ff_group = cell_group.get_groups("ff")
    latch_group = cell_group.get_groups("latch")

    if ff_group and latch_group:
        logger.error("Cell contains a 'ff' and 'latch' description.")
        assert False, "Cannot characterize cells with both 'ff' and 'latch'."
    elif ff_group:
        if len(ff_group) != 1:
            assert False, "Cannot characterize cells with more than one 'ff' group."
        logger.info("'ff' group found. Cell is expected to be a flip-flop.")
        ff_group = ff_group[0]
        assert isinstance(ff_group, Group)

        # Get state names.
        iq, iqn = ff_group.args
        clocked_on = ff_group.get_boolean_function('clocked_on')
        next_state = ff_group.get_boolean_function('next_state')

        clear = ff_group.get_boolean_function('clear')
        preset = ff_group.get_boolean_function('preset')

        # TODO: Store and use this.
        clear_preset_var1 = ff_group['clear_preset_var1']
        clear_preset_var2 = ff_group['clear_preset_var2']

        # TODO: Store and use this.
        clocked_on_also = ff_group.get_boolean_function('clocked_on_also')

        cell_type = SingleEdgeDFF()
        cell_type.internal_state = sympy.Symbol(iq)
        cell_type.clocked_on = clocked_on
        cell_type.next_state = next_state
        cell_type.async_preset = preset
        cell_type.async_clear = clear

    elif latch_group:
        if len(latch_group) != 1:
            assert False, "Cannot characterize cells with more than one 'latch' group."
        logger.info("'latch' group found. Cell is expected to be a latch.")
        latch_group = latch_group[0]
        assert isinstance(latch_group, Group)

        # Get state names.
        iq, iqn = latch_group.args

        cell_type = Latch()
        cell_type.internal_state = sympy.Symbol(iq)

        clocked_on = latch_group.get_boolean_function('clocked_on')
        next_state = latch_group.get_boolean_function('next_state')

        clear = latch_group.get_boolean_function('clear')
        preset = latch_group.get_boolean_function('preset')

        # TODO: Store and use this.
        clear_preset_var1 = latch_group['clear_preset_var1']
        clear_preset_var2 = latch_group['clear_preset_var2']

        # TODO: Store and use this.
        clocked_on_also = latch_group.get_boolean_function('clocked_on_also')

        cell_type.clocked_on = clocked_on
        cell_type.next_state = next_state
        cell_type.async_preset = preset
        cell_type.async_clear = clear
    else:
        # No sequential element.
        cell_type = Combinational()

    # TODO:
    # power_down_function = cell_group.get_boolean_function('power_down_function')
    # cell_type.power_down_function = power_down_function

    # Copy description of output pins.
    for name, output in outputs_user.items():
        cell_type.outputs[sympy.Symbol(name)] = output

    input_pins = {sympy.Symbol(p) for p in input_pins}

    inputs_found_in_outputs = {i for output in cell_type.outputs.values()
                               for i in output.get_inputs()}
    diff = inputs_found_in_outputs - input_pins
    if diff:
        logger.warning(f"Some input pins are used but not declared in the liberty file: {sorted(diff)}")

    cell_type.inputs = sorted(input_pins, key=str)

    return cell_type


def abort(message: str, exit_code=1):
    """
    Exit the program due to an error.
    :param message: Error message.
    :param exit_code:
    """
    logger.error(message)
    exit(exit_code)


def main():
    """
    Command-line tool for cell characterization.
    Currently only combinatorial cells are supported excluding tri-state cells.
    :return:
    """

    print(licence_notice_string_single_line())

    lctime = LcTime()
    lctime.run()


class LcTime:

    def __init__(self):
        args = None
        workdir: str = None
        library: Group = None
        new_library: Group = None # Library under construction.
        conf: CharacterizationConfig = None

    def run(self):
        logger = logging.getLogger(__name__)
        logger.info("lctime main function")

        self.f00_parse_args()
        self.f01_init_logging()
        self.f02_init_workdir()
        self.f03_init_netlists()
        self.f04_check_cell_names()
        self.f05_load_liberty_template()
        self.f06_check_delay_model()
        self.f07_init_new_library()
        self.f08_load_operating_conditions()
        self.f09_init_include_statements()
        self.f10_init_characterization_config()
        self.f11_init_table_indices()
        self.f12_characterize_library()
        self.write_liberty()

    def f00_parse_args(self):
        parser = argparse.ArgumentParser(
            description='Characterize the timing of a combinatorial cell based on a SPICE netlist. '
                        'The resulting liberty file will contain the data of the input liberty file '
                        'plus the updated characteristics of the selected cell.',
            epilog='Example: lctime --liberty specification.lib --cell INVX1 AND2X1 --spice netlists.sp -I '
                   'transistor_model.m --output mylib.lib')

        parser.add_argument('-l', '--liberty', required=True, metavar='LIBERTY', type=str,
                            help='Liberty file. This must contain all necessary specifications '
                                 'needed to characterize the cell.')

        parser.add_argument('--cell', required=True, metavar='CELL_NAME', type=str,
                            action='append',
                            nargs='+',
                            help='Names of cells to be characterized.')

        parser.add_argument('--spice', required=True, metavar='SPICE', type=str,
                            action='append',
                            nargs='+',
                            help='SPICE netlist containing a subcircuit with the same name as the cell.')

        parser.add_argument('-I', '--include', required=False, action='append', metavar='SPICE_INCLUDE', type=str,
                            help='SPICE files to include such as transistor models.')

        parser.add_argument('-L', '--library', required=False, action='append', metavar='SPICE_LIB', type=str,
                            help='SPICE .LIB statements defining each a path to the library and a library name.'
                                 'Example: --library "/path/to/lib libraryName".')

        parser.add_argument('--calc-mode', metavar='CALC_MODE', type=str, choices=['worst', 'typical', 'best'],
                            default='typical',
                            help='Calculation mode for computing the default timing arc'
                                 ' based on the conditional timing arcs. "worst", "typical" (average) or "best".')

        parser.add_argument('-o', '--output', required=True, metavar='LIBERTY_OUT', type=str, help='Output liberty file.')

        parser.add_argument('--workingdir', required=False, metavar='WORKDIR', type=str,
                            help="Directory for ngspice simulation scripts and raw results.")

        parser.add_argument('--output-loads', required=True, metavar='CAPACITANCES', type=str,
                            help="List of output load capacitances for the cells. In pico Farads."
                                 " List must be quoted, elements must be separated by a comma."
                                 " Example: '0.05, 0.1, 0.2'")

        parser.add_argument('--slew-times', required=True, metavar='SLEWTIMES', type=str,
                            help="List of slew times of the input signals in nano seconds."
                                 " List must be quoted, elements must be separated by a comma."
                                 " Example: '0.05, 0.1, 0.2'")

        parser.add_argument('--related-pin-transition', required=False, metavar='SLEWTIMES', type=str,
                            help="List of slew times of the clock signal in nano seconds. "
                                 "This is used for sequential cells only. "
                                 "List must be quoted, elements must be separated by a comma. "
                                 "Example: '0.05, 0.1, 0.2'")

        parser.add_argument('--analyze-cell-function', action='store_true',
                            help='Derive the logical function of the cell from the SPICE netlist (experimental).')

        parser.add_argument('--diff', required=False,
                            nargs="+",
                            metavar='DIFFERENTIAL_PATTERN',
                            type=str,
                            help='Specify differential inputs as "NonInverting,Inverting" tuples.'
                                 'The placeholder "%%" can be used like "%%_P,%%_N" or "%%,%%_Diff", ...')

        parser.add_argument('--time-step', default=10e-12,
                            metavar='TIME_STEP',
                            type=float,
                            help='Specify the simulation time-step in seconds. Default is 10e-12.')

        parser.add_argument('--debug', action='store_true',
                            help='Enable debug mode (more verbose logging).')

        parser.add_argument('--debug-plots', action='store_true',
                            help='Create debug plots of simulation waveforms.')

        parser.add_argument('-j', '--jobs', type=int, default=1, metavar="NUM_JOBS", help="number of threads for cell-level parallelism")

        # Parse arguments
        self.args = parser.parse_args()
        

    def f01_init_logging(self):
        DEBUG = self.args.debug
        log_level = logging.DEBUG if DEBUG else logging.INFO

        if DEBUG:
            # Also output name of function in DEBUG mode.
            log_format = '%(module)16s %(funcName)16s %(levelname)8s: %(message)s'
        else:
            log_format = '%(levelname)8s: %(message)s'

        logging.basicConfig(format=log_format, level=log_level)
    
    def f02_init_workdir(self):
        self.workingdir = self.args.workingdir
        if self.workingdir is None:
            self.workingdir = tempfile.mkdtemp(prefix="lctime-")

    def f03_init_netlists(self):
        
        # Get list of cell names to be characterized.
        self.cell_names = [n for names in self.args.cell for n in names]  # Flatten the nested list.

        # Get list of user-provided netlist files.
        netlist_files = [n for names in self.args.spice for n in names]  # Flatten the nested list.

        # Generate a lookup-table which tells for each cell name which netlist file to use.
        self.netlist_file_table: Dict[str, str] = dict()
        for netlist_file in netlist_files:
            logger.info("Load SPICE netlist: {}".format(netlist_file))
            parser = SpiceParser(path=netlist_file)
            for sub in parser.subcircuits:
                if sub.name in self.netlist_file_table:
                    # Abort if a sub circuit is defined in multiple netlists.
                    abort(
                        f"Sub-circuit '{sub.name}' is defined in multiple netlists: {self.netlist_file_table[sub.name]}, {netlist_file}")
                self.netlist_file_table[sub.name] = netlist_file

    def f04_check_cell_names(self):
        # Test if all cell names can be found in the netlist files.
        cell_names_not_found = set(self.cell_names) - self.netlist_file_table.keys()
        if cell_names_not_found:
            abort(f"Cell names not found in netlists: {', '.join(cell_names_not_found)}")

    def f05_load_liberty_template(self):
        # Load liberty file.
        lib_file = self.args.liberty
        logger.info("Reading liberty: {}".format(lib_file))
        with open(lib_file) as f:
            data = f.read()
        self.library = liberty_parser.parse_liberty(data)

    def f06_check_delay_model(self):
        # Check if the delay model is supported.
        delay_model = self.library['delay_model']
        supported_delay_models = ['table_lookup']
        if delay_model not in supported_delay_models:
            msg = "Delay model not supported: '{}'. Must be one of {}.".format(delay_model,
                                                                               ", ".join(supported_delay_models))
            logger.debug(msg)
            abort(msg)

    def f07_init_new_library(self):
        # Make independent copies of the library.
        self.new_library = deepcopy(self.library)
        # Strip all cell groups.
        self.new_library.groups = [g for g in self.new_library.groups if g.group_name != 'cell']
        # Strip away all LUT template table groups.
        table_types = ['lu_table_template', 'power_lut_template']
        self.new_library.groups = [g for g in self.new_library.groups if g.group_name not in table_types]

    def f10_init_characterization_config(self):
        
        # Setup configuration struct.
        conf = CharacterizationConfig()
        
        # Load operation voltage and temperature.
        # TODO: load voltage/temperature from operating_conditions group
        conf.supply_voltage = self.library['nom_voltage']
        logger.info('Supply voltage = {:f} V'.format(conf.supply_voltage))
        conf.temperature = self.library['nom_temperature']
        logger.info('Temperature = {:f} V'.format(conf.temperature))

        # Read trip points from liberty file.
        conf.trip_points = util.read_trip_points_from_liberty(self.library)
        logger.debug(conf.trip_points)
        
        # Get timing corner from liberty file.
        # TODO: let user overwrite it.
        calc_modes = {
            'typical': CalcMode.TYPICAL,
            'worst': CalcMode.WORST,
            'best': CalcMode.BEST,
        }
        assert self.args.calc_mode in calc_modes, "Unknown calculation mode: {}".format(self.args.calc_mode)
        conf.timing_corner = calc_modes[self.args.calc_mode]
        logger.info("timing corner: {}".format(conf.timing_corner.name))
        
        conf.setup_statements = self.setup_statements
        
        # Simulation time step
        time_resolution_seconds = float(self.args.time_step)
        logger.info(f"Time resolution = {time_resolution_seconds}s")
        if time_resolution_seconds <= 0:
            abort('Time step must be larger than zero.')

        if time_resolution_seconds > 1e-9:
            logger.warning(f"Timestep is larger than 1ns: {time_resolution_seconds}s")
        conf.time_step = time_resolution_seconds
        
        conf.workingdir = self.workingdir
        conf.debug = self.args.debug
        conf.debug_plots = self.args.debug_plots
        conf.get_units_from_liberty(self.library)

        logger.info(f"Capacitance unit: {conf.capacitance_unit} F")
        logger.info(f"Time unit: {conf.time_unit} s")
        self.conf = conf
        
    def f08_load_operating_conditions(self):
        # TODO: not used at the moment
        # Get timing corner from liberty file.
        # Find definitions of operating conditions and sort them by name.
        operating_conditions_list = self.library.get_groups('operating_conditions')
        # Put into a dict by name.
        operating_conditions: Dict[str, Group] = {str(g.args[0]): g for g in operating_conditions_list}

        logger.info("Operating conditions: {}".format(set(operating_conditions.keys())))

        """
        TODO: Use the information from the operating conditions.
        Example:
        operating_conditions (MPSS) {
            calc_mode : worst ;
            process : 1.5 ;
            process_label : "ss" ;
            temperature : 70 ;
            voltage : 4.75 ;
            tree_type : worse_case_tree ;
        }
        """

        # TODO: Make use of this.
        default_operating_conditions = self.library['default_operating_conditions']
        logger.info("Default operating conditions: {}".format(default_operating_conditions))
        
    def f09_init_include_statements(self):
        # Create .include statements for ngspice
        
        spice_includes = self.args.include if self.args.include else []
        if len(spice_includes) == 0:
            logger.warning("No transistor model supplied. Use --include or -I.")

        # Sanitize include paths.
        input_argument_error = False
        for path in spice_includes:
            if not os.path.isfile(path):
                logger.error(f"Include file does not exist: {path}")
                input_argument_error = True

        spice_libraries_raw: List[str] = self.args.library if self.args.library else []
        # Split library statements into path and library name.
        spice_libraries: List[Tuple[str, str]] = [tuple(s.strip() for s in l.split(" ", maxsplit=2))
                                                  for l in spice_libraries_raw
                                                  ]
        # Sanitize the library arguments.
        for lib, raw in zip(spice_libraries, spice_libraries_raw):
            if len(lib) != 2 or not lib[0] or not lib[1]:
                abort(f'Library statements must be of the format "/path/to/library libraryName". Found: "{raw}".')

            path, name = lib
            if not os.path.isfile(path):
                logger.error(f"Library file does not exist: {path}")
                input_argument_error = True

        # Exit if some input arguments were obviously invalid.
        if input_argument_error:
            abort("Exit because of invalid arguments.")

        # .LIB statements
        library_statements = [f".LIB {path} {name}" for path, name in spice_libraries]

        # .INCLUDE statements
        include_statements = [f".include {i}" for i in spice_includes]

        self.setup_statements = library_statements + include_statements
        
    def f11_init_table_indices(self):
        """
        Load values for input transition times and output loads.
        """
        
        # Setup array of output capacitances and input slews.
        self.output_capacitances = np.array([float(s.strip()) for s in self.args.output_loads.split(",")]) * 1e-12  # pF
        self.input_transition_times = np.array([float(s.strip()) for s in self.args.slew_times.split(",")]) * 1e-9  # ns

        # Transition times of the clock pin.
        if self.args.related_pin_transition:
            self.related_pin_transition = np.array(
                [float(s.strip()) for s in self.args.related_pin_transition.split(",")]) * 1e-9  # ns
        else:
            self.related_pin_transition = None

        logger.info(f"Output capacitances [pF]: {self.output_capacitances / 1e-12}")
        logger.info(f"Input slew times [ns]: {self.input_transition_times / 1e-9}")
        if self.related_pin_transition is not None:
            logger.info(f"Related pin transition times [ns]: {self.related_pin_transition / 1e-9}")

    def f12_characterize_library(self):
        if self.args.jobs != 1:
            # Characterize cells in parallel.
            new_cell_groups = joblib.Parallel(n_jobs=self.args.jobs, prefer='threads') \
                (joblib.delayed(self.characterize_cell)(cell_name) for cell_name in self.cell_names)
        else:
            # Characterize cells sequentially.
            new_cell_groups = [self.characterize_cell(cell_name) for cell_name in self.cell_names]

        for new_cell_group in new_cell_groups:
            self.new_library.groups.append(new_cell_group)      


    def write_liberty(self):
        """
        Dump new liberty library to disk.
        """
        assert self.new_library is not None
        
        logger.info("Write liberty: {}".format(self.args.output))
        with open(self.args.output, 'w') as f:

            # Write URL to lctime.

            s = """/*
Generated by lctime ({}).
*/
    
    """
            f.write(s.format(original_source_repository()))

            f.write(str(self.new_library))
        
    def characterize_cell(self, cell_name: str) -> Group:
        """
        Characterize a cell and create an updated cell group.
        :param cell_name:
        :return: Return an updated cell group.
        """

        cell_setup = CellSetup(self, cell_name)

        return cell_setup.run()

class CellSetup:
    """
    Measurement setup for a single cell.
    """

    def __init__(self, lctime: LcTime, cell_name: str):
        self.lctime = lctime
        """
        Global values.
        """
        self.cell_name: str = cell_name
        self.cell_workdir: str = None
        self.output_capacitances = None
        self.input_transition_times = None
        self.related_pin_transition = None
        self.cell_group = None
        self.cell_type_liberty = None
        "Cell type as derived from liberty file."
        self.cell_type = None

    def init_workdir(self):
        """
        Create working directory if it does not exist yet.
        """
        self.cell_workingdir = os.path.join(self.lctime.conf.workingdir, self.cell_name)
        if not os.path.exists(self.cell_workingdir):
            os.mkdir(self.cell_workingdir)

    def init_indices(self):
        self.output_capacitances = self.lctime.output_capacitances
        self.input_transition_times = self.lctime.input_transition_times
        self.related_pin_transition = self.lctime.related_pin_transition

    def recognize_cell_type(self):
        try:
            self.cell_group = select_cell(self.lctime.library, self.cell_name)

            # Determine type of cell (latch, flip-flop, combinational).
            self.cell_type_liberty = recognize_cell_from_liberty(self.cell_group)
            self.cell_type = self.cell_type_liberty
        except KeyError as e:
            logger.warning(f"No cell group defined yet in liberty file: {self.cell_name}")

            if not self.lctime.args.analyze_cell_function:
                abort("Cell is not defined in liberty. Enable cell recognition with --analyze.")

            self.cell_type_liberty = Combinational()  # Default: Empty cell.

            # Cell group does not exist, so create it.
            logger.debug("Create empty cell group.")
            self.cell_group = Group(group_name='cell', args=[self.cell_name])
            self.lctime.library.groups.append(self.cell_group)

            # The liberty did not define anything about this cell.
            self.cell_type = None

        # Check that the name matches.
        assert self.cell_group.args == [self.cell_name], "Cell name does not match."  # This should not happen.
        
    def init_pins(self):
        # Get information on pins from the liberty file.
        self.input_pins = [str(s) for s in self.cell_type_liberty.inputs]
        self.output_pins = [str(s) for s in self.cell_type_liberty.outputs.keys()]
        
        logger.info(f"Input pins as defined in liberty: {self.input_pins}")
        logger.info(f"Output pins as defined in liberty: {sorted(self.cell_type_liberty.outputs.keys())}")


    def init_case_lookup_table(self):
        """
        Create lookup table to fix lower/upper case mismatches between Liberty and SPICE.
        """
        
        # Get all IO pins defined in liberty.
        liberty_pins = set(self.input_pins) | set(self.output_pins)
        # Convert to strings.
        liberty_pins = {str(p) for p in liberty_pins}
        
        # Create a lookup table to reconstruct lower/upper case letters.
        # This is a workaround. The SPICE parser converts everything to uppercase.
        self.case_lookup_table = {p.lower(): p for p in liberty_pins}
        if len(self.case_lookup_table) != len(liberty_pins):
            # It's not a one-to-one mapping!
            logger.warning(f"Mixed lower case and upper case could cause trouble.")

    def fix_case(self, pin: str) -> str:
        """
        Restore lower/upper case of signals that went lost during SPICE parsing.
        """
        return self.case_lookup_table.get(pin.lower(), pin)

    def init_differential_inputs(self):

        # Extract differential pairs from liberty.
        # Liberty allows to reference complementary pins with the 'complementary_pin' attribute.
        logger.debug("Load complementary pins from liberty.")
        differential_inputs_liberty = dict()
        for pin in self.cell_group.get_groups("pin"):
            assert isinstance(pin, liberty_parser.Group)
            pin_name = pin.args[0]
            complementary_pin = pin.get("complementary_pin")
            if complementary_pin is not None:
                differential_inputs_liberty[pin_name] = complementary_pin

        # Match differential inputs.
        if self.lctime.args.diff is not None:
            logger.debug("Match complementary pins from user-defined pattern.")
            differential_inputs_from_pattern = find_differential_inputs_by_pattern(self.lctime.args.diff, self.input_pins)
        else:
            differential_inputs_from_pattern = dict()

        # Merge the differential pairs provided from the user with the pairs detected from the liberty file.
        differential_inputs_liberty.update(differential_inputs_from_pattern)
        self.differential_inputs = differential_inputs_liberty

        # Sanity checks on complementary pins.
        # Complementary pin should not be defined as pin group in liberty file.
        for pin in self.cell_group.get_groups("pin"):
            assert isinstance(pin, liberty_parser.Group)
            pin_name = pin.args[0]
            if pin_name in self.differential_inputs.values():
                logger.warning(
                    f"Complementary pin is modelled in the liberty file but will not be characterized: {pin_name}")

        for noninv, inv in self.differential_inputs.items():
            logger.info(f"Differential input (+,-): {noninv}, {inv}")

        # Find all input pins that are not inverted inputs of a differential pair.
        inverted_pins = self.differential_inputs.values()

        self.input_pins_non_inverted = [p for p in self.input_pins if p not in inverted_pins]
        "All input pins that are not inverted inputs of a differential pair"


    def create_cell_config(self) -> CellConfig:
        # Setup cell specific configuration.
        cell_conf = CellConfig()
        cell_conf.cell_name = self.cell_name
        cell_conf.global_conf = self.lctime.conf
        cell_conf.complementary_pins = self.differential_inputs
        cell_conf.ground_net = self.gnd_pin()
        cell_conf.supply_net = self.vdd_pin()
        cell_conf.workingdir = self.cell_workingdir
        cell_conf.spice_netlist_file = self.lctime.netlist_file_table[self.cell_name]
        
        # Get pin ordering of spice circuit.
        cell_conf.spice_ports = get_subcircuit_ports(self.netlist_file_path(), self.cell_name)
        logger.debug(f"SPICE subcircuit ports: {cell_conf.spice_ports}")

        return cell_conf
        
    def netlist_file_path(self) -> str:
        """
        Get path to SPICE netlist.
        """
        return self.lctime.netlist_file_table[self.cell_name]

    def vdd_pin(self):
        # TODO: don't decide based only on net name.
        power_pins = self.power_pins()
        assert len(power_pins) == 2, "Expected to have 2 power pins."
        vdd_pins = [p for p in power_pins if net_util.is_supply_net(p)]
        assert len(vdd_pins) == 1, "Expected to find one VDD pin but found: {}".format(vdd_pins)
        return vdd_pins[0]
    
    def gnd_pin(self):
        # TODO: don't decide based only on net name.
        power_pins = self.power_pins()
        assert len(power_pins) == 2, "Expected to have 2 power pins."
        gnd_pins = [p for p in power_pins if net_util.is_ground_net(p)]
        assert len(gnd_pins) == 1, "Expected to find one GND pin but found: {}".format(gnd_pins)
        return gnd_pins[0]
        
        
    def power_pins(self) -> List[str]:
        # TODO: don't decide based only on net name.
        return [p for p in self.cell_pins if net_util.is_power_net(p)]
        

    def get_liberty_pins(self) -> Set:
        """
        Get set of pin names defined in liberty template.
        """
        liberty_pins = set()
        for pin in self.cell_group.get_groups("pin"):
            assert isinstance(pin, liberty_parser.Group)
            pin_name = pin.args[0]
            liberty_pins.add(pin_name)
            complementary_pin = pin.get("complementary_pin")
            if complementary_pin is not None:
                liberty_pins.add(complementary_pin)
        return liberty_pins
        
    def check_pins(self):
        """
        Sanity check: All pins defined in liberty must appear in the SPICE netlist.
        """
        all_spice_pins = set(self.cell_pins)
        pins_not_in_spice = sorted(self.get_liberty_pins() - all_spice_pins)

        if pins_not_in_spice:
            abort(f"Pins defined in liberty but not in SPICE netlist: {', '.join(pins_not_in_spice)}")

    def io_pins(self):
        """
        Get data pins, i.e. all pins which are not power pins.
        """
        return net_util.get_io_pins(self.cell_pins)

    def load_netlist(self):
        """ Load netlist of cell
        Populate the self.transistor_graph variable.
        """
        # TODO: Load all netlists at the beginning of lctime to detect errors early.
        # Get netlist and liberty group.
        logger.info('Load netlist: %s', self.netlist_file_path())
        try:
            transistors_abstract, cell_pins = load_transistor_netlist(self.netlist_file_path(), self.cell_name)
        except Exception as e:
            abort(str(e))

        if len(transistors_abstract) == 0:
            msg = "No transistors found in cell. (The netlist must be flattened, sub-circuits are not resolved)"
            abort(msg)

        self.cell_pins = [self.fix_case(p) for p in cell_pins]
        for t in transistors_abstract:
            t.source_net = self.fix_case(t.source_net)
            t.drain_net = self.fix_case(t.drain_net)
            t.gate_net = self.fix_case(t.gate_net)

        # Convert the transistor network into its multi-graph representation.
        # This is used for a formal analysis of the network.
        self.transistor_graph = _transistors2multigraph(transistors_abstract)
        

    def recognize_input_pins(self):
        """
        Dectect input pins / gates by analyzing the transistor network.
        """
        
        logger.debug("Detect input nets from the circuit.")
        detected_inputs = functional_abstraction.find_input_gates(self.transistor_graph)
        # Detect nets that must be inputs (connected to gates only but do not
        # appear in the list of pins in the SPICE circuit definition.
        all_spice_pins = set(self.cell_pins)
        inputs_missing_in_spice = detected_inputs - all_spice_pins
        if inputs_missing_in_spice:
            logger.warning(f"The circuit has gate nets that must be inputs "
                           f"but are not in the pin definition of the SPICE circuit: "
                           f"{', '.join(sorted(inputs_missing_in_spice))}")
        # Same check for pins declared in liberty template.
        inputs_missing_in_liberty = detected_inputs - self.get_liberty_pins()
        if inputs_missing_in_liberty:
            logger.warning(f"The circuit has gate nets that must be inputs "
                           f"but are not declared as a pin in the liberty template: "
                           f"{', '.join(sorted(inputs_missing_in_liberty))}")

        # Add detected input pins.
        diff = detected_inputs - set(self.input_pins)
        if diff:
            logger.info(f"Also include detected pins: {', '.join(sorted(diff))}")
            self.input_pins.extend(diff)

        # Find pins that are defined in the SPICE circuit but are not inputs nor power.
        maybe_outputs = all_spice_pins - set(self.input_pins) - set(self.power_pins())
        if maybe_outputs:
            logger.info(f"Potential output pins: {', '.join(sorted(maybe_outputs))}")
            self.output_pins.extend(maybe_outputs)

    def recognize_cell_function(self):
            """
            Derive boolean functions for the outputs from the netlist.
            """
            logger.info("Derive boolean functions for the outputs based on the netlist.")

            self.cell_type = analyze_boolean_functions(
                self.cell_type,
                self.cell_group,
                self.transistor_graph,
                self.io_pins(),
                self.differential_inputs,
                self.vdd_pin(),
                self.gnd_pin(),
            )

            merge_cell_types(self.cell_type_liberty, self.cell_type)

    def run(self) -> Group:
        """
        Characterize the cell and create a populated 'cell' group data structure.
        """
        
        logger.info("Cell: {}".format(self.cell_name))

        self.init_workdir()
        self.init_indices()
        self.recognize_cell_type()
        self.init_pins()
        self.init_case_lookup_table()
        self.load_netlist()
        self.check_pins()
        

        # Detect input nets from the transistor netlist (if enabled).
        if self.lctime.args.analyze_cell_function:
            self.recognize_input_pins()
            
        # Sanity check.
        if len(self.input_pins) == 0:
            # TODO: could be valid for tie cells.
            abort("Cell has no input pins.")

        # Sanity check.
        if len(self.output_pins) == 0:
            abort("Cell has no output pins.")

        self.init_differential_inputs()

        if self.lctime.args.analyze_cell_function:
            self.recognize_cell_function()
        else:
            # Skip functional abstraction and take the functions provided in the liberty file.
            # output_functions_symbolic = output_functions_user
            pass  # TODO


        logger.info(f"Run characterization for {self.cell_name}")

        cell_conf = self.create_cell_config()
        
        # Add groups for the cell to be characterized.
        new_cell_group = deepcopy(select_cell(self.lctime.library, self.cell_name))

        # Populate the cell group with missing pin groups.
        create_missing_pin_groups(
            new_cell_group,
            self.cell_type,
            cell_conf,
            self.output_pins,
            self.input_pins_non_inverted
        )

        # Measure input pin capacitances.
        measure_input_capacitances(
            self.lctime.conf,
            cell_conf,
            self.input_pins,
            self.input_pins_non_inverted,
            self.output_pins,
            new_cell_group
        )

        if isinstance(self.cell_type, Combinational):
            characterize_combinational_output(
                self.lctime.new_library,
                new_cell_group,
                self.lctime.conf,
                self.cell_type,
                cell_conf,
                self.input_pins,
                self.input_pins_non_inverted,
                self.output_capacitances,
                self.input_transition_times
            )
        elif isinstance(self.cell_type, SingleEdgeDFF):
            flipflop.characterize_flip_flop_output(
                self.lctime.new_library,
                new_cell_group,
                self.lctime.conf,
                self.cell_type,
                cell_conf,
                self.related_pin_transition,
                self.input_transition_times,
                output_capacitances=self.output_capacitances
            )
        elif isinstance(self.cell_type, Latch):
            logger.info("Characterize latch.")
            logger.error("Characterization of latches is not yet supported.")

            """
            Characterization of latches is very similar to the one of flip-flops. Delays, hold and setup times
            are measured relative to the de-activating edge of the clock signal instead of the active clock edge.
            """

            abort("Characterization of latches is not yet supported.")
        else:
            assert False, f"Unsupported cell type: {type(self.cell_type)}"

        assert isinstance(new_cell_group, Group)
        return new_cell_group


def analyze_boolean_functions(
        cell_type: Optional[CellType],
        cell_group: Group,
        transistor_graph: nx.MultiGraph,
        io_pins: Set,
        differential_inputs: Dict[str, str],
        vdd_pin: str,
        gnd_pin: str,
) -> CellType:
    assert isinstance(cell_group, Group)
    assert cell_group.group_name == 'cell', "not a cell group"
    assert cell_type is None or isinstance(cell_type, CellType)

    abstracted_circuit = functional_abstraction.analyze_circuit_graph(
        graph=transistor_graph,
        pins_of_interest=io_pins,
        constant_input_pins={
            vdd_pin: True,
            gnd_pin: False},
        differential_inputs=differential_inputs,
        user_input_nets=None
    )

    if abstracted_circuit.latches:
        # There's some feedback loops in the circuit.

        # Try to recognize sequential cells.
        detected_cell_type = seq_recognition.extract_sequential_circuit(abstracted_circuit)

        if detected_cell_type:
            logger.info(f"Detected sequential circuit:\n{detected_cell_type}")

    else:
        logger.info("Detected purely combinational circuit.")
        detected_cell_type = Combinational()
        detected_cell_type.outputs = abstracted_circuit.outputs
        detected_cell_type.inputs = abstracted_circuit.get_primary_inputs()
        if cell_type is None:
            cell_type = Combinational()

    if cell_type is None or len(cell_group.groups) == 0:
        cell_type = detected_cell_type
    else:
        # Sanity check: Detected cell type (combinational, latch, ff) must match with the liberty file.
        if type(detected_cell_type) is not type(cell_type):
            msg = f"Mismatch: Detected cell type is {type(detected_cell_type)} " \
                  f"but liberty says {type(cell_type)}."
            logger.error(msg)
            assert False, msg

    output_functions_deduced = abstracted_circuit.outputs

    # Log deduced output functions.
    for output_name, value in output_functions_deduced.items():
        if value.high_impedance:
            logger.info(
                f"Deduced output function: {output_name} = {value.function}, tri_state = {value.high_impedance}")
        else:
            logger.info(f"Deduced output function: {output_name} = {value.function}")

    # # Convert keys into strings (they are `sympy.Symbol`s now)
    # output_functions_deduced = {str(output.name): comb.function for output, comb in
    #                             output_functions_deduced.items()}
    # output_functions_symbolic = output_functions_deduced.copy()

    return cell_type


def merge_cell_types(
        source_cell_type: CellType,
        target_cell_type: CellType
):
    # Merge deduced output functions with the ones read from the liberty file and perform consistency check.
    for output_symbol, output in source_cell_type.outputs.items():
        output_name = str(output_symbol)
        logger.info(f"User supplied output function: {output_name} = {output_name}")

        assert output_symbol in target_cell_type.outputs, f"No function has been deduced for output pin '{output_name}'."
        # Consistency check:
        # Verify that the deduced output formula is equal to the one defined in the liberty file.
        logger.info("Check equality of boolean function in liberty file and derived function.")
        equal = functional_abstraction.bool_equals(output.function,
                                                   target_cell_type.outputs[output_symbol].function)
        if not equal:
            msg = "User supplied function does not match the deduced function for pin '{}'".format(output_name)
            logger.error(msg)

        if equal:
            # Take the function defined by the liberty file.
            # This might be desired because it is in another form (CND, DNF,...).
            target_cell_type.outputs[output_symbol] = output


def create_missing_pin_groups(
        new_cell_group: Group,
        cell_type: CellType,
        cell_conf: CellConfig,
        output_pins: List[str],
        input_pins_non_inverted: List[str]
):
    # Strip away timing groups. They will be replaced by the new characterization.
    for pin_group in new_cell_group.get_groups('pin'):
        pin_group.groups = [g for g in pin_group.groups if g.group_name != 'timing']

    # Create missing pin groups.
    for pin in sorted(set(input_pins_non_inverted + output_pins)):
        pin_group = new_cell_group.get_groups('pin', pin)
        if not pin_group:
            pin_group = Group('pin', args=[pin])
            new_cell_group.groups.append(pin_group)

    # Set 'direction' attribute of input pins.
    for pin in input_pins_non_inverted:
        pin_group = new_cell_group.get_group('pin', pin)
        if 'direction' not in pin_group:
            pin_group['direction'] = 'input'

    # Set 'direction' attribute of output pins.
    for pin in output_pins:
        pin_group = new_cell_group.get_group('pin', pin)
        if 'direction' not in pin_group:
            pin_group['direction'] = 'output'
        pin_symbol = sympy.Symbol(pin)
        if cell_type.outputs[pin_symbol].is_tristate():
            # Mark as tri-state.
            pin_group.set_boolean_function('three_state', cell_type.outputs[pin_symbol].high_impedance)

    # Create 'complementary_pin' attribute for the inverted pin of differential pairs.
    for input_pin in input_pins_non_inverted:
        input_pin_group = new_cell_group.get_group('pin', input_pin)
        # Create link to inverted pin for differential inputs.
        input_pin_inverted = cell_conf.complementary_pins.get(input_pin)
        if input_pin_inverted:
            input_pin_group['complementary_pin'] = [EscapedString(input_pin_inverted)]


def measure_input_capacitances(
        conf: CharacterizationConfig,
        cell_conf: CellConfig,
        input_pins: List[str],
        input_pins_non_inverted: List[str],
        output_pins: List[str],
        cell_group: Group
):
    """
    Measure input capacitances and write them into the `cell_group`.
    :param conf: 
    :param cell_conf: 
    :param input_pins: 
    :param input_pins_non_inverted: 
    :param output_pins: 
    :param cell_group: 
    :return: 
    """
    logger.debug(f"Measuring input pin capacitances of cell {cell_conf.cell_name}.")
    for input_pin in input_pins_non_inverted:
        # Input capacitances are not measured for the inverting inputs of differential pairs.
        logger.info("Measuring input capacitance: {} {}".format(cell_conf.cell_name, input_pin))
        input_pin_group = cell_group.get_group('pin', input_pin)

        result = characterize_input_capacitances(
            input_pins=input_pins,
            active_pin=input_pin,
            output_pins=output_pins,
            cell_conf=cell_conf
        )

        input_pin_group['rise_capacitance'] = result['rise_capacitance'] / conf.capacitance_unit
        input_pin_group['fall_capacitance'] = result['fall_capacitance'] / conf.capacitance_unit
        input_pin_group['capacitance'] = result['capacitance'] / conf.capacitance_unit


def characterize_combinational_output(
        new_library: Group,
        new_cell_group: Group,
        conf: CharacterizationConfig,
        cell_type: CellType,
        cell_conf: CellConfig,
        input_pins: List[str],
        input_pins_non_inverted: List[str],
        output_capacitances: np.ndarray,
        input_transition_times: np.ndarray
):
    assert isinstance(cell_type, Combinational) or isinstance(cell_type, SingleEdgeDFF)
    
    is_clock_to_output_arc = isinstance(cell_type, SingleEdgeDFF)
    
    # Measure timing for all input-output arcs.
    logger.debug("Measuring delay arcs.")
    for output_pin_symbol in cell_type.outputs.keys():
        output_pin_name = str(output_pin_symbol)
        output_pin_group = new_cell_group.get_group('pin', output_pin_name)

        # Store boolean function of output to liberty.
        output_pin_group.set_boolean_function('function', cell_type.outputs[output_pin_symbol].function)

        # Check if the output can be high-impedance.
        is_tristate = cell_type.outputs[output_pin_symbol].is_tristate()

        # Store three_state function to liberty.
        constant_input_pins = dict()
        if is_tristate:
            output_pin_group.set_boolean_function(
                'three_state', cell_type.outputs[output_pin_symbol].high_impedance
            )

            # Find normal operating conditions such that the output is not tri-state.
            models = list(satisfiable(~cell_type.outputs[output_pin_symbol].high_impedance, all_models=True))
            for model in models:
                logger.info(f"Output '{output_pin_name}' is low-impedance when {model}.")

            if len(models) > 1:
                abort("Characterization of tri-state outputs is not supported when the tri-state depends on"
                      "more than one input.")

            model = models[0]
            for name, value in model.items():
                constant_input_pins[str(name)] = value

        # Skip measuring the tri-state enable input.
        related_pins = sorted(set(input_pins_non_inverted) - constant_input_pins.keys())
        _input_pins = sorted(set(input_pins) - constant_input_pins.keys())

        # Characterize each from related_pin to output_pin.
        for related_pin in related_pins:

            related_pin_inverted = cell_conf.complementary_pins.get(related_pin)
            if related_pin_inverted:
                logger.info("Timing arc (differential input): ({}, {}) -> {}"
                            .format(related_pin, related_pin_inverted, output_pin_name))
            else:
                logger.info("Timing arc: {} -> {}".format(related_pin, output_pin_name))

            # Convert deduced output functions into Python lambda functions.
            output_functions = {
                str(name): _boolean_to_lambda(comb_output.function, input_pins)
                for name, comb_output in cell_type.outputs.items()
            }

            # Get timing sense of this arc.
            timing_sense = str(is_unate_in_xi(output_functions[output_pin_name], related_pin).name).lower()
            logger.info("Timing sense: {}".format(timing_sense))

            result = characterize_comb_cell(
                input_pins=_input_pins,
                output_pin=output_pin_name,
                related_pin=related_pin,
                output_functions=output_functions,

                total_output_net_capacitance=output_capacitances,
                input_net_transition=input_transition_times,

                cell_conf=cell_conf,
                constant_inputs=constant_input_pins
            )

            # Get the table indices.
            # TODO: get correct index/variable mapping from liberty file.
            index_1 = result['total_output_net_capacitance'] / conf.capacitance_unit
            index_2 = result['input_net_transition'] / conf.time_unit

            # Create template tables.
            delay_template_table = liberty_util.create_delay_template_table(new_library, len(index_1), len(index_2))
            delay_table_template_name = delay_template_table.args[0]

            # Create liberty timing tables.
            timing_tables = []
            for table_name in ['cell_rise', 'cell_fall', 'rise_transition', 'fall_transition']:
                table = Group(
                    table_name,
                    args=[delay_table_template_name],
                )

                table.set_array('index_1', index_1)
                table.set_array('index_2', index_2)
                table.set_array('values', result[table_name] / conf.time_unit)

                timing_tables.append(table)

            # Create the liberty timing group.
            timing_attributes = [
                Attribute('related_pin', EscapedString(related_pin)),
                Attribute('timing_sense', timing_sense)
            ]

            timing_group = Group(
                'timing',
                attributes=timing_attributes,
                groups=timing_tables
            )

            # Attach timing group to output pin group.
            output_pin_group.groups.append(timing_group)

            # Create template tables.
            power_template_table = liberty_util.create_power_template_table(new_library, len(index_1), len(index_2))
            power_table_template_name = power_template_table.args[0]
            
            # Create liberty power tables.
            power_tables = []
            for table_name in ['rise_power', 'fall_power']:
                table = Group(
                    table_name,
                    args=[power_table_template_name],
                )

                table.set_array('index_1', index_1)
                table.set_array('index_2', index_2)
                table.set_array('values', result[table_name] / conf.energy_unit)

                power_tables.append(table)

            power_attributes = [
                Attribute('related_pin', EscapedString(related_pin)),
            ]
            
            internal_power_group = Group(
                'internal_power',
                attributes=power_attributes,
                groups=power_tables
            )
            
            # Attach group to output pin group.
            output_pin_group.groups.append(internal_power_group)
    
def _transistors2multigraph(transistors) -> nx.MultiGraph:
    """ Create a graph representing the transistor network.
        Each edge corresponds to a transistor, each node to a net.
    """
    G = nx.MultiGraph()
    for t in transistors:
        G.add_edge(t.source_net, t.drain_net, (t.gate_net, t.channel_type))
    assert nx.is_connected(G)
    return G


# Copyright (c) 2019-2020 Thomas Kramer.
# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Simple sub-process based NgSpice binding.
"""

import os
import subprocess
import queue
import threading
import logging
import tempfile
import numpy as np
from typing import Dict, List, Tuple, Union, Optional
from .piece_wise_linear import PieceWiseLinear

logger = logging.getLogger(__name__)


def run_simulation(sim_file: str, ngspice_executable: str = 'ngspice'):
    """
    Invoke 'ngspice' to run the `sim_file`.
    :param sim_file: Path to ngspice simulation file.
    :return: Returns (stdout, stderr) outputs of ngspice.
    """
    logger.debug(f"Run simulation: {sim_file}")
    try:
        ret = subprocess.run([ngspice_executable, sim_file], capture_output=True)
        # proc = subprocess.Popen([ngspice_executable, sim_file])
        # logger.debug(f"Subprocess return value: {ret}")
        if ret.returncode != 0:
            ngspice_err_message = ret.stderr.decode("utf-8")
            logger.error(f"ngspice simulation failed: {ngspice_err_message}")
            raise Exception(f"ngspice simulation failed: {ngspice_err_message}")

        return ret.stdout.decode("utf-8"), ret.stderr.decode("utf-8")
    except FileNotFoundError as e:
        msg = f"SPICE simulator executable not found. Make sure it is in the current path: {ngspice_executable}"
        logger.error(msg)
        raise FileNotFoundError(msg)

class CellSimulation:

    def __init__(self,
        simulator, #: NgSpiceInteractive,
        cell_name: str,
        cell_ports: List[str],
        input_voltages: Dict[str, Union[float, PieceWiseLinear]],
        input_currents: Dict[str, Union[float, PieceWiseLinear]],
        output_load_capacitances: Dict[str, float] = None,
        setup_statements: List[str] = None,
        ground_net: str = "GND",
        simulation_title: str = "<UNTITLED SIMULATION>",
        initial_node_voltages: Dict[str, float] = None,
        set_initial_voltages_for_outputs: bool = True
    ):
        """
        :param simulator:
        :param cell_name: Name of the cell.
        :param cell_ports: List of all pins in the order they appear in the SPICE subcircuit.
        :param input_voltages: Values for driving input pins with a voltage source.
        :param input_currents: Values for driving input pins with a current source.
        :param output_load_capacitances: 
        :param setup_statements: ngspice statements such as 'include' or 'lib'
        :param ground_net: Name of the ground net.
        :param simulation_title: Descriptive title of the simulation.
        :param initial_node_voltages: Optionally provide initial node voltages here.
        :param set_initial_voltages_for_outputs: Enable initial node voltage hints for output pins

        """
        assert isinstance(simulator, Simulator)
        self.simulator = simulator
        self.cell_name = cell_name
        self.cell_ports = cell_ports
        self.input_voltages = input_voltages
        self.input_currents = input_currents
        self.initial_node_voltages = initial_node_voltages if initial_node_voltages else dict()
        self.simulation_title = simulation_title
        self.ground_net = ground_net
        self.temperature = 25
        self.output_load_capacitances = output_load_capacitances
        self.setup_statements = setup_statements
        self.set_initial_voltages_for_outputs = set_initial_voltages_for_outputs 
        missing_sources = set(cell_ports) - {ground_net} - input_voltages.keys() - input_currents.keys() - output_load_capacitances.keys()
        if missing_sources:
            logger.warning(f"missing sources for input pins: {missing_sources}")
            assert False

        self._init_simulation()

    def _initial_voltages(self) -> Dict[str, float]:
        initial_voltages = dict()
        for net, v in self.input_voltages.items():
            if isinstance(v, PieceWiseLinear):
                initial_voltages[net] = v(0)
            else:
                initial_voltages[net] = v
                
        # Set default value of outputs.
        if self.set_initial_voltages_for_outputs:
            for net in self.output_load_capacitances.keys():
                initial_voltages[net] = 0.0

        for net, v in self.initial_node_voltages.items():
            initial_voltages[net] = v
            
        return initial_voltages
        
    def _initial_currents(self) -> Dict[str, float]:
        initial_currents = dict()
        for net, v in self.input_currents.items():
            if isinstance(v, PieceWiseLinear):
                initial_currents[net] = v(0)
            else:
                initial_currents[net] = v
        return initial_currents
        

    def _default_circuit(self) -> str:
        """
        Create SPICE netlist of this simulation setup.
        """

        # Create a list of include files.
        setup_statements_string = ""
        if self.setup_statements is not None:
            # Load include files.
            setup_statements_string = "\n".join(self.setup_statements)

        # If the ground net is not called GND, then it must be connected to GND or 0.
        # This seems to be a must for SPICE simulators.
        # See: https://codeberg.org/librecell/lctime/issues/12#issuecomment-2173526
        ground_connection = ""
        if self.ground_net not in ["GND", "gnd", "0"]:
            logger.debug(f"Connect ground net `{self.ground_net}` to simulators ground `0`.")
            ground_connection = f"* Connect ground net to GND\n" \
            f"vgnd {self.ground_net} 0 0"

        # Load capacitance statements.
        load_capacitance_statements = ""
        if self.output_load_capacitances is not None:
            assert isinstance(self.output_load_capacitances, dict)
            load_capacitance_statements = "\n".join(
                (
                    f"Cload_{net} {net} {self.ground_net} {load}"
                    for net, load in self.output_load_capacitances.items()
                )
            )

        # Generate SPICE statements of input sources.
        signal_source_statements = ""
        signal_source_statements += _generate_input_voltage_statements(self.ground_net, self.input_voltages)
        signal_source_statements += "\n"
        signal_source_statements += _generate_input_current_statements(self.ground_net, self.input_currents)

        sim_netlist = f"""* librecell {__name__}
.title {self.simulation_title}

.control
* Exit on error with return value 1
pre_set strict_errorhandling
.endc

.option TEMP={self.temperature}

{self._params_initial_counditions()}

{setup_statements_string}

{ground_connection}

* Output load capacitances.
{load_capacitance_statements}

* Input and supply sources.
{signal_source_statements}

Xcircuit_under_test {" ".join(self.cell_ports)} {self.cell_name}

{self._initial_conditions_stmts()}

.end
"""
        return sim_netlist

    def _initial_conditions_stmts(self):
        # TODO
        # Also all voltages of DC sources must be here if they are needed to compute the initial conditions.

        initial_voltages = [
            f"v({net})={{ic_{net.lower()}}}"
            for net, _ in self._initial_voltages().items()
        ]
        initial_currents = [] # TODO
        # initial_currents = [
        #     f"i(V{net})={{ic_i_{net.lower()}}}"
        #     for net, _ in self._initial_currents().items()
        # ]
        ics = initial_voltages + initial_currents

        return f'.ic {" ".join(ics)}'

    def _params_initial_counditions(self):
        """
        Define variables (parameters) for the values of initial conditions. 
        """
        params = []

        for net, v in self._initial_voltages().items():
            params.append(f".param ic_{net.lower()}={v}")

        for net, i in self._initial_currents().items():
            params.append(f".param ic_i_{net.lower()}={i}")

        return "\n".join(params)

    def _init_simulation(self):
        logger.debug(self._default_circuit())
        #self.simulator.remove_circuit() # Remove any existing circuit.
        self.simulator.load_circuit(self._default_circuit())

    def set_temperature(self, temp: float):
        self.temperature = temp
        self.simulator.cmd(f"option TEMP={temp}")

    def set_breakpoint(self, breakpoint: str):
        assert breakpoint.startswith("stop")
        self.simulator.cmd(breakpoint.lower())

    # TODO remove
    # def delete_all_breakpoints(self):
    #     """
    #     Delete breakpoints.
    #     """
    #     self.simulator.drop_stdout()

    #     # Ask for current breakpoints.
    #     self.simulator.cmd("status")

    #     nums = [] # Breakpoint numbers to be deleted.
        
    #     read_timeout = 0.1
    #     # Get current breakpoints.
    #     while True:
    #         line = self.simulator.readline(timeout=read_timeout)
    #         read_timeout = 0.001 # Use shorter timeout after the first line.
    #         if line is None:
    #             break
    #         # Parse response.
    #         parts = line.split() # Split at whitespace
    #         if len(parts) > 1 and parts[1] == "stop":
    #             num = int(parts[0])
    #             nums.append(num)

    #     logger.info(f"num breakpoints: {len(nums)}")
    #     for num in nums:
    #         self.simulator.cmd(f"delete {num}")

    def set_capacitance(self, name: str, value: float):
        name = name.lower()
        assert name.startswith("c"), "capacitor name must start with C"
        self.simulator.cmd(f"alter {name} = {value}")
        
    def set_capacitor_voltage(self, name: str, value: float):
        name = name.lower()
        assert name.startswith("c"), "capacitor name must start with C"
        self.simulator.cmd(f"alter {name} ic = {value}")

    def set_resistance(self, name: str, value: float):
        name = name.lower()
        assert name.startswith("r"), "resistor name must start with R"
        self.simulator.cmd(f"alter {name} = {value}")

    def set_source_dc(self, name: str, value: float):
        name = name.lower()
        assert name.startswith("v") or name.startswith("i"), "source name must start with i or v"
        self.simulator.cmd(f"alter {name} dc = {value}")

    def set_source_pwl(self, name: str, pwl: PieceWiseLinear):
        name = name.lower()
        assert name.startswith("v") or name.startswith("i"), "source name must start with i or v"
        assert isinstance(pwl, PieceWiseLinear)
        self.simulator.cmd(f"alter {name} pwl = [ {pwl.to_spice_pwl_string()} ]")

    def set_source(self, name: str, source: Union[float, PieceWiseLinear]):
        if isinstance(source, PieceWiseLinear):
            self.set_source_dc(name, 0.0)
            self.set_source_pwl(name, source)
        else:
            self.set_source_dc(name, source)

    def set_initial_voltage(self, net: str, value: float):
        assert isinstance(value, float) or isinstance(value, int)
        self.simulator.cmd(f"alterparam ic_{net.lower()}={value}")

    def set_initial_current(self, component: str, value: float):
        assert isinstance(value, float) or isinstance(value, int)
        self.simulator.cmd(f"alterparam ic_i_{component.lower()}={value}")

    def tran(self, t_step: float, t_stop: float, t_start=None,
            output_voltages: List[str] = [], 
            output_currents: List[str] = [],
             ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Run transient simulation.

        Return number of datapoints.
        """
        return self.simulator.tran(
            t_step=t_step, t_stop=t_stop, t_start=t_start,
            output_voltages=output_voltages, output_currents=output_currents
        )

    def reset(self):
        """
        Reset parameters, clear all breakpoints.
        """
        self.simulator.reset()
        self.simulator.cmd("delete all") # Delete all breakpoints.
        self.simulator.cmd("destroy all") # Remove previous datasets.

def _generate_input_voltage_statements(ground_net: str, input_voltages: Dict[str, Union[float, PieceWiseLinear]]) -> str:
    # Generate SPICE statements for input voltages.
    source_statements = []
    for net, wave in input_voltages.items():
        assert isinstance(wave, float) or isinstance(wave, PieceWiseLinear)
        source_statements.extend([
            __create_voltage_source_statement(ground_net, f"{net}", wave), # Ideal voltage source
        ])
    return "\n".join(source_statements)

def _generate_input_current_statements(ground_net: str, input_currents: Dict[str, Union[float, PieceWiseLinear]]) -> str:
    # Generate SPICE statements for input currents.
    source_statements = []
    for net, wave in input_currents.items():
        assert isinstance(wave, float) or isinstance(wave, PieceWiseLinear)
        source_statements.extend([
            __create_current_source_statement(ground_net, f"{net}", wave), # Ideal current source
        ])
    return "\n".join(source_statements)

def __create_voltage_source_statement(ground_net: str, net: str, voltage: Union[float, PieceWiseLinear]) -> str:
    """
    Create a SPICE statement for a voltage source driving the 'net' with a voltage.
    The voltage can be either a static value or a `PieceWiseLinear` function.
    """
    if isinstance(voltage, PieceWiseLinear):
        return f"V{net} {net} {ground_net} PWL({voltage.to_spice_pwl_string()}) DC=0"
    elif isinstance(voltage, float):
        return f"V{net} {net} {ground_net} {voltage}"
    else:
        assert False, "`voltage` must be either a float or {}".format(PieceWiseLinear)

def __create_current_source_statement(ground_net: str, net: str, current: Union[float, PieceWiseLinear]) -> str:
    """
    Create a SPICE statement for a current source driving the 'net' with a current.
    The current can be either a static value or a `PieceWiseLinear` function.
    """
    if isinstance(current, PieceWiseLinear):
        return f"I{net} {ground_net} {net} PWL({current.to_spice_pwl_string()}) DC=0"
    elif isinstance(current, float):
        return f"I{net} {ground_net} {net} {current}"
    else:
        assert False, "`current` must be either a float or {}".format(PieceWiseLinear)

class Simulator:
    """
    Abstract interface of SPICE circuit simulators.
    """

    def __init__(self):
        pass

    def name(self) -> str:
        """
        Get name of the simulator.
        """
        raise NotImplemented()

    def version_string(self) -> str:
        """
        Get version string of the simulator.
        """
        raise NotImplemented()

    def source(self, file: str):
        """
        Load a netlist from a file.
        """
        raise NotImplemented()

    def reset(self):
        raise NotImplemented()

    def tran(self, t_step, t_stop, t_start=None,
            output_voltages: List[str] = [], 
            output_currents: List[str] = [],
             ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """

        :param t_step:
        :param t_stop:
        :param t_start:
        :param output_voltages: Names of voltages which should be measured and returned
        :param output_currents:
        :return: A tuple of `(time, voltages, currents)`. Voltages and currents are stored in a dict by their name.
        """
        raise NotImplemented()

    def remove_circuit(self):
        """
        Remove current circuit.
        """
        raise NotImplemented()

    def load_circuit(self, circuit: str):
        """
        Load a circuit over stdin.
        :param circuit:
        :return:
        """
        raise NotImplemented()

class SimulatorSubprocess(Simulator):

    def __init__(self, executable: str, args: List[str] = []):
        self.executable = executable
        self.args = args

        self.proc: subprocess.Popen[str] = None
        "process handle."

        self._from_stdout = queue.Queue()
        self._from_stderr = queue.Queue()

        self._stdout_reader_thread = None
        self._stderr_reader_thread = None

    def _start(self):
        self.proc = subprocess.Popen(
            [self.executable] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        def read_stdout():
            while self.proc:
                line = self.proc.stdout.readline()
                if line is None:
                    break
                line = line.strip()
                if not line:  # Skip empty lines.
                    continue
                # print("stdout:", line)
                self._from_stdout.put(line)

        def read_stderr():
            while self.proc:
                line = self.proc.stderr.readline()
                if line is None:
                    break
                line = line.strip()
                if not line:  # Skip empty lines.
                    continue
                # print("stderr:", line)
                # Forward error messages to the logger.
                if 'Error' in line:
                    self.logger.error(line)
                elif 'Warning' in line:
                    self.logger.warning(line)
                self._from_stderr.put(line)

        self._stdout_reader_thread = threading.Thread(target=read_stdout, daemon=True)
        self._stderr_reader_thread = threading.Thread(target=read_stderr, daemon=True)
        self._stdout_reader_thread.start()
        self._stderr_reader_thread.start()

    def _stop(self):
        if self.proc:
            self.proc.kill()
            self.proc = None

    def readline(self, timeout: Optional[int] = 0.1) -> str:
        try:
            return self._from_stdout.get(block=True, timeout=timeout)
        except queue.Empty:
            return None

    def drop_stdout(self):
        """
        Delete the stdout buffer.
        """
        while not self._from_stdout.empty():
            self._from_stdout.get_nowait()

    def drop_stderr(self):
        """
        Delete the stderr buffer.
        """
        while not self._from_stdout.empty():
            self._from_stdout.get_nowait()

    def readline_err(self, timeout: float = 0.1) -> str:
        """
        Read stderr.
        Returns `None` if there's nothing on stderr within the timeout.
        """
        try:
            return self._from_stderr.get(block=True, timeout=timeout)
        except queue.Empty:
            return None

    def _write(self, data: str):
        self.proc.stdin.write(data)

    def _flush(self):
        self.proc.stdin.flush()

def test_ngspice_file_based():
    import math

    sim = NgSpiceFileBased()

    vdd = 1
    vcap_init = 0
    sim.load_circuit(f"""
V1 vout 0 {vdd}
R1 vout vcap 1000
C1 vcap 0 1e-6

.ic v(vcap)={vcap_init}
""")

    for _ in range(3): # Do simulation multiple times to check if 'reset' works.
        t_stop = 1
        time, voltages, currents = sim.tran(
                    t_step=1e-4, t_stop=t_stop,
                    output_voltages=['vcap', 'vout'],
                    output_currents=['v1']
                )

        assert abs(time[-1] - t_stop) < 1e-6
        assert np.all(np.isclose(voltages['vout'], vdd))
        assert abs(voltages['vcap'][0] - vcap_init) < 1e-3
        assert abs(voltages['vcap'][-1] - vdd) < 1e-3

        sim.reset()

class NgSpiceFileBased(SimulatorSubprocess):
    """
    Interface to non-interactive ngspice.
    Writes the simulation script into a file, calls ngspice, then reads the results.
    """

    def __init__(self,
                 ngspice_executable: str = None,
                 workdir: str = None,
                 logger: logging.Logger = None):
        self.logger = logger
        if logger is None:
            self.logger = logging.getLogger(__name__)
        executable = 'ngspice' if ngspice_executable is None else ngspice_executable

        super().__init__(executable, ["-p"])

        self._workdir = workdir
        if workdir is None:
            self._workdir = tempfile.mkdtemp(prefix="lctime")

        self._commands = []
        self._circuit: str = ""

    def name(self) -> str:
        return "ngspice-file-based"

    def version_string(self) -> str:
        """
        Get ngspice version string.
        Returns something like "ngspice-39" or "ngspice-44+".
        Raises an exception if ngspice executable cannot be found.
        """

        output = subprocess.check_output([self.executable, "--version"]).decode("utf-8")
        lines = output.split("\n")

        for l in lines:
            if "ngspice-" in l:
                parts = l.split()
                if len(parts) > 2:
                    return parts[1]

        return "ngspice-unknown"

    def __exit__(self, *args):
        pass

    def __enter__(self):
        return self
    
    def cmd(self, cmd: str):
        self._commands.append(cmd)

    def source(self, file: str):
        """
        Load a netlist.
        """
        self.cmd(f"source {file}")

    def reset(self):
        #self._commands.clear()
        def take_cmd(c: str) -> bool:
            return c.startswith("alter")
        self._commands = [c for c in self._commands if take_cmd(c)]
        self.cmd('reset')
        
    def remove_circuit(self):
        self._commands = []
        self._circuit = ""
    
    def load_circuit(self, circuit: str):
        self._commands = []
        self._circuit = circuit

    def _write_sim_file(self, path: str):

        control = "\n".join(self._commands)
        

        spice_script = f"""
.title lctime simulation

{self._circuit}

.control
{control}
.endc

.end
        """

        with open(path, "w") as f:
            f.write(spice_script)

    def _run_simulation(self, output_voltages: List[str], output_currents: List[str]):
        simfile = os.path.join(self._workdir, "simulation.sp")
        sim_output_file = os.path.join(self._workdir, "simulation_out.txt")
        
        output_voltage_stmts = " ".join(f"v({v})" for v in output_voltages)
        output_current_stmts = " ".join(f"i({v})" for v in output_currents)
        
        self.cmd("set filetype=ascii")
        self.cmd("set wr_vecnames") # Enable output of vector names in the first line
        self.cmd(f"wrdata {sim_output_file} {output_voltage_stmts} {output_current_stmts}")
        self.cmd("exit")

        self._write_sim_file(simfile)

        result = subprocess.run(
            [self.executable, simfile],
            capture_output=True
        )

        if result.returncode != 0:
            raise Exception(f"ngspice failed: {result.stderr}")
        
    def _get_data(self, output_voltages: List[str] = [], output_currents: List[str] = []):
        sim_output_file = os.path.join(self._workdir, "simulation_out.txt")
        #data = np.genfromtxt(sim_output_file, skip_header=1, ndmin=2)
        data = np.loadtxt(sim_output_file, skiprows=1, ndmin=2)

        time = data[:,0]

        # Extract signals (strip away time)
        data = data[:,1::2]
        voltages = data[:, :len(output_voltages)].T
        currents = data[:, len(output_voltages):].T
        assert len(currents) == len(output_currents), "mismatch in number of data columns"
        
        voltages = {name: v for name, v in  zip(output_voltages, voltages)}
        currents = {name: i for name, i in  zip(output_currents, currents)}

        return time, voltages, currents

    def tran(self,
            t_step: float,
            t_stop: float, 
            output_voltages: List[str] = [], 
            output_currents: List[str] = [],
            t_start: float=None,
            uic: str = ""
            ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:

        self.cmd(f'tran {t_step} {t_stop} {uic}')
        self._run_simulation(output_voltages, output_currents)
        
        return self._get_data(output_voltages, output_currents)

class NgSpiceInteractive(SimulatorSubprocess):
    """
    Interface to ngspice as an interactive subprocess.
    """

    def __init__(self,
                 ngspice_executable: str = None,
                 logger: logging.Logger = None):
        self.logger = logger
        if logger is None:
            self.logger = logging.getLogger(__name__)
        executable = 'ngspice' if ngspice_executable is None else ngspice_executable

        super().__init__(executable, ["-p"])

        self._circuit_is_loaded = False

    def name(self) -> str:
        return "ngspice-interactive"

    def version_string(self) -> str:
        """
        Get ngspice version string.
        Returns something like "ngspice-39" or "ngspice-44+".
        Raises an exception if ngspice executable cannot be found.
        """

        output = subprocess.check_output([self.executable, "--version"]).decode("utf-8")
        lines = output.split("\n")

        for l in lines:
            if "ngspice-" in l:
                parts = l.split()
                if len(parts) > 2:
                    return parts[1]

        return "ngspice-unknown"

    def __reboot(self):
        """
        Restart ngspice process. Used as a workaraound for memory leaks in ngspice.
        """
        self._stop()
        self._start();

    def __exit__(self, *args):
        self._stop()

    def __enter__(self):
        self._start()
        return self

    def cmd(self, cmd: str):
        self.logger.debug(f"ngspice> {cmd}")
        self._write(cmd)
        self._write('\n')
        self._flush()
        self.__check_err(0.001) # TODO remove?

    def source(self, file: str):
        """
        Load a netlist.
        """
        self.cmd(f"source {file}")

    def reset(self):
        self.cmd('reset')

    def _tran(self, t_step, t_stop, t_start=None, uic='') -> int:
        """

        :param t_step:
        :param t_stop:
        :param t_start:
        :param uic:
        :return: Return number of data points.
        """
        self._flush()
        self.cmd(f'tran {t_step} {t_stop} {uic}')
        self.cmd(f'print length(time)')  # Should print something like: length(time) = 1.234e+03

        # Find number of data points.
        num_rows = 0
        while True:
            line = self.readline(timeout=None)
            assert line is not None
            if line.startswith('length(time)'):
                _, num_rows_str = line.split('=', 2)
                num_rows = int(float(num_rows_str))
                break
            else:
                logger.debug(f"ngspice: {line}")

        assert num_rows > 0
        return num_rows

    def remove_circuit(self):
        """
        Remove current circuit.
        """
        self.cmd("remcirc")
        self._circuit_is_loaded = False

    def load_circuit(self, circuit: str):
        """
        Load a circuit over stdin.
        :param circuit:
        :return:
        """
        
        if self._circuit_is_loaded:
            self.remove_circuit()
            
        lines = circuit.split('\n')
        for line in lines:
            line = line.strip()
            if line:
                self._write("circbyline ")
                self._write(line)
                self._write('\n')
                self._flush()
        self.__check_err(timeout=0)

        self._circuit_is_loaded = True

    def tran(self,
            t_step: float,
            t_stop: float, 
            output_voltages: List[str] = [], 
            output_currents: List[str] = [],
            t_start: float=None,
            ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        num_rows = self._tran(t_step=t_step, t_stop=t_stop, t_start=t_start)
        
        return self._get_data(num_rows, output_voltages, output_currents)

    def _get_data(self, 
                 num_rows: int, 
                 output_voltages: List[str] = [], 
                 output_currents: List[str] = []
             ) -> Tuple[np.ndarray, Dict[str, np.ndarray], Dict[str, np.ndarray]]:
        """
        Get data points.
        :param num_rows: number of data points created by `self.tran()`
        """

        sim_data = self._get_data_raw(
            num_rows, output_voltages, output_currents
        )
        
        if sim_data.ndim != 2:
            logger.error("Simulation failed. No data was written to the output file.")
            if debug:
                pass
                # TODO logger.error(f"ngspice: {stderr}")
            assert False, "Simulation failed. No data was written to the output file."

        # Extract data from the numpy array.
        time = sim_data[:, 0]
        index = 1

        # Put voltages into a dict.
        voltages = dict()
        for v_out in output_voltages:
            voltages[v_out] = sim_data[:, index]
            index = index + 1

        # Put currents into a dict.
        currents = dict()
        for i_out in output_currents:
            currents[i_out] = sim_data[:, index]
            index = index + 1

        return time, voltages, currents

    def _get_data_raw(self, num_rows: int, voltages: List[str] = None, currents: List[str] = None) -> np.ndarray:
        # TODO use wrdata into a pipe (os.mkfifo()).
        self.drop_stdout()

        signals = []
        if voltages is not None:
            signals.extend((f"v({v})" for v in voltages))

        if currents is not None:
            signals.extend((f"i({i})" for i in currents))

        signals_str = " ".join(signals)

        self.cmd(f"set width={(1 + len(signals)) * 40}")
        self.cmd(f"print {signals_str}")

        rows = []
        i = 0
        while True:
            line = self.readline(timeout=1)
            assert line is not None
            if line.startswith(str(i)):
                i = i + 1
                arr = np.fromstring(line, dtype=float, sep=' ')
                rows.append(arr)
            if i == num_rows:
                break

        data = np.array(rows)
        # Remove index.
        data = data[:, 1:]

        return data

    def __check_err(self, timeout: float = 0.1):
        """
        Raise an exception on an error.
        """

        while True:
            err = self.readline_err(timeout=timeout)
            if err is None:
                break
            if err.startswith("Error"):
                raise Exception(f"ngspice error: {err}")


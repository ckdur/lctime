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
        input_voltages: Dict[str, Union[PieceWiseLinear, float]],
        output_load_capacitances: Dict[str, float] = None,
        setup_statements: List[str] = None,
        ground_net: str = "GND",
        simulation_title: str = "<UNTITLED SIMULATION>",
        ):
        assert isinstance(simulator, NgSpiceInteractive)
        self.simulator = simulator
        self.cell_name = cell_name
        self.cell_ports = cell_ports
        self.input_voltages = input_voltages
        self.simulation_title = simulation_title
        self.ground_net = ground_net
        self.temperature = 25
        self.output_load_capacitances = output_load_capacitances
        self.setup_statements = setup_statements

        self.initial_voltages = dict()
        for net, v in input_voltages.items():
            if isinstance(v, PieceWiseLinear):
                self.initial_voltages[net] = v(0)
            else:
                self.initial_voltages[net] = v

        # Set default value of outputs.
        for net in output_load_capacitances.keys():
            self.initial_voltages[net] = 0.0

        missing_voltages = set(cell_ports) - {ground_net} - input_voltages.keys() - output_load_capacitances.keys()
        if missing_voltages:
            logger.warning(f"missing voltage sources for input pins: {missing_voltages}")
            assert False

        self._init_simulation()

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
        signal_source_statements = _generate_input_voltage_statements(self.ground_net, self.input_voltages)

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

* Input and supply voltages.
{signal_source_statements}

Xcircuit_under_test {" ".join(self.cell_ports)} {self.cell_name}

{self._initial_conditions_stmts()}

.end
"""
        return sim_netlist

    def _initial_conditions_stmts(self):
        # TODO
        # Also all voltages of DC sources must be here if they are needed to compute the initial conditions.
        return f'.ic {" ".join((f"v({net})={{ic_{net.lower()}}}" for net, _ in self.initial_voltages.items()))}'

    def _params_initial_counditions(self):
        """
        Define variables (parameters) for the values of initial conditions. 
        """
        params = []

        for net, v in self.initial_voltages.items():
            params.append(f".param ic_{net.lower()}={v}")

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
        assert name.lower().startswith("c"), "capacitor name must start with C"
        self.simulator.cmd(f"alter {name} {value}")
        
    def set_capacitor_voltage(self, name: str, value: float):
        assert name.lower().startswith("c"), "capacitor name must start with C"
        self.simulator.cmd(f"alter {name} ic {value}")

    def set_resistance(self, name: str, value: float):
        assert name.lower().startswith("r"), "resistor name must start with R"
        self.simulator.cmd(f"alter {name} {value}")

    def set_voltage_dc(self, name: str, value: float):
        assert name.lower().startswith("v"), "voltage source name must start with V"
        self.simulator.cmd(f"alter {name} {value}")

    def set_voltage_pwl(self, name: str, pwl: PieceWiseLinear):
        assert name.lower().startswith("v"), "voltage source name must start with V"
        assert isinstance(pwl, PieceWiseLinear)
        self.simulator.cmd(f"alter {name} pwl = [ {pwl.to_spice_pwl_string()} ]")

    def set_voltage(self, name: str, voltage: Union[float, PieceWiseLinear]):
        if isinstance(voltage, PieceWiseLinear):
            self.set_voltage_dc(name, 0.0)
            self.set_voltage_pwl(name, voltage)
        else:
            self.set_voltage_dc(name, voltage)

    def set_initial_voltage(self, net: str, value: float):
        assert isinstance(value, float) or isinstance(value, int)
        self.simulator.cmd(f"alterparam ic_{net.lower()}={value}")

    def tran(self, t_step: float, t_stop: float, t_start=None) -> int:
        """
        Run transient simulation.

        Return number of datapoints.
        """
        return self.simulator.tran(t_step=t_step, t_stop=t_stop, t_start=t_start)

    def get_data(self, 
                 num_rows: int, 
                 output_voltages: List[str] = None, 
                 output_currents: List[str] = None
             ) -> np.ndarray:
        """
        Get data points.
        :param num_rows: number of data points created by `self.tran()`
        """

        sim_data = self.simulator.get_data(
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
        input_resistance = 0 # A small input resistance. TODO: parametrize this for each input pin
        source_statements.extend([
            __create_voltage_source_statement(ground_net, f"{net}", wave), # Ideal voltage source
        ])
        # source_statements.extend([
        #     __create_voltage_source_statement(ground_net, f"{net}_ideal", wave), # Ideal voltage source
        #     f"Rinput_{net} {net}_ideal {net} {input_resistance}" # Input resistance.
        # ])
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

class NgSpiceInteractive:
    """
    Interface to ngspice as a subprocess.
    """

    def __init__(self,
                 ngspice_executable: str = None,
                 logger: logging.Logger = None):
        self.logger = logger
        if logger is None:
            self.logger = logging.getLogger(__name__)
        self.ngspice_cmd = 'ngspice' if ngspice_executable is None else ngspice_executable
        self.ngspice_args = ['-p']
        "Run ngspice in interactive pipe mode."

        self.proc: subprocess.Popen[str] = None
        "ngspice process handle."

        self._from_stdout = queue.Queue()
        self._from_stderr = queue.Queue()

        self._stdout_reader_thread = None
        self._stderr_reader_thread = None

    def __stop(self):
        if self.proc:
            self.proc.kill()
            self.proc = None

    def __exit__(self, *args):
        self.__stop()

    def __enter__(self):
        self.__start()
        return self

    def __start(self):
        self.proc = subprocess.Popen(
            [self.ngspice_cmd] + self.ngspice_args,
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

    def cmd(self, cmd: str):
        self.logger.debug(f"ngspice> {cmd}")
        self._write(cmd)
        self._write('\n')
        self._flush()

    def source(self, file: str):
        """
        Load a netlist.
        """
        self.cmd(f"source {file}")

    def reset(self):
        self.cmd('reset')

    def tran(self, t_step, t_stop, t_start=None, uic='') -> int:
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

    def load_circuit(self, circuit: str):
        """
        Load a circuit over stdin.
        :param circuit:
        :return:
        """
        lines = circuit.split('\n')
        for line in lines:
            line = line.strip()
            if line:
                self._write("circbyline ")
                self._write(line)
                self._write('\n')
                self._flush()
        self.__check_err(timeout=0)

    def get_data(self, num_rows: int, voltages: List[str] = None, currents: List[str] = None) -> np.ndarray:
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

        err = self.readline_err(timeout=timeout)
        if err is not None:
            raise Exception(f"ngspice error: {err}")

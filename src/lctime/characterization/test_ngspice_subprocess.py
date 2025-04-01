# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import tempfile
import subprocess
import numpy as np
import matplotlib.pyplot as plt
import os
import asyncio
import logging
import threading, queue
import time
from typing import List

from .ngspice_subprocess import NgSpiceInteractive

def test_version_number():

    with NgSpiceInteractive() as sim:
        version = sim.version_string()
        assert version is not None
        assert version.startswith("ngspice-")
        assert version == version.strip()

def test_simple_simulation():
    """Run a simple transient simulation in a ngspice subprocess and retreive the results from a file."""

    sim_file = tempfile.mktemp()
    sim_output_file = tempfile.mktemp()

    spice_simulation_netlist = f"""
*
.title Simple RC circuit.

R1 VDD Y 1k
C1 Y GND 1u ic=0V
Vsrc_vdd VDD GND PWL(0 0 1ms 0V 2ms 1V)

.control
*option abstol=10e-15
*option reltol=10e-11
set filetype=ascii
* Enable output of vector names in the first line.
set wr_vecnames
tran 1ms 10ms
wrdata {sim_output_file} v(VDD) v(Y)
exit
.endc

.end
"""
    print(f"Write simulation file: {sim_file}")
    open(sim_file, 'w').write(spice_simulation_netlist)

    # Run simulation.
    ret = subprocess.run(["ngspice", sim_file])
    print(f"Subprocess return value: {ret}")
    if ret.returncode != 0:
        print(f"ngspice simulation failed: {ret}")
    assert ret.returncode == 0

    print(f"Read output data: {sim_output_file}")
    data = np.loadtxt(sim_output_file, skiprows=1)  # Skip the header.

    a_time = data[:, 0]
    a = data[:, 1]

    y_time = data[:, 2]
    y = data[:, 3]

    assert all(a_time == y_time)

    plt.plot(a_time, a, 'x-')
    plt.plot(y_time, y, 'x-')
    # Disable for automatic tests: plt.show()

    os.remove(sim_output_file)
    os.remove(sim_file)


def test_interactive_subprocess():
    import subprocess
    p = subprocess.Popen(['ngspice', '-p'],
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         universal_newlines=True)

    p.stdin.write("a\n")
    p.stdin.flush()
    print(p.stderr.readline())

    p.stdin.write("quit\n")
    p.stdin.flush()
    print(p.stdout.readlines())
    print(p.stderr.readlines())


def test_ngspice_interactive_simple():

    with NgSpiceInteractive() as sim:

        sim.load_circuit(r"""
.title test RC circuit
C1 0 A 0.001
R1 0 A 100

.ic v(a)=2
.end
""")

        time, voltages, currents = sim.tran(
            t_step=0.001, t_stop=1,
            output_voltages=["A"]
        )
        voltage_a = voltages["A"]
        assert time[0] == 0.0

        assert abs(voltage_a[0]-2) < 1e-6
        assert voltage_a[-1] < 0.01, "voltage over capacitor should decay"
        
def test_ngspice_subprocess_class():

    spice_simulation_netlist = f"""
*
.title Simple RC circuit.

.param voltage_end = 1V

R1 VDD Y 1k
C1 Y GND 1u ic=0V
Vsrc_vdd VDD GND PWL(0 0 1ms 0V 2ms {{voltage_end}})

.end
    """

    with NgSpiceInteractive() as ns:

        # ns.source(sim_file)
        ns.load_circuit(spice_simulation_netlist)

        # ns.cmd(spice_simulation_netlist)
        # ns.cmd('set filetype=ascii')
        # ns.cmd('tran 1ms 1ms')
        time1, v1, i1 = ns.tran(t_step='1ms', t_stop='1ms',
             output_voltages=['VDD', 'Y'], output_currents=['vsrc_vdd']
         )
        assert v1['VDD'][0] == 0
        assert v1['VDD'][-1] == 0

        err = ns.readline_err()
        assert err == None, f"ngspice error: {err}"

        time, v2, i2 = ns.tran(t_step='1ms', t_stop='2ms', 
                output_voltages=['VDD', 'Y'], output_currents=['vsrc_vdd']
            )
        assert v2['VDD'][0] == 0
        assert v2['VDD'][-1] == 1
        # ns.cmd('wrdata /dev/stdout v(VDD) v(Y)')

        err = ns.readline_err()
        assert err == None, f"ngspice error: {err}"


        # Re-run the simulation with another wave form.
        ns.reset()
        # update the waveform
        ns.cmd("alter Vsrc_vdd pwl = [ 0 0 1ms 0V 2ms 2V ]")
        # Change capacitor value
        ns.cmd("alter C1 = 2u")
        #ns.cmd("alterparam voltage_end = 2V")
        time, v2, i2 = ns.tran(t_step='1ms', t_stop='2ms',
                        output_voltages=['VDD', 'Y'],
                        output_currents=['vsrc_vdd']
                    )
        err = ns.readline_err()
        assert err == None, f"ngspice error: {err}"
        assert v2["VDD"][0] == 0
        assert v2["VDD"][-1] == 2, "failed to alter the piece-wise linear voltage source"


#class NgSpiceAsync:
#    """
#    Asynchronous interface to ngspice as a subprocess.
#    """
#
#    def __init__(self, logger: logging.Logger = None):
#        if logger is None:
#            logger = logging.getLogger(__name__)
#        self.logger = logger
#        self.ngspice_cmd = "ngspice"
#        self.ngspice_args = ['-p']
#        "Run ngspice in interactive pipe mode."
#
#        self.proc = None
#        "ngspice process handle."
#
#    async def start(self):
#        self.proc = await asyncio.create_subprocess_exec(
#            self.ngspice_cmd,
#            *self.ngspice_args,
#            stdin=asyncio.subprocess.PIPE,
#            stdout=asyncio.subprocess.PIPE,
#            stderr=asyncio.subprocess.PIPE,
#        )
#
#    async def cmd(self, cmd: bytes):
#        if not cmd.endswith(b"\n"):
#            cmd += b"\n"
#        self.logger.debug(f"Run cmd: {cmd}")
#        print(f"Run cmd: {cmd}")
#        # cmd = cmd.encode('utf-8')
#        stdout, stderr = await self.proc.communicate(input=cmd)
#        self.logger.debug(f"stdout: {stdout}")
#        print(f"stdout: {stdout}")
#        self.logger.debug(f"stderr: {stderr}")
#        print(f"stderr: {stderr}")
#
#        print(f"return code: {self.proc.returncode}")
#
#
#def test_async_interactive_subprocess():
#
#    async def run():
#        
#        ns = NgSpiceAsync()
#        try:
#            async with asyncio.timeout(1):
#                await ns.start()
#                await ns.cmd(b"help")
#                await ns.cmd(b"help")
#                await ns.cmd(b"quit")
#        except Exception as e:
#            if ns.proc:
#                ns.proc.kill()
#            raise e
#
#    asyncio.run(run())
#
#
#def test_async_interactive_subprocess_raw():
#
#    async def run():
#        
#        proc = None
#        try:
#            async with asyncio.timeout(1):
#            
#                cmd = 'ngspice -p'
#                proc = await asyncio.create_subprocess_exec(
#                    'ngspice',
#                    '-p',
#                    stdin=asyncio.subprocess.PIPE,
#                    stdout=asyncio.subprocess.PIPE,
#                    stderr=asyncio.subprocess.PIPE,
#                )
#
#                stdout, stderr = await proc.communicate(input=b"help\n")
#                print(stdout)
#                print(stderr)
#                stdout, stderr = await proc.communicate(input=b"quit\n")
#
#                print(f'[{cmd!r} exited with {proc.returncode}]')
#                if stdout:
#                    print(f'[stdout]\n{stdout.decode()}')
#                if stderr:
#                    print(f'[stderr]\n{stderr.decode()}')
#        except Exception as e:
#            if proc:
#                proc.kill()
#            raise e
#
#    asyncio.run(run())
#

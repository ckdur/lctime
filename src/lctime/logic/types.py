# Copyright (c) 2019-2021 Thomas Kramer.
# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from sympy.logic import satisfiable
from sympy.logic import boolalg
import sympy
from typing import Set


class CombinationalOutput:
    """
    Description of an output signal of a combinatorial circuit.
    """

    def __init__(self, function: boolalg.Boolean, high_impedance: boolalg.Boolean):
        self.function: boolalg.Boolean = function
        "Boolean expression for the logic output."
        self.high_impedance: boolalg.Boolean = high_impedance
        "Boolean expression which tells when the output is in high-impedance state."

    def is_tristate(self):
        """
        Check if the output have be high-impedance.
        Check if the high-impedance condition is satisfiable.
        :return: bool
        """
        if self.high_impedance is None:
            return False
        return satisfiable(self.high_impedance)

    def get_inputs(self) -> Set[sympy.Symbol]:
        """
        Find all input pins that are relevant for the outputs.
        :return: Set of input pins.
        """
        pins = set()
        if self.function is not None:
            pins.update(self.function.atoms(sympy.Symbol))
        if self.high_impedance is not None:
            pins.update(self.high_impedance.atoms(sympy.Symbol))
        return pins

    def __str__(self):
        if self.high_impedance:
            return f"CombinationalOutput(f = {self.function}, Z = {self.high_impedance})"
        else:
            return f"CombinationalOutput(f = {self.function})"

    def __repr__(self):
        return str(self)

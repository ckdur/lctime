# SPDX-FileCopyrightText: 2022 Thomas Kramer <code@tkramer.ch>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

from enum import Enum

from copy import deepcopy
from typing import Any, Tuple


class ChannelType(Enum):
    NMOS = 1,
    PMOS = 2


class Transistor:
    """
    Abstract representation of a MOS transistor.
    """

    def __init__(self, channel_type: ChannelType,
                 source_net: str, gate_net: str, drain_net: str,
                 channel_width=None,
                 name: str = 'M?',
                 allow_flip_source_drain: bool = True
                 ):
        """
        params:
        left: Either source or drain net.
        right: Either source or drain net.
        """
        self.name = name
        self.channel_type = channel_type
        self.source_net = source_net
        self.gate_net = gate_net
        self.drain_net = drain_net

        self.channel_width = channel_width

        self.allow_flip_source_drain = allow_flip_source_drain

        # TODO
        self.threshold_voltage = None

    def flipped(self):
        """ Return the same transistor but with left/right terminals flipped.
        """

        assert self.allow_flip_source_drain, "Flipping source and drain is not allowed."

        f = deepcopy(self)
        f.source_net = self.drain_net
        f.drain_net = self.source_net

        return f

    def terminals(self) -> Tuple[Any, Any, Any]:
        """ Return a tuple of all terminal names.
        :return:
        """
        return self.source_net, self.gate_net, self.drain_net

    def __key(self):
        return self.name, self.channel_type, self.source_net, self.gate_net, self.drain_net, self.channel_width, self.threshold_voltage

    def __hash__(self):
        return hash(self.__key())

    def __eq__(x, y):
        return x.__key() == y.__key()

    def __repr__(self):
        return "({}, {}, {})".format(self.source_net, self.gate_net, self.drain_net)


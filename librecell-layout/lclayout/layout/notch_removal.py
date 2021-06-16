#
# Copyright 2019-2020 Thomas Kramer.
#
# This source describes Open Hardware and is licensed under the CERN-OHL-S v2.
#
# You may redistribute and modify this documentation and make products using it
# under the terms of the CERN-OHL-S v2 (https:/cern.ch/cern-ohl).
# This documentation is distributed WITHOUT ANY EXPRESS OR IMPLIED WARRANTY,
# INCLUDING OF MERCHANTABILITY, SATISFACTORY QUALITY AND FITNESS FOR A PARTICULAR PURPOSE.
# Please see the CERN-OHL-S v2 for applicable conditions.
#
# Source location: https://codeberg.org/tok/librecell
#
import klayout.db as pya

import logging

logger = logging.getLogger(__name__)


def fill_notches(region: pya.Region, minimum_notch: int) -> pya.Region:
    """ Fill notches in a pya.Region.
    :param region:
    :param minimum_notch:
    :return:
    """
    merged = region.merged()

    # Find notches.
    notches = merged.notch_check(minimum_notch)
    spaces = merged.space_check(minimum_notch)
    notches = list(notches) + list(spaces)
    s = pya.Shapes()
    s.insert(region)

    # Fill each notch with a rectangle.
    for edge_pair in notches:
        a, b = edge_pair.first, edge_pair.second
        # Find smaller edge (a)
        a, b = sorted((a, b), key=lambda e: e.length())

        # Construct a minimal box to fill the notch
        box = a.bbox()
        # Extend box of shorted edge by points of longer edge
        box1 = box + b.p1
        box2 = box + b.p2

        # Take the smaller box.
        min_box = min([box1, box2], key=lambda b: b.area())

        logger.debug(f"Fill notch: {min_box}")

        s.insert(min_box)

    result = pya.Region(s)
    result.merge()
    return result


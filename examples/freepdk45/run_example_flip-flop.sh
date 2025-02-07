#!/bin/bash

# SPDX-FileCopyrightText: 2022 Thomas Kramer
#
# SPDX-License-Identifier: CC0-1.0

# Characterize the DFFSR flip-flop (with set and reset).

NETLIST_DIR="../test_data/freepdk45/netlists_pex"

lctime --liberty template.lib \
    --analyze-cell-function \
    --include gpdk45nm.m \
    --spice $NETLIST_DIR/DFFSR.pex.netlist \
    --cell DFFSR \
    --output-loads "0.05" \
    --slew-times "0.1" \
    --related-pin-transition "0.1" \
    --output dffsr.lib

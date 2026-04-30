#!/bin/bash

# SPDX-FileCopyrightText: 2026 Thomas Kramer, mbarlow
#
# SPDX-License-Identifier: CC0-1.0

# Characterize a slow version of the DFFSR flip-flop (with set and reset).
# See https://codeberg.org/librecell/lctime/issues/41

NETLIST_DIR="../../test_data/freepdk45/netlists_pex"

lctime --liberty template.lib \
    --analyze-cell-function \
    --include gpdk45nm.m \
    --workingdir tmp \
    --spice DFFSR_slow.pex.netlist \
    --cell DFFSR \
    --output-loads "0.05" \
    --slew-times "0.1" \
    --related-pin-transition "0.1" \
    --debug \
    --debug-plots \
    --output dffsr.lib


#!/bin/bash

set -e

OUT_DIR=$(mktemp -d)
DATA_DIR=data/freepdk45

function clean {
    rm -rf $OUT_DIR
}

trap clean EXIT


echo TEST: Guide the characterization based on a template liberty file which contains a specification of the cell pins.
lctime --liberty invx1_template.lib \
    --include gpdk45nm.m \
    --spice INVX1.pex.netlist \
    --cell INVX1 \
    --output-loads "0.05, 1.6" \
    --slew-times "0.1, 3.2" \
    --output $OUT_DIR/invx1.lib

echo TEST: Case sensitivity of cell names.
lctime --liberty lowercase_invx1_template.lib \
    --include gpdk45nm.m \
    --spice lowercase_invx1.pex.netlist \
    --cell invx1 \
    --output-loads "0.05" \
    --slew-times "0.1" \
    --output $OUT_DIR/lower_case_invx1.lib

echo TEST: detect cell functionality
# Here the template liberty file does NOT contain a cell specification.
# With the --analize-cell-function flag the cell specification will be infered from the netlist.
lctime --liberty template.lib \
    --analyze-cell-function \
    --include gpdk45nm.m \
    --spice AND2X1.pex.netlist \
    --cell AND2X1 \
    --output-loads "0.05, 1.6" \
    --slew-times "0.1, 3.2" \
    --output $OUT_DIR/and2x1.lib

echo TEST OK

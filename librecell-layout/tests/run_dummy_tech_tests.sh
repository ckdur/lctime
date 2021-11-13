#!/bin/bash

set -e

OUT_DIR=$(mktemp -d)
DATA_DIR=data/dummy_tech

function clean {
    rm -rf $OUT_DIR
}

trap clean EXIT


echo "Test generating a layout of a simple INVX1 cell."
lclayout --output-dir $OUT_DIR --tech $DATA_DIR/dummy_tech.py --netlist $DATA_DIR/cells.sp --cell INVX1 --verbose

echo "Test generating a layout of a cell with lower case name."
lclayout --output-dir $OUT_DIR --tech $DATA_DIR/dummy_tech.py --netlist $DATA_DIR/cells.sp --cell lower_case_and2x1 --verbose


echo TEST OK

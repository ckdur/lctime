#!/bin/bash

set -e

OUT_DIR=$(mktemp -d)
DATA_DIR=data/freepdk45

function clean {
    rm -rf $OUT_DIR
}

trap clean EXIT


echo TEST: Recognize INVX1
sp2bool --spice INVX1.pex.netlist

echo TEST: Recognize AND2X1
sp2bool --spice AND2X1.pex.netlist

# TODO: Include flip-flops & latches 

echo TEST OK

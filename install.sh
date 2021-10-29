#!/bin/bash

# Install librecell. The install will make an independent copy of the code.
# Edits in the repository will not affect the installed version.

set -e

INSTALL="pip install --upgrade"

# Install library code shared by multiple parts of librecell.
$INSTALL ./librecell-common

# Install lclayout
$INSTALL ./librecell-layout

# Install lclib
$INSTALL ./librecell-lib

#cd librecell-meta
#python3 setup.py install
#cd ..

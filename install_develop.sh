#!/bin/bash

# Install librecell in development mode.
# The installed package will just link to this repository. Changes in the repository affect the installation immediately.

set -e

INSTALL="pip install --upgrade --editable"

# Install library code shared by multiple parts of librecell.
$INSTALL ./librecell-common

# Install lclayout
$INSTALL ./librecell-layout

# Install lclib
$INSTALL ./librecell-lib

#cd librecell-meta
#python3 setup.py install
#cd ..

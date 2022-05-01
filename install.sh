#!/bin/bash

# Install librecell. The install will make an independent copy of the code.
# Edits in the repository will not affect the installed version.

set -e

INSTALL="pip install --upgrade"

# Install lctime
$INSTALL .


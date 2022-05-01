#!/bin/bash

# Install librecell in development mode.
# The installed package will just link to this repository. Changes in the repository affect the installation immediately.

set -e

INSTALL="pip install --upgrade --editable"

# Install lctime
$INSTALL .


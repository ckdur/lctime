#!/bin/bash

# SPDX-FileCopyrightText: 2022 Thomas Kramer
#
# SPDX-License-Identifier: CC0-1.0

# Install librecell in development mode.
# The installed package will just link to this repository. Changes in the repository affect the installation immediately.

set -e

INSTALL="pip install --upgrade --editable"

# Install lctime
$INSTALL .


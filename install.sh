#!/bin/bash

# SPDX-FileCopyrightText: 2022-2024 Thomas Kramer
#
# SPDX-License-Identifier: CC0-1.0

# Install lctime. The install will make an independent copy of the code.
# Edits in the repository will not affect the installed version.

set -e

pip install --upgrade .


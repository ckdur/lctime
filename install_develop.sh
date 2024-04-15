#!/bin/bash

# SPDX-FileCopyrightText: 2022-2024 Thomas Kramer
#
# SPDX-License-Identifier: CC0-1.0

# Install lctime in development mode.
# The installed package will just link to this repository. Changes in the repository affect the installation immediately.

set -e

pip install --upgrade --editable .



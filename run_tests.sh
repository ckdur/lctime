#!/bin/bash

# SPDX-FileCopyrightText: 2022 Thomas Kramer
#
# SPDX-License-Identifier: CC0-1.0

set -e

if [ "$(which pytest)" ]; then
  echo run unit tests...
  pytest $(find src/ -name \*.py)
else
  echo "pytest not found, skipping unit tests"
fi

echo run integration tests...
cd tests/
./run_tests.sh

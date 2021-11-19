#!/bin/bash

# Run all integration tests of librecell.
# TODO: also run unit tests with `nosetest`.

set -e

LCDIR=$PWD

echo TEST: lclayout
cd $LCDIR/librecell-layout/tests
./run_dummy_tech_tests.sh

echo TEST: lctime
cd $LCDIR/librecell-lib/tests
./run_tests.sh


echo TEST OK

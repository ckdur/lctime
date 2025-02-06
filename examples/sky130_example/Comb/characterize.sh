#/bin/bash

#Possible usages:

#./characterize.sh sky130_as_sc_hs__clkbuff_8 "0.0005, 0.00175, 0.00612, 0.0213, 0.074, 0.260, 0.91" "0.01, 0.023, 0.055, 0.12, 0.28, 0.65, 1.5"

#./characterize.sh sky130_as_sc_hs__xnor2_2 "0.0005, 0.00182, 0.0057, 0.019, 0.051, 0.18, 0.3" "0.01, 0.023, 0.053, 0.122, 0.28, 0.65, 1.5"

#./characterize.sh sky130_as_sc_hs__mux2_4 "0.0005, 0.0014, 0.006, 0.02, 0.066, 0.16, 0.47" "0.01, 0.023, 0.053, 0.122, 0.28, 0.65, 1.5"

#./characterize.sh sky130_as_sc_hs__aoi211_2 "0.0005, 0.00125, 0.003, 0.0075, 0.019, 0.04, 0.1" "0.01, 0.023, 0.053, 0.122, 0.28, 0.65, 1.5"

set -e

lctime --liberty template.lib --library "/foss/pdks/sky130A/libs.tech/combined/sky130.lib.spice tt" --output-loads "$2" --slew-times "$3" --spice $1.spice --cell $1 --output ./test.lib

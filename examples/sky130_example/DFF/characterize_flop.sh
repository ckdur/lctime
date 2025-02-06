#/bin/bash

#Usage:
#./characterize_flop.sh [cell name] "0.0005, 0.00177, 0.005, 0.017, 0.042, 0.15, 0.3" "0.01, 0.023, 0.053, 0.122, 0.28, 0.65, 1.5" "0.01, 0.5, 1.5"
#Available demo cells:
#sky130_as_sc_hs__dfxtp_2 - DFF with only Q output, rising-edge triggered
#sky130_as_sc_hs__dfxtn_2 - DFF with only Q output, falling-edge triggered
#sky130_as_sc_hs__dfxbp_2 - DFF with Q and !Q outputs, rising-edge triggered

set -e

lctime --liberty template.lib --library "/foss/pdks/sky130A/libs.tech/combined/sky130.lib.spice tt" --output-loads "$2" --slew-times "$3" --spice $1.spice --cell $1 --output ./test.lib --related-pin-transition "$4"

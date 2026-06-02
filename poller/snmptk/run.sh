#!/bin/bash

make

# ./snmptk --name pontraffic --snmppoll /home/pms/online/etc/pontraffic60m.yml --timeout 900
./snmptk --name oltuplink60m --snmppoll /home/pms/online/etc/oltuplink60m.yml --timeout 900
# ./snmptk --name oltpon60m --snmppoll /home/pms/online/etc/oltpon60m.yml --timeout 900
# ./snmptk --name onupon60m --snmppoll /home/pms/online/etc/onupon60m.yml --timeout 10800


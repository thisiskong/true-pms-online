#!/bin/bash

make

# olt dasan
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.178.153.10

# olt fiberhome
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.237.153.6
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.237.151.3
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.237.17.2
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.237.2.2

# olt raisecom
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.177.152.52
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.167.117.83
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.177.189.8

# olt raisecom & cpe
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.177.152.52
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.167.117.83

# olt gcom
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.179.153.11

# olt gcom & cpe
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.179.151.124
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.167.7.163

# olt zte
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.239.152.25
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.239.77.246
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.239.77.248
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.239.83.8
# olt zte c610
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.239.123.8

# olt huawei
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.238.152.16

# olt nokia
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.237.205.147

# zte vdsl
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.239.214.76

# cpe zte
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.167.100.88

# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.238.118.6

# huawei wrong model
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.238.155.27

# huawei X2
# snmpget -v2c -c public123 -On 10.238.19.21 1.3.6.1.2.1.1.2.0
# .1.3.6.1.2.1.1.2.0 = OID: .1.3.6.1.4.1.2011.2.317
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.238.19.21


# lat/lng
# snmptk --disc /home/pms/online/etc/disc.yml --discip 10.177.176.27

# huawei board
# snmptk --disc /home/pms/online/etc/disc.yml --discip 10.238.152.16
snmptk --disc /home/pms/online/etc/disc.yml --discip 10.238.1.4

# fiberhome board
# snmptk --disc /home/pms/online/etc/disc.yml --discip 10.237.152.2

# zte board
# snmptk --disc /home/pms/online/etc/disc.yml --discip 10.239.165.15

# nokia dstsite
# snmptk --disc /home/pms/online/etc/disc.yml --discip 10.237.165.131 --debug


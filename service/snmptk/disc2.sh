#!/bin/bash

make

# olt dasan
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.178.153.10

# olt fiberhome
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.237.153.6

# olt raisecom
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.177.152.52 > raisecom-olt.log
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.167.117.83 > raisecom-cpe.log
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.177.189.8

# cpe connected to olt raisecome
snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.167.246.15

# olt gcom
# snmptk --disc /home/pms/online/etc/disc.yml --debug --discip 10.179.153.11


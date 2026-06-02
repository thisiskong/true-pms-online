#!/bin/bash

# traffic5m-tuty02nxgw09-20221021T2025.json
outdir=/home/pms/online/data
dt=$(date --date "5 minutes ago" +"%Y%m%dT%H%M")
dd=$(date --date "5 minutes ago" +"%Y%m%d")

jsonfile="traffic5m-${HOSTNAME}-${dt}.json"
tsdbfile="traffic5m-${HOSTNAME}-${dt}.tsdb"

echo "dt=${dt}, jsonfile=${jsonfile}, tsdbfile=${tsdbfile}"

# cd /home/pms
./snmptk --name traffic5m --snmpget /home/pms/online/etc/traffic5m.yml \
  --poll 300 \
  --timeout 360 \
  --delta ${outdir}/traffic5m.json/${jsonfile} \
  --tsdb ${outdir}/traffic5m.tsdb/${tsdbfile} \
  --offline ${outdir}/traffic5m-offline.json

#  >> /home/pms/online/logs/traffic5m.${dd}.log 2>&1

# copy json file for datalake
# cp -f ${outdir}/traffic5m.json/${jsonfile} ${outdir}/traffic5m.dl/${jsonfile}


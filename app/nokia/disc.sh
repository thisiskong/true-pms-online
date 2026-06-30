#!/bin/bash

# get token
# uv run python -m nokia.main --server 10.50.238.203 --username adminuser --password password --no-verify-ssl

# full response
# uv run python -m nokia.main --server 10.50.238.203 --username adminuser --password password --no-verify-ssl --output json

# discovery
uv run python -m nokia.discovery --server 10.50.238.203 --username adminuser --password password --no-verify-ssl --output-dir output

# mapper
# input:  output/device.jsonl, output/intf.jsonl, output/ponport.jsonl
# output: output/devices.jsonl
uv run python -m nokia.mapper --output-dir output

# cd C:\Users\ST\GitHub\true-pms-online\poller\snmptk
# make build-win
./snmptk.exe --disc disc.yml --discid 313490 --devicefile C:/Users/ST/GitHub/true-pms-online/app/nokia/output/devices.json

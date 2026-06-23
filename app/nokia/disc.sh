#!/bin/bash

# get token
# uv run python main.py --server 10.50.238.203 --username adminuser --password password --no-verify-ssl

# full response
# uv run python main.py --server 10.50.238.203 --username adminuser --password password --no-verify-ssl --output json

# discovery
uv run python discover.py --server 10.50.238.203 --username adminuser --password password --no-verify-ssl

# mapper
# output/devices.jsonl
uv run python mapper.py

# cd C:\Users\ST\GitHub\true-pms-online\poller\snmptk
# make build-win
./snmptk.exe --disc disc.yml --discid 313490 --devicefile C:/Users/ST/GitHub/true-pms-online/app/nokia/output/devices.json

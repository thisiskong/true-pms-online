#!/bin/bash

# get token
# uv run python main.py --server 10.50.238.203 --username adminuser --password password --no-verify-ssl

# full response
# uv run python main.py --server 10.50.238.203 --username adminuser --password password --no-verify-ssl --output json

# discovery
uv run python discover.py --server 10.50.238.203 --username adminuser --password password --no-verify-ssl

# mapper
uv run python mapper.py
